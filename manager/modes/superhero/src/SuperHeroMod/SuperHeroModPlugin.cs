using System.Text.Json;
using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Core.Attributes;
using CounterStrikeSharp.API.Core.Attributes.Registration;
using CounterStrikeSharp.API.Modules.Admin;
using CounterStrikeSharp.API.Modules.Commands;
using CounterStrikeSharp.API.Modules.Extensions;
using CounterStrikeSharp.API.Modules.Memory;
using CounterStrikeSharp.API.Modules.Memory.DynamicFunctions;
using Microsoft.Extensions.Logging;
using SuperHeroMod.Configuration;
using SuperHeroMod.Core;
using SuperHeroMod.Services;
using SuperHeroMod.Utilities;

namespace SuperHeroMod;

[MinimumApiVersion(80)]
public sealed class SuperHeroModPlugin : BasePlugin, IPluginConfig<SuperHeroConfig>
{
    public override string ModuleName => "SuperHero Mod";
    public override string ModuleVersion => typeof(SuperHeroModPlugin).Assembly.GetName().Version?.ToString(3) ?? "0.1.0";
    public override string ModuleAuthor => "SuperHero Mod Contributors";
    public override string ModuleDescription => "Classic CS 1.6-style superhero mode for CS2.";

    public SuperHeroConfig Config { get; set; } = new();
    private readonly PlayerStateService _states = new();
    private readonly Random _random = new();
    private HeroCatalog _catalog = null!;
    private HeroEffectService _effects = null!;
    private AbilityService _abilities = null!;

    public void OnConfigParsed(SuperHeroConfig config) { ValidateConfig(config); Config = config; }

    private static void ValidateConfig(SuperHeroConfig c)
    {
        if (c.GlobalMultiplierMax is < 1f or > 2f) throw new InvalidOperationException("GlobalMultiplierMax must be 1.0..2.0.");
        if (c.MovementMultiplierMin is <= 0f or > 1f) throw new InvalidOperationException("MovementMultiplierMin must be >0 and <=1.");
        if (c.GravityMultiplierMin is <= 0f or > 1f) throw new InvalidOperationException("GravityMultiplierMin must be >0 and <=1.");
        if (c.HealthMultiplierMin is <= 0f or > 1f) throw new InvalidOperationException("HealthMultiplierMin must be >0 and <=1.");
        if (c.MaxEquippedHeroes is < 1 or > 5) throw new InvalidOperationException("MaxEquippedHeroes must be 1..5.");
        if (string.IsNullOrWhiteSpace(c.HeroesFile)) throw new InvalidOperationException("HeroesFile is required.");
    }

    public override void Load(bool hotReload)
    {
        ReloadRuntime();
        RegisterListener<Listeners.OnTick>(OnTick);
        VirtualFunctions.CBaseEntity_TakeDamageOldFunc.Hook(OnTakeDamage, HookMode.Pre);
        if (hotReload && Config.Enabled)
            foreach (var p in CounterStrikeSharp.API.Utilities.GetPlayers().Where(PlayerUtil.IsAlivePlayer))
            {
                EnsureAuto(p);
                Server.NextFrame(() => { if (PlayerUtil.IsAlivePlayer(p)) _effects.CaptureAndApplyOnSpawn(p); });
            }
        Logger.LogInformation("SuperHero Mod loaded with {Count} heroes.", _catalog.All.Count);
    }

    public override void Unload(bool hotReload)
    {
        try { RemoveListener<Listeners.OnTick>(OnTick); } catch { }
        try { VirtualFunctions.CBaseEntity_TakeDamageOldFunc.Unhook(OnTakeDamage, HookMode.Pre); } catch { }
        foreach (var p in CounterStrikeSharp.API.Utilities.GetPlayers().Where(PlayerUtil.IsAlivePlayer)) _effects.RestoreBaseline(p);
        _states.Clear();
    }

    private void ReloadRuntime()
    {
        var dir = Path.GetDirectoryName(Config.GetConfigPath()) ?? throw new InvalidOperationException("Cannot resolve config directory.");
        var root = Path.GetFullPath(dir);
        var heroesPath = Path.GetFullPath(Path.Combine(root, Config.HeroesFile));
        if (!heroesPath.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("HeroesFile must stay inside plugin config directory.");
        _catalog = HeroCatalog.Load(heroesPath, Config);
        _effects = new HeroEffectService(Config, _states, _catalog);
        _abilities = new AbilityService(Config, _states, _effects);
    }

    [GameEventHandler]
    public HookResult OnSpawn(EventPlayerSpawned e, GameEventInfo info)
    {
        if (!Config.Enabled || e.Userid is not { IsValid: true } p) return HookResult.Continue;
        PromotePending(p); EnsureAuto(p);
        Server.NextFrame(() =>
        {
            if (!PlayerUtil.IsAlivePlayer(p)) return;
            _effects.CaptureAndApplyOnSpawn(p);
            if (Config.ShowHeroOnSpawn && _states.TryGet(p.Index, out var state))
                p.PrintToChat($"{Config.ChatPrefix} Hero: {string.Join(", ", state.EquippedHeroIds.Select(NameFor))}. Use !power.");
        });
        return HookResult.Continue;
    }

    [GameEventHandler]
    public HookResult OnDisconnect(EventPlayerDisconnect e, GameEventInfo info)
    {
        if (e.Userid != null) _states.Remove(e.Userid.Index);
        return HookResult.Continue;
    }

    [GameEventHandler]
    public HookResult OnRoundStart(EventRoundStart e, GameEventInfo info)
    {
        if (!Config.Enabled) return HookResult.Continue;
        foreach (var p in CounterStrikeSharp.API.Utilities.GetPlayers())
            if (_states.TryGet(p.Index, out var state))
            {
                if (state.NoclipActive && PlayerUtil.IsAlivePlayer(p)) _effects.StopNoclip(p, state);
                state.NextPowerUseUtcByHero.Clear(); state.ResetTemporaryEffects();
            }
        return HookResult.Continue;
    }

    [GameEventHandler]
    public HookResult OnJump(EventPlayerJump e, GameEventInfo info)
    {
        var p = e.Userid;
        if (!Config.Enabled || !PlayerUtil.IsAlivePlayer(p) || !_states.TryGet(p!.Index, out var state)) return HookResult.Continue;
        var pawn = p.PlayerPawn.Value!; var jump = _effects.Aggregate(state).JumpMultiplier;
        pawn.AbsVelocity.Z = Math.Clamp(pawn.AbsVelocity.Z * jump, -GameplaySafety.MaxVerticalVelocity, GameplaySafety.MaxVerticalVelocity);
        return HookResult.Continue;
    }

    [ConsoleCommand("css_heroes", "Lists available heroes")]
    public void Heroes(CCSPlayerController? p, CommandInfo c)
    {
        var heroes = _catalog.All.Where(x => x.Enabled).OrderBy(x => x.Name).ToArray();
        int page = c.ArgCount >= 2 && int.TryParse(c.GetArg(1), out var parsed) ? Math.Max(1, parsed) : 1;
        const int size = 8; int pages = Math.Max(1, (int)Math.Ceiling(heroes.Length / (double)size)); page = Math.Min(page, pages);
        c.ReplyToCommand($"{Config.ChatPrefix} Heroes {page}/{pages}");
        foreach (var h in heroes.Skip((page - 1) * size).Take(size)) c.ReplyToCommand($"{h.Id} - {h.Name}: {h.Description}");
    }

    [ConsoleCommand("css_hero", "Select hero")]
    [CommandHelper(minArgs: 1, usage: "<hero id>", whoCanExecute: CommandUsage.CLIENT_ONLY)]
    public void Hero(CCSPlayerController? p, CommandInfo c)
    {
        if (p == null || !p.IsValid || !Config.Enabled) return;
        var hero = _catalog.FindByIdOrName(c.GetArg(1));
        if (hero == null || !hero.Enabled) { c.ReplyToCommand($"{Config.ChatPrefix} Unknown hero. Use !heroes."); return; }
        var state = _states.Get(p.Index);
        if (PlayerUtil.IsAlivePlayer(p) && !Config.AllowHeroChangeWhileAlive)
        {
            state.PendingHeroIds.Clear(); state.PendingHeroIds.Add(hero.Id);
            c.ReplyToCommand($"{Config.ChatPrefix} {hero.Name} selected for next spawn."); return;
        }
        if (PlayerUtil.IsAlivePlayer(p)) _effects.RestoreBaseline(p);
        state.EquippedHeroIds.Clear(); state.EquippedHeroIds.Add(hero.Id); state.PendingHeroIds.Clear(); state.NextPowerUseUtcByHero.Clear();
        if (PlayerUtil.IsAlivePlayer(p)) _effects.CaptureAndApplyOnSpawn(p);
        c.ReplyToCommand($"{Config.ChatPrefix} {hero.Name} selected.");
    }

    [ConsoleCommand("css_myhero", "Shows equipped hero")]
    public void MyHero(CCSPlayerController? p, CommandInfo c)
    {
        if (p == null || !p.IsValid) return;
        var state = _states.Get(p.Index);
        if (state.EquippedHeroIds.Count == 0) { c.ReplyToCommand($"{Config.ChatPrefix} No hero selected."); return; }
        foreach (var id in state.EquippedHeroIds)
            if (_catalog.TryGet(id, out var h)) c.ReplyToCommand($"{Config.ChatPrefix} {h.Name}: HP {Pct(h.Stats.HealthMultiplier)}, speed {Pct(h.Stats.MovementSpeedMultiplier)}, gravity {Pct(h.Stats.GravityMultiplier)}, damage dealt {Pct(h.Stats.OutgoingDamageMultiplier)}, damage received {Pct(h.Stats.IncomingDamageMultiplier)}.");
    }

    [ConsoleCommand("css_power", "Uses hero power")]
    public void Power(CCSPlayerController? p, CommandInfo c)
    {
        if (p == null || !p.IsValid || !Config.Enabled) return;
        var state = _states.Get(p.Index);
        if (state.EquippedHeroIds.Count == 0 || !_catalog.TryGet(state.EquippedHeroIds[0], out var h)) { c.ReplyToCommand($"{Config.ChatPrefix} No hero selected."); return; }
        c.ReplyToCommand($"{Config.ChatPrefix} {h.Name}: {_abilities.Use(p, h)}");
    }

    [ConsoleCommand("css_drop", "Drops hero")]
    public void Drop(CCSPlayerController? p, CommandInfo c)
    {
        if (p == null || !p.IsValid) return;
        var state = _states.Get(p.Index); if (PlayerUtil.IsAlivePlayer(p)) _effects.RestoreBaseline(p);
        state.EquippedHeroIds.Clear(); state.PendingHeroIds.Clear(); state.NextPowerUseUtcByHero.Clear();
        c.ReplyToCommand($"{Config.ChatPrefix} Hero removed.");
    }

    [ConsoleCommand("css_shreload", "Reloads SuperHero configuration")]
    [RequiresPermissions("@css/root")]
    public void Reload(CCSPlayerController? p, CommandInfo c)
    {
        var alive = CounterStrikeSharp.API.Utilities.GetPlayers().Where(PlayerUtil.IsAlivePlayer).ToArray();
        var previousConfig = JsonSerializer.Deserialize<SuperHeroConfig>(JsonSerializer.Serialize(Config)) ?? new();
        var previousCatalog = _catalog;
        try
        {
            foreach (var x in alive) _effects.RestoreBaseline(x);
            Config.Reload(); ValidateConfig(Config); ReloadRuntime();
            if (Config.Enabled) foreach (var x in alive.Where(PlayerUtil.IsAlivePlayer)) _effects.CaptureAndApplyOnSpawn(x);
            c.ReplyToCommand($"{Config.ChatPrefix} Reloaded {_catalog.All.Count} heroes.");
        }
        catch (Exception ex)
        {
            Config = previousConfig; _catalog = previousCatalog;
            _effects = new HeroEffectService(Config, _states, _catalog); _abilities = new AbilityService(Config, _states, _effects);
            if (Config.Enabled) foreach (var x in alive.Where(PlayerUtil.IsAlivePlayer)) _effects.CaptureAndApplyOnSpawn(x);
            Logger.LogError(ex, "SuperHero reload failed; previous runtime restored.");
            c.ReplyToCommand($"{Config.ChatPrefix} Reload failed: {ex.Message}");
        }
    }

    private void OnTick()
    {
        if (!Config.Enabled || Server.TickCount % 4 != 0) return;
        var now = DateTime.UtcNow;
        foreach (var p in CounterStrikeSharp.API.Utilities.GetPlayers()) _effects.TickPlayer(p, now);
    }

    private HookResult OnTakeDamage(DynamicHook hook)
    {
        if (!Config.Enabled) return HookResult.Continue;
        var victimEntity = hook.GetParam<CEntityInstance>(0); var info = hook.GetParam<CTakeDamageInfo>(1);
        if (victimEntity == null || !victimEntity.IsValid || info == null) return HookResult.Continue;
        var victimPawn = victimEntity.As<CCSPlayerPawn>();
        if (victimPawn == null || !victimPawn.IsValid || victimPawn.DesignerName != "player") return HookResult.Continue;
        float multiplier = 1f;
        var victimController = victimPawn.Controller?.Value;
        if (victimController is { IsValid: true })
        {
            var victim = victimController.As<CCSPlayerController>();
            if (victim != null && _states.TryGet(victim.Index, out var vs)) multiplier *= _effects.Aggregate(vs).IncomingDamageMultiplier;
        }
        var attackerEntity = info.Attacker?.Value;
        if (attackerEntity is { IsValid: true })
        {
            var attackerPawn = new CCSPlayerPawn(attackerEntity.Handle);
            var controller = attackerPawn.Controller?.Value;
            if (attackerPawn.IsValid && attackerPawn.DesignerName == "player" && controller is { IsValid: true })
            {
                var attacker = controller.As<CCSPlayerController>();
                if (attacker != null && _states.TryGet(attacker.Index, out var state))
                {
                    var stats = _effects.Aggregate(state);
                    multiplier *= stats.OutgoingDamageMultiplier * state.TemporaryOutgoingDamageMultiplier;
                    if (IsMelee(info)) multiplier *= stats.MeleeDamageMultiplier;
                }
            }
        }
        info.Damage = Math.Max(0f, info.Damage * Math.Clamp(multiplier, 0f, Config.GlobalMultiplierMax));
        return HookResult.Continue;
    }

    private static bool IsMelee(CTakeDamageInfo info)
    {
        var ability = info.Ability?.Value; if (ability == null || !ability.IsValid) return false;
        var name = ability.DesignerName ?? "";
        return name.Contains("knife", StringComparison.OrdinalIgnoreCase) || name.Contains("bayonet", StringComparison.OrdinalIgnoreCase);
    }

    private void EnsureAuto(CCSPlayerController p)
    {
        var state = _states.Get(p.Index);
        if (state.EquippedHeroIds.Count > 0 || state.PendingHeroIds.Count > 0 || !Config.AutoAssignRandomHero) return;
        var enabled = _catalog.All.Where(h => h.Enabled).ToArray(); if (enabled.Length > 0) state.EquippedHeroIds.Add(enabled[_random.Next(enabled.Length)].Id);
    }

    private void PromotePending(CCSPlayerController p)
    {
        var state = _states.Get(p.Index); if (state.PendingHeroIds.Count == 0) return;
        state.EquippedHeroIds.Clear(); state.EquippedHeroIds.AddRange(state.PendingHeroIds.Take(Config.MaxEquippedHeroes)); state.PendingHeroIds.Clear(); state.NextPowerUseUtcByHero.Clear();
    }

    private string NameFor(string id) => _catalog.TryGet(id, out var h) ? h.Name : id;
    private static string Pct(float value) => $"{Math.Round(value * 100)}%";
}
