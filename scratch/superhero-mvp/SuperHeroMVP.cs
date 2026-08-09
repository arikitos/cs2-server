using System.Text.Json;
using System.Text.Json.Serialization;
using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Core.Attributes;
using CounterStrikeSharp.API.Core.Attributes.Registration;
using CounterStrikeSharp.API.Modules.Commands;
using CounterStrikeSharp.API.Modules.Extensions;
using CounterStrikeSharp.API.Modules.Timers;
using CounterStrikeSharp.API.Modules.Utils;
using Microsoft.Extensions.Logging;

namespace SuperHeroMVP;

public sealed class SuperHeroConfig : BasePluginConfig
{
    [JsonPropertyName("ChatPrefix")]
    public string ChatPrefix { get; set; } = "[SH]";

    [JsonPropertyName("XpPerKill")]
    public int XpPerKill { get; set; } = 20;

    [JsonPropertyName("HeadshotBonusXp")]
    public int HeadshotBonusXp { get; set; } = 10;

    [JsonPropertyName("LevelThresholds")]
    public int[] LevelThresholds { get; set; } = [0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200, 4000];

    [JsonPropertyName("WolverineRegenPerSecond")]
    public int WolverineRegenPerSecond { get; set; } = 5;

    [JsonPropertyName("DraculaLifestealPercent")]
    public float DraculaLifestealPercent { get; set; } = 0.20f;

    [JsonPropertyName("HulkPowerSeconds")]
    public float HulkPowerSeconds { get; set; } = 8.0f;

    [JsonPropertyName("HulkCooldownSeconds")]
    public float HulkCooldownSeconds { get; set; } = 30.0f;
}

public sealed class PlayerProfile
{
    public int Xp { get; set; }
    public List<string> Heroes { get; set; } = [];
}

public sealed record HeroDefinition(
    string Id,
    string DisplayName,
    int MinimumLevel,
    string Description,
    bool ActivePower = false);

[MinimumApiVersion(80)]
public sealed class SuperHeroMvpPlugin : BasePlugin, IPluginConfig<SuperHeroConfig>
{
    public override string ModuleName => "SuperHero MVP";
    public override string ModuleVersion => "0.1.0";
    public override string ModuleAuthor => "Arikitos + OpenAI";
    public override string ModuleDescription => "AMX Mod X SuperHero inspired MVP for Counter-Strike 2";

    public SuperHeroConfig Config { get; set; } = new();

    private readonly Dictionary<ulong, PlayerProfile> _profiles = [];
    private readonly Dictionary<ulong, float> _hulkCooldownUntil = [];
    private readonly Dictionary<ulong, float> _hulkActiveUntil = [];

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private static readonly HeroDefinition[] Heroes =
    [
        new("superman", "Superman", 0, "+50 HP, armor and lower gravity"),
        new("flash", "Flash", 1, "Increased movement speed"),
        new("wolverine", "Wolverine", 2, "Regenerates health every second"),
        new("batman", "Batman", 3, "Receives a tactical weapon loadout on spawn"),
        new("dracula", "Dracula", 4, "Steals health from damage dealt"),
        new("hulk", "Hulk", 5, "Active rage power with speed and armor boost", true)
    ];

    private string DataPath => Path.Combine(ModuleDirectory, "players.json");

    public void OnConfigParsed(SuperHeroConfig config)
    {
        if (config.LevelThresholds.Length == 0 || config.LevelThresholds[0] != 0)
        {
            throw new InvalidOperationException("LevelThresholds must start with 0.");
        }

        for (var i = 1; i < config.LevelThresholds.Length; i++)
        {
            if (config.LevelThresholds[i] <= config.LevelThresholds[i - 1])
            {
                throw new InvalidOperationException("LevelThresholds must be strictly increasing.");
            }
        }

        config.DraculaLifestealPercent = Math.Clamp(config.DraculaLifestealPercent, 0.0f, 1.0f);
        config.WolverineRegenPerSecond = Math.Clamp(config.WolverineRegenPerSecond, 0, 100);
        config.HulkPowerSeconds = Math.Clamp(config.HulkPowerSeconds, 1.0f, 60.0f);
        config.HulkCooldownSeconds = Math.Max(config.HulkCooldownSeconds, config.HulkPowerSeconds);
        Config = config;
    }

    public override void Load(bool hotReload)
    {
        LoadProfiles();

        RegisterEventHandler<EventPlayerSpawn>(OnPlayerSpawn);
        RegisterEventHandler<EventPlayerDeath>(OnPlayerDeath);
        RegisterEventHandler<EventPlayerHurt>(OnPlayerHurt);

        AddTimer(0.10f, ApplyMovementEffects, TimerFlags.REPEAT);
        AddTimer(1.00f, RegenTick, TimerFlags.REPEAT);
        AddTimer(10.0f, SaveProfilesSafe, TimerFlags.REPEAT);

        Logger.LogInformation("SuperHero MVP {Version} loaded. Profiles: {Count}", ModuleVersion, _profiles.Count);
    }

    public override void Unload(bool hotReload)
    {
        SaveProfilesSafe();
        Logger.LogInformation("SuperHero MVP unloaded.");
    }

    private HookResult OnPlayerSpawn(EventPlayerSpawn @event, GameEventInfo info)
    {
        var player = @event.Userid;
        if (!IsUsablePlayer(player)) return HookResult.Continue;

        EnsureProfile(player!);
        AddTimer(0.20f, () =>
        {
            if (!IsUsablePlayer(player)) return;
            ApplySpawnEffects(player!);
        });

        return HookResult.Continue;
    }

    private HookResult OnPlayerDeath(EventPlayerDeath @event, GameEventInfo info)
    {
        var attacker = @event.Attacker;
        var victim = @event.Userid;

        if (!IsUsablePlayer(attacker) || attacker == victim) return HookResult.Continue;

        var gained = Config.XpPerKill + (@event.Headshot ? Config.HeadshotBonusXp : 0);
        AddXp(attacker!, gained);
        return HookResult.Continue;
    }

    private HookResult OnPlayerHurt(EventPlayerHurt @event, GameEventInfo info)
    {
        var attacker = @event.Attacker;
        var victim = @event.Userid;

        if (!IsUsablePlayer(attacker) || attacker == victim) return HookResult.Continue;
        if (!HasHero(attacker!, "dracula")) return HookResult.Continue;

        var pawn = attacker!.PlayerPawn.Get();
        if (pawn == null || pawn.Health <= 0) return HookResult.Continue;

        var maxHealth = GetDesiredMaxHealth(attacker);
        var heal = Math.Max(1, (int)MathF.Round(@event.DmgHealth * Config.DraculaLifestealPercent));
        var newHealth = Math.Min(maxHealth, pawn.Health + heal);
        if (newHealth == pawn.Health) return HookResult.Continue;

        pawn.Health = newHealth;
        Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
        return HookResult.Continue;
    }

    private void ApplySpawnEffects(CCSPlayerController player)
    {
        var pawn = player.PlayerPawn.Get();
        if (pawn == null || pawn.Health <= 0) return;

        ResetRuntimePawnFields(pawn);

        var maxHealth = GetDesiredMaxHealth(player);
        if (maxHealth > 100)
        {
            pawn.MaxHealth = maxHealth;
            pawn.Health = maxHealth;
            Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iMaxHealth");
            Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
        }

        if (HasHero(player, "superman"))
        {
            pawn.ArmorValue = Math.Max(pawn.ArmorValue, 100);
            pawn.GravityScale = 0.80f;
            Utilities.SetStateChanged(pawn, "CCSPlayerPawn", "m_ArmorValue");
            Utilities.SetStateChanged(pawn, "CBaseEntity", "m_flGravityScale");
        }

        if (HasHero(player, "batman"))
        {
            GiveBatmanLoadout(player);
        }
    }

    private void ResetRuntimePawnFields(CCSPlayerPawn pawn)
    {
        pawn.MaxHealth = 100;
        if (pawn.Health > 100) pawn.Health = 100;
        pawn.GravityScale = 1.0f;
        pawn.VelocityModifier = 1.0f;

        Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iMaxHealth");
        Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
        Utilities.SetStateChanged(pawn, "CBaseEntity", "m_flGravityScale");
        Utilities.SetStateChanged(pawn, "CCSPlayerPawn", "m_flVelocityModifier");
    }

    private void GiveBatmanLoadout(CCSPlayerController player)
    {
        if (!IsUsablePlayer(player)) return;

        try
        {
            player.GiveNamedItem("weapon_deagle");
            player.GiveNamedItem("weapon_m4a1");
            player.GiveNamedItem("weapon_hegrenade");
            player.GiveNamedItem("weapon_flashbang");
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Batman loadout failed for {Player}", player.PlayerName);
        }
    }

    private void ApplyMovementEffects()
    {
        var now = Server.CurrentTime;

        foreach (var player in Utilities.GetPlayers())
        {
            if (!IsUsablePlayer(player)) continue;
            var pawn = player.PlayerPawn.Get();
            if (pawn == null || pawn.Health <= 0) continue;

            var speedMultiplier = 1.0f;
            if (HasHero(player, "flash")) speedMultiplier = 1.20f;
            if (_hulkActiveUntil.TryGetValue(player.SteamID, out var activeUntil) && activeUntil > now)
            {
                speedMultiplier = Math.Max(speedMultiplier, 1.35f);
            }

            if (speedMultiplier > 1.0f)
            {
                pawn.VelocityModifier = speedMultiplier;
                Utilities.SetStateChanged(pawn, "CCSPlayerPawn", "m_flVelocityModifier");
            }

            if (HasHero(player, "superman"))
            {
                pawn.GravityScale = 0.80f;
                Utilities.SetStateChanged(pawn, "CBaseEntity", "m_flGravityScale");
            }
        }
    }

    private void RegenTick()
    {
        foreach (var player in Utilities.GetPlayers())
        {
            if (!IsUsablePlayer(player) || !HasHero(player, "wolverine")) continue;
            var pawn = player.PlayerPawn.Get();
            if (pawn == null || pawn.Health <= 0) continue;

            var maxHealth = GetDesiredMaxHealth(player);
            if (pawn.Health >= maxHealth) continue;

            pawn.Health = Math.Min(maxHealth, pawn.Health + Config.WolverineRegenPerSecond);
            Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
        }
    }

    [ConsoleCommand("css_sh", "Show SuperHero status and commands")]
    public void CommandStatus(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        var profile = EnsureProfile(player!);
        var level = GetLevel(profile.Xp);
        var nextXp = level + 1 < Config.LevelThresholds.Length ? Config.LevelThresholds[level + 1].ToString() : "MAX";
        var heroes = profile.Heroes.Count == 0 ? "none" : string.Join(", ", profile.Heroes.Select(GetHeroDisplayName));

        command.ReplyToCommand($"{Config.ChatPrefix} Level {level}, XP {profile.Xp}/{nextXp}, slots {profile.Heroes.Count}/{GetHeroSlots(level)}, heroes: {heroes}");
        command.ReplyToCommand($"{Config.ChatPrefix} Commands: !heroes, !selecthero <name>, !drophero <name>, !myheroes, !power");
    }

    [ConsoleCommand("css_heroes", "List available SuperHero heroes")]
    public void CommandHeroes(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        var profile = EnsureProfile(player!);
        var level = GetLevel(profile.Xp);

        command.ReplyToCommand($"{Config.ChatPrefix} Heroes available at level {level}:");
        foreach (var hero in Heroes)
        {
            var state = level >= hero.MinimumLevel ? "READY" : $"LEVEL {hero.MinimumLevel}";
            command.ReplyToCommand($"{Config.ChatPrefix} {hero.DisplayName} [{state}] - {hero.Description}");
        }
    }

    [ConsoleCommand("css_myheroes", "List your selected SuperHero heroes")]
    public void CommandMyHeroes(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        var profile = EnsureProfile(player!);
        var level = GetLevel(profile.Xp);
        var heroes = profile.Heroes.Count == 0 ? "none" : string.Join(", ", profile.Heroes.Select(GetHeroDisplayName));
        command.ReplyToCommand($"{Config.ChatPrefix} Selected {profile.Heroes.Count}/{GetHeroSlots(level)}: {heroes}");
    }

    [ConsoleCommand("css_selecthero", "Select a hero. Usage: !selecthero <name>")]
    [CommandHelper(minArgs: 1, usage: "<hero>")]
    public void CommandSelectHero(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        var requested = command.GetArg(1).Trim();
        var hero = FindHero(requested);
        if (hero == null)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} Unknown hero '{requested}'. Use !heroes.");
            return;
        }

        var profile = EnsureProfile(player!);
        var level = GetLevel(profile.Xp);
        if (level < hero.MinimumLevel)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} {hero.DisplayName} requires level {hero.MinimumLevel}.");
            return;
        }

        if (profile.Heroes.Contains(hero.Id, StringComparer.OrdinalIgnoreCase))
        {
            command.ReplyToCommand($"{Config.ChatPrefix} {hero.DisplayName} is already selected.");
            return;
        }

        if (profile.Heroes.Count >= GetHeroSlots(level))
        {
            command.ReplyToCommand($"{Config.ChatPrefix} No free hero slots. Drop one with !drophero <name>.");
            return;
        }

        profile.Heroes.Add(hero.Id);
        SaveProfilesSafe();
        ApplySpawnEffects(player!);
        command.ReplyToCommand($"{Config.ChatPrefix} Selected {hero.DisplayName}.");
    }

    [ConsoleCommand("css_drophero", "Drop a hero. Usage: !drophero <name>")]
    [CommandHelper(minArgs: 1, usage: "<hero>")]
    public void CommandDropHero(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        var hero = FindHero(command.GetArg(1).Trim());
        if (hero == null)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} Unknown hero. Use !myheroes.");
            return;
        }

        var profile = EnsureProfile(player!);
        var removed = profile.Heroes.RemoveAll(x => x.Equals(hero.Id, StringComparison.OrdinalIgnoreCase)) > 0;
        if (!removed)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} {hero.DisplayName} is not selected.");
            return;
        }

        _hulkActiveUntil.Remove(player!.SteamID);
        SaveProfilesSafe();
        var pawn = player.PlayerPawn.Get();
        if (pawn != null && pawn.Health > 0)
        {
            ApplySpawnEffects(player);
        }
        command.ReplyToCommand($"{Config.ChatPrefix} Dropped {hero.DisplayName}.");
    }

    [ConsoleCommand("css_power", "Activate your hero power")]
    public void CommandPower(CCSPlayerController? player, CommandInfo command)
    {
        if (!IsUsablePlayer(player)) return;
        if (!HasHero(player!, "hulk"))
        {
            command.ReplyToCommand($"{Config.ChatPrefix} No selected hero has an active MVP power. Hulk unlocks at level 5.");
            return;
        }

        var now = Server.CurrentTime;
        if (_hulkCooldownUntil.TryGetValue(player!.SteamID, out var cooldownUntil) && cooldownUntil > now)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} Hulk cooldown: {MathF.Ceiling(cooldownUntil - now)}s.");
            return;
        }

        var pawn = player.PlayerPawn.Get();
        if (pawn == null || pawn.Health <= 0) return;

        _hulkActiveUntil[player.SteamID] = now + Config.HulkPowerSeconds;
        _hulkCooldownUntil[player.SteamID] = now + Config.HulkCooldownSeconds;
        pawn.ArmorValue = Math.Max(pawn.ArmorValue, 130);
        Utilities.SetStateChanged(pawn, "CCSPlayerPawn", "m_ArmorValue");
        command.ReplyToCommand($"{Config.ChatPrefix} HULK RAGE active for {Config.HulkPowerSeconds:0}s.");
    }

    [ConsoleCommand("css_sh_reload", "Reload SuperHero MVP configuration")]
    public void CommandReload(CCSPlayerController? player, CommandInfo command)
    {
        if (player != null)
        {
            command.ReplyToCommand($"{Config.ChatPrefix} This command is server console or RCON only.");
            return;
        }

        Config.Reload();
        command.ReplyToCommand("SuperHero MVP config reloaded.");
    }

    private void AddXp(CCSPlayerController player, int amount)
    {
        if (amount <= 0) return;
        var profile = EnsureProfile(player);
        var oldLevel = GetLevel(profile.Xp);
        profile.Xp = Math.Max(0, profile.Xp + amount);
        var newLevel = GetLevel(profile.Xp);

        player.PrintToChat($"{Config.ChatPrefix} +{amount} XP. Total: {profile.Xp}.");
        if (newLevel > oldLevel)
        {
            player.PrintToChat($"{Config.ChatPrefix} LEVEL UP. You are now level {newLevel}. Hero slots: {GetHeroSlots(newLevel)}.");
            player.PrintToChat($"{Config.ChatPrefix} Use !heroes to see newly unlocked heroes.");
        }

        SaveProfilesSafe();
    }

    private PlayerProfile EnsureProfile(CCSPlayerController player)
    {
        if (!_profiles.TryGetValue(player.SteamID, out var profile))
        {
            profile = new PlayerProfile();
            _profiles[player.SteamID] = profile;
        }

        profile.Heroes ??= [];
        profile.Heroes = profile.Heroes
            .Select(x => x.Trim().ToLowerInvariant())
            .Where(x => FindHero(x) != null)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return profile;
    }

    private bool HasHero(CCSPlayerController player, string heroId)
    {
        if (!_profiles.TryGetValue(player.SteamID, out var profile)) return false;
        return profile.Heroes.Any(x => x.Equals(heroId, StringComparison.OrdinalIgnoreCase));
    }

    private int GetDesiredMaxHealth(CCSPlayerController player)
    {
        return HasHero(player, "superman") ? 150 : 100;
    }

    private int GetLevel(int xp)
    {
        var level = 0;
        for (var i = 1; i < Config.LevelThresholds.Length; i++)
        {
            if (xp < Config.LevelThresholds[i]) break;
            level = i;
        }
        return level;
    }

    private static int GetHeroSlots(int level)
    {
        if (level >= 6) return 3;
        if (level >= 3) return 2;
        return 1;
    }

    private static HeroDefinition? FindHero(string value)
    {
        return Heroes.FirstOrDefault(x =>
            x.Id.Equals(value, StringComparison.OrdinalIgnoreCase) ||
            x.DisplayName.Equals(value, StringComparison.OrdinalIgnoreCase));
    }

    private static string GetHeroDisplayName(string heroId)
    {
        return FindHero(heroId)?.DisplayName ?? heroId;
    }

    private static bool IsUsablePlayer(CCSPlayerController? player)
    {
        return player != null && player.IsValid && !player.IsBot && player.SteamID != 0;
    }

    private void LoadProfiles()
    {
        _profiles.Clear();
        if (!File.Exists(DataPath)) return;

        try
        {
            var json = File.ReadAllText(DataPath);
            var stored = JsonSerializer.Deserialize<Dictionary<string, PlayerProfile>>(json, JsonOptions) ?? [];
            foreach (var (key, profile) in stored)
            {
                if (!ulong.TryParse(key, out var steamId) || steamId == 0) continue;
                _profiles[steamId] = profile ?? new PlayerProfile();
            }
        }
        catch (Exception ex)
        {
            Logger.LogError(ex, "Failed to load SuperHero profiles from {Path}", DataPath);
        }
    }

    private void SaveProfilesSafe()
    {
        try
        {
            Directory.CreateDirectory(ModuleDirectory);
            var stored = _profiles.ToDictionary(x => x.Key.ToString(), x => x.Value);
            var tempPath = DataPath + ".tmp";
            File.WriteAllText(tempPath, JsonSerializer.Serialize(stored, JsonOptions));
            File.Move(tempPath, DataPath, true);
        }
        catch (Exception ex)
        {
            Logger.LogError(ex, "Failed to save SuperHero profiles to {Path}", DataPath);
        }
    }
}
