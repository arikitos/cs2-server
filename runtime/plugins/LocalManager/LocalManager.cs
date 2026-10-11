using System.Text.Json;
using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Commands;
using CounterStrikeSharp.API.Modules.Entities;
using CounterStrikeSharp.API.Modules.Timers;
using CounterStrikeSharp.API.ValveConstants.Protobuf;
using Microsoft.Extensions.Logging;

namespace LocalManager;

public sealed class SeenUser
{
    public string name { get; set; } = "";
    public long first_seen { get; set; }
    public long last_seen { get; set; }
    public int visits { get; set; }
}

public sealed class LocalManager : BasePlugin
{
    public override string ModuleName => "CS2 Local Manager";
    public override string ModuleVersion => "2.0.0";
    public override string ModuleAuthor => "arikitos";
    private const string Telemetry = "/telemetry";
    private readonly Dictionary<int, string> authorized = new();
    private Dictionary<string, SeenUser> seen = new();
    private HashSet<string> bans = new();
    private string policyText = "";
    private readonly string instance = Guid.NewGuid().ToString();

    public override void Load(bool hotReload)
    {
        Directory.CreateDirectory(Telemetry);
        try
        {
            if (File.Exists(Telemetry + "/users-seen.json"))
                seen = JsonSerializer.Deserialize<Dictionary<string, SeenUser>>(File.ReadAllText(Telemetry + "/users-seen.json")) ?? new();
        }
        catch (Exception error) { Logger.LogError(error, "Could not load persistent player history"); }
        RegisterListener<Listeners.OnClientAuthorized>((slot, steamId) => Register(slot, steamId.SteamId64.ToString()));
        RegisterListener<Listeners.OnClientDisconnect>(slot => { authorized.Remove(slot); });
        AddCommand("css_local_reload", "Reload managed bans/admins (server only)", (player, command) =>
        {
            if (player != null) return;
            try { ReloadPolicy(true); command.ReplyToCommand("CS2LOCAL_OK"); }
            catch (Exception error) { command.ReplyToCommand("CS2LOCAL_ERROR " + error.Message); }
        });
        AddCommand("css_local_kick", "Kick an authenticated SteamID (server only)", (player, command) =>
        {
            if (player != null || command.ArgCount != 2) return;
            var target = Utilities.GetPlayers().FirstOrDefault(p => p.IsValid && !p.IsBot && p.AuthorizedSteamID?.SteamId64.ToString() == command.GetArg(1));
            if (target == null) { command.ReplyToCommand("CS2LOCAL_NOT_FOUND"); return; }
            target.Disconnect(NetworkDisconnectionReason.NETWORK_DISCONNECT_KICKED);
            command.ReplyToCommand("CS2LOCAL_OK");
        });
        ReloadPolicy(true);
        AddTimer(1.0f, Tick, TimerFlags.REPEAT);
        Tick();
    }

    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    private static void Write(string filename, object data)
    {
        var temporary = filename + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(data));
        File.Move(temporary, filename, true);
    }

    private void Register(int slot, string identity)
    {
        if (identity == "0") return;
        var player = Utilities.GetPlayerFromSlot(slot);
        if (player is { IsValid: true } && bans.Contains(identity))
            player.Disconnect(NetworkDisconnectionReason.NETWORK_DISCONNECT_BANADDED);
        if (authorized.GetValueOrDefault(slot) == identity) return;
        authorized[slot] = identity;
        var name = player is { IsValid: true } ? player.PlayerName : identity;
        if (!seen.TryGetValue(identity, out var entry))
            seen[identity] = entry = new SeenUser { first_seen = Now() };
        entry.name = name;
        entry.last_seen = Now();
        entry.visits++;
        Write(Telemetry + "/users-seen.json", seen);
    }

    private void ReloadPolicy(bool force = false)
    {
        var text = File.ReadAllText("/control/policy.json");
        if (!force && text == policyText) return;
        using var policy = JsonDocument.Parse(text);
        bans = policy.RootElement.GetProperty("bans").EnumerateArray().Select(value => value.GetString()!).ToHashSet();
        policyText = text;
        Server.ExecuteCommand("css_admins_reload");
        foreach (var player in Utilities.GetPlayers().Where(p => p.IsValid && !p.IsBot))
            if (player.AuthorizedSteamID is { } steam && bans.Contains(steam.SteamId64.ToString()))
                player.Disconnect(NetworkDisconnectionReason.NETWORK_DISCONNECT_BANADDED);
    }

    private void Tick()
    {
        try
        {
            ReloadPolicy();
            var players = new List<object>();
            foreach (var player in Utilities.GetPlayers().Where(p => p.IsValid))
            {
                string? identity = null;
                if (!player.IsBot && player.AuthorizedSteamID is { } steam)
                {
                    identity = steam.SteamId64.ToString();
                    Register(player.Slot, identity);
                    seen[identity].name = player.PlayerName;
                    seen[identity].last_seen = Now();
                }
                players.Add(new { steamid = identity, name = player.PlayerName, bot = player.IsBot,
                                  team = (int)player.TeamNum, userid = player.UserId, ping = player.Ping });
            }
            Write(Telemetry + "/live.json", new { updated_at = Now(), instance, players });
            // Persist activity even when the web panel is stopped.
            if (Now() % 5 == 0) Write(Telemetry + "/users-seen.json", seen);
        }
        catch (Exception error) { Logger.LogError(error, "CS2 Local management synchronization failed"); }
    }
}
