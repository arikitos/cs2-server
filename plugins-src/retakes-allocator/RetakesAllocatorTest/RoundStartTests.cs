using CounterStrikeSharp.API.Modules.Utils;
using RetakesAllocatorCore;

namespace RetakesAllocatorTest;

public class RoundStartTests : BaseTestFixture
{
    private record TestPlayer(ulong SteamId, CsTeam Team);

    [Test]
    public void TestRoundStartCanRunInCore()
    {
        OnRoundPostStartHelper.Handle(
            new List<int>(),
            i => 1,
            x => CsTeam.None,
            x => {},
            (x, y, z) => {},
            x => false,
            out _
        );
    }

    [Test]
    public void AutomaticPreferredWeaponSelectsOnePlayerAcrossBothTeams()
    {
        Configs.OverrideConfigDataForTests(new ConfigData
        {
            AllowedWeaponSelectionTypes = new List<WeaponSelectionType> {WeaponSelectionType.Default},
            EnableAutomaticPreferredWeapon = true,
            AutomaticPreferredWeapon = CounterStrikeSharp.API.Modules.Entities.Constants.CsItem.AWP,
            MaxAutomaticPreferredWeaponsPerRound = 1,
            MinPlayersForAutomaticPreferredWeapon = 5,
            ChanceForPreferredWeapon = 100,
            RoundTypeSelection = RoundTypeSelectionOption.ManualOrdering,
            RoundTypeManualOrdering = new List<RoundTypeManualOrderingItem>
            {
                new(RoundType.FullBuy, 1),
            },
        });
        RetakesAllocatorCore.Managers.RoundTypeManager.Instance.Initialize();

        var players = new List<TestPlayer>
        {
            new(1, CsTeam.Terrorist),
            new(2, CsTeam.Terrorist),
            new(3, CsTeam.Terrorist),
            new(4, CsTeam.CounterTerrorist),
            new(5, CsTeam.CounterTerrorist),
            new(6, CsTeam.CounterTerrorist),
            new(7, CsTeam.CounterTerrorist),
        };
        var allocations = new Dictionary<TestPlayer, ICollection<CounterStrikeSharp.API.Modules.Entities.Constants.CsItem>>();

        OnRoundPostStartHelper.Handle(
            players,
            player => player?.SteamId ?? 0,
            player => player.Team,
            _ => { },
            (player, items, _) => allocations[player] = items,
            _ => false,
            out var roundType
        );

        Assert.That(roundType, Is.EqualTo(RoundType.FullBuy));
        Assert.That(allocations.Values.Count(items =>
            items.Contains(CounterStrikeSharp.API.Modules.Entities.Constants.CsItem.AWP)), Is.EqualTo(1));
    }
}
