using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Commands;

namespace PanelBridge;

/// <summary>
/// Minimal, mode-agnostic bridge for the CS2 Manager panel. Its only job is to
/// expose connected players together with their SteamID64 — data the built-in
/// `status` command does not include on this CS2 build. Loaded globally for every
/// mode; it registers no gameplay behaviour and touches no match state.
/// </summary>
public sealed class PanelBridgePlugin : BasePlugin
{
    public override string ModuleName => "CS2 Manager Panel Bridge";
    public override string ModuleVersion => "1.0.0";
    public override string ModuleAuthor => "CS2 Manager";
    public override string ModuleDescription =>
        "Exposes connected players with SteamID64 for the panel (read-only).";

    public override void Load(bool hotReload)
    {
        // Registered here (rather than via attribute) so it works regardless of
        // the CounterStrikeSharp attribute namespace across versions.
        AddCommand("css_panel_players",
            "List connected players with SteamID64 (panel use)", OnPanelPlayers);
        Console.WriteLine("[PanelBridge] Loaded.");
    }

    // Callable over RCON as `css_panel_players`. Output is line-delimited and
    // parsed by the panel. Name is placed last because it may contain spaces.
    public void OnPanelPlayers(CCSPlayerController? player, CommandInfo info)
    {
        info.ReplyToCommand("PANELPLAYERS_BEGIN");
        foreach (var p in Utilities.GetPlayers())
        {
            if (p is null || !p.IsValid)
            {
                continue;
            }

            int userId = p.UserId ?? -1;
            ulong steam64 = p.SteamID; // 0 for bots
            int team = p.TeamNum;
            uint ping = p.Ping;
            int isBot = p.IsBot ? 1 : 0;
            string name = (p.PlayerName ?? string.Empty).Replace('|', '/').Replace('\n', ' ');

            // PP|userid|steamid64|team|ping|isbot|name
            info.ReplyToCommand($"PP|{userId}|{steam64}|{team}|{ping}|{isBot}|{name}");
        }
        info.ReplyToCommand("PANELPLAYERS_END");
    }
}
