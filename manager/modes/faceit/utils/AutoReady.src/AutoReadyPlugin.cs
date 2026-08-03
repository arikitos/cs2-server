using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Timers;

namespace AutoReady;

public sealed class AutoReadyPlugin : BasePlugin
{
    public override string ModuleName => "MatchZy Auto Ready";
    public override string ModuleVersion => "1.0.0";
    public override string ModuleAuthor => "Arik";
    public override string ModuleDescription =>
        "Automatically marks human players ready after they join T or CT.";

    private readonly HashSet<ulong> _readyPlayers = new();

    public override void Load(bool hotReload)
    {
        RegisterListener<Listeners.OnClientPutInServer>(
            playerSlot => ScheduleAutoReady(playerSlot, 30)
        );

        RegisterListener<Listeners.OnMapStart>(_ =>
        {
            _readyPlayers.Clear();

            AddTimer(5.0f, () =>
            {
                foreach (var player in Utilities.GetPlayers())
                {
                    if (player.IsValid && !player.IsBot)
                    {
                        ScheduleAutoReady(player.Slot, 30);
                    }
                }
            }, TimerFlags.STOP_ON_MAPCHANGE);
        });

        Console.WriteLine("[AutoReady] Plugin loaded.");
    }

    private void ScheduleAutoReady(int playerSlot, int attemptsLeft)
    {
        AddTimer(
            2.0f,
            () => TryAutoReady(playerSlot, attemptsLeft),
            TimerFlags.STOP_ON_MAPCHANGE
        );
    }

    private void TryAutoReady(int playerSlot, int attemptsLeft)
    {
        var player = Utilities.GetPlayerFromSlot(playerSlot);

        if (player is null || !player.IsValid || player.IsBot)
        {
            return;
        }

        // Team 2 = Terrorist, Team 3 = Counter-Terrorist.
        if (player.TeamNum is 2 or 3)
        {
            var playerKey = player.SteamID != 0
                ? player.SteamID
                : (ulong)(playerSlot + 1);

            if (_readyPlayers.Add(playerKey))
            {
                player.ExecuteClientCommandFromServer("css_ready");

                Console.WriteLine(
                    $"[AutoReady] Marked {player.PlayerName} as ready."
                );
            }

            return;
        }

        // Retry for approximately one minute while the player selects a team.
        if (attemptsLeft > 1)
        {
            ScheduleAutoReady(playerSlot, attemptsLeft - 1);
        }
    }
}
