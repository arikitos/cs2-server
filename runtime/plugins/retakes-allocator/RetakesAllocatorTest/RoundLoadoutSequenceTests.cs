using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Utils;
using RetakesAllocatorCore;
using RetakesAllocatorCore.Config;
using RetakesAllocatorCore.Managers;

namespace RetakesAllocatorTest;

public class RoundLoadoutSequenceTests : BaseTestFixture
{
    private record TestPlayer(ulong SteamId, CsTeam Team);

    [TearDown]
    public void ResetRandom()
    {
        RoundLoadoutAllocator.RandomIndex = n => new Random().Next(n);
        RoundLoadoutAllocator.RandomPercent = () => new Random().NextDouble() * 100;
    }

    private static List<RoundLoadoutStage> BuildOfficialSequence()
    {
        return new List<RoundLoadoutStage>
        {
            new()
            {
                FromRound = 1,
                ToRound = 1,
                TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
            },
            new()
            {
                FromRound = 2,
                ToRound = 2,
                TerroristSecondaryWeapons = new List<CsItem> {CsItem.Deagle, CsItem.P250, CsItem.Tec9},
                CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.Deagle, CsItem.P250, CsItem.FiveSeven},
            },
            new()
            {
                FromRound = 3,
                ToRound = 3,
                TerroristPrimaryWeapons = new List<CsItem> {CsItem.Mac10, CsItem.MP7},
                TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                CounterTerroristPrimaryWeapons = new List<CsItem> {CsItem.MP9, CsItem.MP7},
                CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
            },
            new()
            {
                FromRound = 4,
                ToRound = 4,
                TerroristPrimaryWeapons = new List<CsItem> {CsItem.Scout, CsItem.Galil},
                TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                CounterTerroristPrimaryWeapons = new List<CsItem> {CsItem.Scout, CsItem.Famas},
                CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
            },
            new()
            {
                FromRound = 5,
                ToRound = null,
                TerroristPrimaryWeapons = new List<CsItem> {CsItem.AK47},
                TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                CounterTerroristPrimaryWeapons = new List<CsItem> {CsItem.M4A4, CsItem.M4A1S},
                CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                PreferredWeapon = CsItem.AWP,
                MaxPreferredWeapons = 1,
            },
        };
    }

    private static void SetupOfficialSequenceConfig()
    {
        Configs.OverrideConfigDataForTests(new ConfigData
        {
            RoundTypeSelection = RoundTypeSelectionOption.LoadoutSequence,
            RoundLoadoutSequence = BuildOfficialSequence(),
        });
        RoundTypeManager.Instance.Initialize();
    }

    private static List<TestPlayer> SevenPlayers() => new()
    {
        new(1, CsTeam.Terrorist),
        new(2, CsTeam.Terrorist),
        new(3, CsTeam.Terrorist),
        new(4, CsTeam.CounterTerrorist),
        new(5, CsTeam.CounterTerrorist),
        new(6, CsTeam.CounterTerrorist),
        new(7, CsTeam.CounterTerrorist),
    };

    private static Dictionary<TestPlayer, ICollection<CsItem>> AllocateRound(List<TestPlayer> players, out RoundType roundType)
    {
        var allocations = new Dictionary<TestPlayer, ICollection<CsItem>>();
        OnRoundPostStartHelper.Handle(
            players,
            player => player?.SteamId ?? 0,
            player => player.Team,
            _ => { },
            (player, items, _) => allocations[player] = items,
            _ => false,
            out roundType
        );
        return allocations;
    }

    [Test]
    public void Round1_PistolsOnly_NoPrimary()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();

        var allocations = AllocateRound(players, out var roundType);

        Assert.That(roundType, Is.EqualTo(RoundType.Pistol));
        foreach (var (player, items) in allocations)
        {
            if (player.Team == CsTeam.Terrorist)
            {
                Assert.That(items, Does.Contain(CsItem.Glock));
            }
            else
            {
                Assert.That(items, Does.Contain(CsItem.USPS));
            }

            Assert.That(items, Has.None.EqualTo(CsItem.AK47));
            Assert.That(items, Has.None.EqualTo(CsItem.M4A1S));
            Assert.That(items, Has.None.EqualTo(CsItem.M4A4));
            Assert.That(items, Has.None.EqualTo(CsItem.AWP));
        }
    }

    [Test]
    public void Round2_RandomSecondaryOnly_FromConfiguredPool()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        AllocateRound(players, out _); // round 1

        var allocations = AllocateRound(players, out var roundType); // round 2

        Assert.That(roundType, Is.EqualTo(RoundType.Pistol));
        var tPool = new HashSet<CsItem> {CsItem.Deagle, CsItem.P250, CsItem.Tec9};
        var ctPool = new HashSet<CsItem> {CsItem.Deagle, CsItem.P250, CsItem.FiveSeven};

        foreach (var (player, items) in allocations)
        {
            var pool = player.Team == CsTeam.Terrorist ? tPool : ctPool;
            var secondaries = items.Where(pool.Contains).ToList();
            Assert.That(secondaries.Count, Is.EqualTo(1));
            Assert.That(items, Has.None.EqualTo(CsItem.AWP));
        }
    }

    [Test]
    public void Round3_SmgPrimary_TeamSpecificPools()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        AllocateRound(players, out _);
        AllocateRound(players, out _);

        var allocations = AllocateRound(players, out var roundType); // round 3

        Assert.That(roundType, Is.EqualTo(RoundType.FullBuy));
        foreach (var (player, items) in allocations)
        {
            if (player.Team == CsTeam.Terrorist)
            {
                Assert.That(items, Does.Contain(CsItem.Glock));
                Assert.That(items.Any(i => i is CsItem.Mac10 or CsItem.MP7), Is.True);
                Assert.That(items, Has.None.EqualTo(CsItem.MP9));
            }
            else
            {
                Assert.That(items, Does.Contain(CsItem.USPS));
                Assert.That(items.Any(i => i is CsItem.MP9 or CsItem.MP7), Is.True);
                Assert.That(items, Has.None.EqualTo(CsItem.Mac10));
            }
        }
    }

    [Test]
    public void Round4_MidRifles_TeamSpecificPools()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 3; i++) AllocateRound(players, out _);

        var allocations = AllocateRound(players, out _); // round 4

        foreach (var (player, items) in allocations)
        {
            if (player.Team == CsTeam.Terrorist)
            {
                Assert.That(items.Any(i => i is CsItem.Scout or CsItem.Galil), Is.True);
                Assert.That(items, Has.None.EqualTo(CsItem.Famas));
            }
            else
            {
                Assert.That(items.Any(i => i is CsItem.Scout or CsItem.Famas), Is.True);
                Assert.That(items, Has.None.EqualTo(CsItem.Galil));
            }
        }
    }

    [Test]
    public void Round5_FinalStage_ExactlyOneAwpAcrossBothTeams()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        var allocations = AllocateRound(players, out var roundType); // round 5

        Assert.That(roundType, Is.EqualTo(RoundType.FullBuy));
        var awpCount = allocations.Values.Count(items => items.Contains(CsItem.AWP));
        Assert.That(awpCount, Is.EqualTo(1));

        foreach (var (player, items) in allocations)
        {
            var hasAwp = items.Contains(CsItem.AWP);
            if (player.Team == CsTeam.Terrorist)
            {
                Assert.That(items, Does.Contain(CsItem.Glock));
                if (!hasAwp)
                {
                    Assert.That(items, Does.Contain(CsItem.AK47));
                }
            }
            else
            {
                Assert.That(items, Does.Contain(CsItem.USPS));
                if (!hasAwp)
                {
                    Assert.That(items.Any(i => i is CsItem.M4A4 or CsItem.M4A1S), Is.True);
                }
            }
        }
    }

    [Test]
    public void Round6AndLater_ReuseFinalOpenEndedStage()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _); // rounds 1-4

        for (var round = 5; round <= 14; round++)
        {
            var allocations = AllocateRound(players, out var roundType);
            Assert.That(roundType, Is.EqualTo(RoundType.FullBuy), $"Round {round} should use the final stage");
            var awpCount = allocations.Values.Count(items => items.Contains(CsItem.AWP));
            Assert.That(awpCount, Is.EqualTo(1), $"Round {round} should distribute exactly one AWP");
        }
    }

    [Test]
    public void NoAwpDistributedInRounds1Through4()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++)
        {
            var allocations = AllocateRound(players, out _);
            Assert.That(allocations.Values.Any(items => items.Contains(CsItem.AWP)), Is.False);
        }
    }

    [Test]
    public void AwpCanBeAssignedToEitherTeam()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        var sawT = false;
        var sawCt = false;
        for (var i = 0; i < 40 && !(sawT && sawCt); i++)
        {
            var allocations = AllocateRound(players, out _);
            foreach (var (player, items) in allocations)
            {
                if (!items.Contains(CsItem.AWP)) continue;
                if (player.Team == CsTeam.Terrorist) sawT = true;
                else sawCt = true;
            }
        }

        Assert.That(sawT, Is.True, "AWP should be assignable to a Terrorist across repeated rounds");
        Assert.That(sawCt, Is.True, "AWP should be assignable to a Counter-Terrorist across repeated rounds");
    }

    [Test]
    public void AwpReplacesPrimary_NeverAdditional()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        var allocations = AllocateRound(players, out _);
        foreach (var (player, items) in allocations)
        {
            if (!items.Contains(CsItem.AWP)) continue;
            var otherPrimary = player.Team == CsTeam.Terrorist
                ? items.Contains(CsItem.AK47)
                : items.Any(i => i is CsItem.M4A4 or CsItem.M4A1S);
            Assert.That(otherPrimary, Is.False, "AWP recipient must not also receive the team rifle");
        }
    }

    [Test]
    public void RepeatedAllocations_NeverProduceMoreThanOneAwpPerRound()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        for (var i = 0; i < 25; i++)
        {
            var allocations = AllocateRound(players, out _);
            var awpCount = allocations.Values.Count(items => items.Contains(CsItem.AWP));
            Assert.That(awpCount, Is.LessThanOrEqualTo(1));
        }
    }

    private static void SetupFinalStageAwpChance(double chance)
    {
        var sequence = BuildOfficialSequence();
        sequence[^1].PreferredWeaponChance = chance;
        Configs.OverrideConfigDataForTests(new ConfigData
        {
            RoundTypeSelection = RoundTypeSelectionOption.LoadoutSequence,
            RoundLoadoutSequence = sequence,
        });
        RoundTypeManager.Instance.Initialize();
    }

    [Test]
    public void PreferredWeaponChance_DefaultsTo100_AndAlwaysAllocates()
    {
        SetupOfficialSequenceConfig();
        Assert.That(BuildOfficialSequence()[^1].PreferredWeaponChance, Is.EqualTo(100));

        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        // A roll that would fail any chance below 100 must still allocate at the default.
        RoundLoadoutAllocator.RandomPercent = () => 99.999;
        for (var i = 0; i < 10; i++)
        {
            var allocations = AllocateRound(players, out _);
            Assert.That(allocations.Values.Count(items => items.Contains(CsItem.AWP)), Is.EqualTo(1));
        }
    }

    [Test]
    public void PreferredWeaponChance_RollBelowThreshold_AllocatesAwp()
    {
        SetupFinalStageAwpChance(25);
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        RoundLoadoutAllocator.RandomPercent = () => 24.999;
        var allocations = AllocateRound(players, out _);

        Assert.That(allocations.Values.Count(items => items.Contains(CsItem.AWP)), Is.EqualTo(1));
    }

    [Test]
    public void PreferredWeaponChance_RollAtOrAboveThreshold_AllocatesNoAwp()
    {
        SetupFinalStageAwpChance(25);
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        RoundLoadoutAllocator.RandomPercent = () => 25;
        var allocations = AllocateRound(players, out _);

        Assert.That(allocations.Values.Any(items => items.Contains(CsItem.AWP)), Is.False);
    }

    [Test]
    public void PreferredWeaponChance_FailedRoll_StillGivesEveryPlayerTheirTeamRifle()
    {
        SetupFinalStageAwpChance(25);
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        RoundLoadoutAllocator.RandomPercent = () => 99;
        var allocations = AllocateRound(players, out var roundType);

        Assert.That(roundType, Is.EqualTo(RoundType.FullBuy));
        foreach (var (player, items) in allocations)
        {
            if (player.Team == CsTeam.Terrorist)
            {
                Assert.That(items, Does.Contain(CsItem.Glock));
                Assert.That(items, Does.Contain(CsItem.AK47));
            }
            else
            {
                Assert.That(items, Does.Contain(CsItem.USPS));
                Assert.That(items.Any(i => i is CsItem.M4A4 or CsItem.M4A1S), Is.True);
            }
        }
    }

    [Test]
    public void PreferredWeaponChance_Zero_NeverAllocatesAwp()
    {
        SetupFinalStageAwpChance(0);
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        for (var i = 0; i < 25; i++)
        {
            var allocations = AllocateRound(players, out _);
            Assert.That(allocations.Values.Any(items => items.Contains(CsItem.AWP)), Is.False);
        }
    }

    [Test]
    public void PreferredWeaponChance_25_AllocatesAwpInRoughlyAQuarterOfRounds()
    {
        SetupFinalStageAwpChance(25);
        var players = SevenPlayers();
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        // Deterministic sweep across the roll space instead of sampling real randomness,
        // so the assertion is exact rather than flaky.
        var rounds = 0;
        var awpRounds = 0;
        for (var percent = 0; percent < 100; percent++)
        {
            var roll = percent;
            RoundLoadoutAllocator.RandomPercent = () => roll;
            var allocations = AllocateRound(players, out _);
            rounds++;
            if (allocations.Values.Any(items => items.Contains(CsItem.AWP))) awpRounds++;
        }

        Assert.That(rounds, Is.EqualTo(100));
        Assert.That(awpRounds, Is.EqualTo(25));
    }

    [Test]
    public void ZeroPlayers_DoesNotThrow()
    {
        SetupOfficialSequenceConfig();
        Assert.DoesNotThrow(() =>
        {
            OnRoundPostStartHelper.Handle(
                new List<TestPlayer>(),
                player => player?.SteamId ?? 0,
                player => player.Team,
                _ => { },
                (_, _, _) => { },
                _ => false,
                out _
            );
        });
    }

    [Test]
    public void OnePlayer_DoesNotThrow_AndMayReceiveAwpInFinalStage()
    {
        SetupOfficialSequenceConfig();
        var players = new List<TestPlayer> {new(1, CsTeam.Terrorist)};
        for (var i = 0; i < 4; i++) AllocateRound(players, out _);

        Assert.DoesNotThrow(() => AllocateRound(players, out _));
    }

    [Test]
    public void SequenceResetsToRound1_OnInitialize()
    {
        SetupOfficialSequenceConfig();
        var players = SevenPlayers();
        AllocateRound(players, out _);
        AllocateRound(players, out _);

        RoundTypeManager.Instance.Initialize();

        var allocations = AllocateRound(players, out var roundType);
        Assert.That(roundType, Is.EqualTo(RoundType.Pistol));
        foreach (var (player, items) in allocations)
        {
            Assert.That(items, Does.Contain(player.Team == CsTeam.Terrorist ? CsItem.Glock : CsItem.USPS));
        }
    }

    [Test]
    public void BackwardCompatibility_EmptySequence_FallsBackToLegacyBehavior()
    {
        Configs.OverrideConfigDataForTests(new ConfigData
        {
            RoundTypeSelection = RoundTypeSelectionOption.LoadoutSequence,
            RoundLoadoutSequence = new List<RoundLoadoutStage>(),
        });
        RoundTypeManager.Instance.Initialize();

        Assert.That(RoundTypeManager.Instance.IsLoadoutSequenceActive(), Is.False);

        Assert.DoesNotThrow(() =>
        {
            OnRoundPostStartHelper.Handle(
                SevenPlayers(),
                player => player?.SteamId ?? 0,
                player => player.Team,
                _ => { },
                (_, _, _) => { },
                _ => false,
                out _
            );
        });
    }

    [Test]
    public void ForcedRandomIndex_AlwaysSelectsFirstConfiguredWeapon()
    {
        SetupOfficialSequenceConfig();
        RoundLoadoutAllocator.RandomIndex = _ => 0;

        var players = SevenPlayers();
        AllocateRound(players, out _);
        var allocations = AllocateRound(players, out _); // round 2

        // Round 2 pools are [Deagle, P250, Tec9] for T and [Deagle, P250, FiveSeven] for CT;
        // index 0 for both means every player receives Deagle.
        foreach (var (_, items) in allocations)
        {
            Assert.That(items, Does.Contain(CsItem.Deagle));
        }
    }
}
