using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Utils;
using RetakesAllocatorCore;
using RetakesAllocatorCore.Config;

namespace RetakesAllocatorTest;

public class ConfigTests : BaseTestFixture
{
    [Test]
    public void TestDefaultWeaponsValidation()
    {
        var usableWeapons = WeaponHelpers.AllWeapons;
        usableWeapons.Remove(CsItem.Glock);
        var warnings = Configs.OverrideConfigDataForTests(
            new ConfigData()
            {
                UsableWeapons = usableWeapons,
            }
        ).Validate();
        Assert.That(warnings[0],
            Is.EqualTo(
                "Glock18 in the DefaultWeapons.Terrorist.PistolRound " +
                "config is not in the UsableWeapons list."));

        var defaults =
            new Dictionary<CsTeam, Dictionary<WeaponAllocationType, CsItem>>(Configs.GetConfigData().DefaultWeapons);
        defaults[CsTeam.Terrorist] = new Dictionary<WeaponAllocationType, CsItem>(defaults[CsTeam.Terrorist]);
        defaults[CsTeam.Terrorist].Remove(WeaponAllocationType.FullBuyPrimary);
        warnings = Configs.OverrideConfigDataForTests(
            new ConfigData()
            {
                DefaultWeapons = defaults
            }
        ).Validate();
        Assert.That(warnings[0], Is.EqualTo("Missing FullBuyPrimary in DefaultWeapons.Terrorist config."));

        defaults.Remove(CsTeam.CounterTerrorist);
        warnings = Configs.OverrideConfigDataForTests(
            new ConfigData()
            {
                DefaultWeapons = defaults
            }
        ).Validate();
        Assert.That(warnings[0], Is.EqualTo("Missing FullBuyPrimary in DefaultWeapons.Terrorist config."));
        Assert.That(warnings[1], Is.EqualTo("Missing CounterTerrorist in DefaultWeapons config."));

        defaults[CsTeam.Terrorist][WeaponAllocationType.FullBuyPrimary] = CsItem.Kevlar;
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(
                new ConfigData()
                {
                    DefaultWeapons = defaults
                }
            );
        });
        Assert.That(error?.Message,
            Is.EqualTo("Kevlar is not a valid weapon in config DefaultWeapons.Terrorist.FullBuyPrimary."));

        defaults =
            new Dictionary<CsTeam, Dictionary<WeaponAllocationType, CsItem>>(Configs.GetConfigData().DefaultWeapons);
        defaults[CsTeam.Terrorist][WeaponAllocationType.Preferred] = CsItem.AWP;
        error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(
                new ConfigData()
                {
                    DefaultWeapons = defaults
                }
            );
        });
        Assert.That(error?.Message, Is.EqualTo(
            "Preferred is not a valid default weapon allocation type for config DefaultWeapons.Terrorist."
        ));
    }

    private static RoundLoadoutStage MakeStage(int fromRound, int? toRound) => new()
    {
        FromRound = fromRound,
        ToRound = toRound,
        TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
    };

    [Test]
    public void TestRoundLoadoutSequenceRejectsGap()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    MakeStage(1, 1),
                    MakeStage(3, null),
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("gap"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsOverlap()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    MakeStage(1, 3),
                    MakeStage(2, null),
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("overlap"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsMultipleOpenEndedStages()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    MakeStage(1, null),
                    MakeStage(2, null),
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("more than one open-ended stage"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRequiresOpenEndedStageLast()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    MakeStage(1, null),
                    MakeStage(2, 3),
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("must be the last stage"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsInvalidRoundNumbers()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    MakeStage(0, null),
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain(">= 1"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsFiveSevenForTerrorist()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristSecondaryWeapons = new List<CsItem> {CsItem.FiveSeven},
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                    },
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("FiveSeven"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsTec9ForCounterTerrorist()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.Tec9},
                    },
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("Tec9"));
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsNegativeMaxPreferredWeapons()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                        MaxPreferredWeapons = -1,
                    },
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("cannot be negative"));
    }

    [TestCase(-1.0)]
    [TestCase(100.1)]
    public void TestRoundLoadoutSequenceRejectsOutOfRangePreferredWeaponChance(double chance)
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                        PreferredWeaponChance = chance,
                    },
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("must be between 0 and 100"));
    }

    [TestCase(0.0)]
    [TestCase(25.0)]
    [TestCase(100.0)]
    public void TestRoundLoadoutSequenceAcceptsInRangePreferredWeaponChance(double chance)
    {
        Assert.DoesNotThrow(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristPrimaryWeapons = new List<CsItem> {CsItem.AK47},
                        TerroristSecondaryWeapons = new List<CsItem> {CsItem.Glock},
                        CounterTerroristPrimaryWeapons = new List<CsItem> {CsItem.M4A4},
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                        PreferredWeapon = CsItem.AWP,
                        MaxPreferredWeapons = 1,
                        PreferredWeaponChance = chance,
                    },
                },
            });
        });
    }

    [Test]
    public void TestRoundLoadoutSequenceRejectsMissingBothPoolsForATeam()
    {
        var error = Assert.Catch(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
                {
                    new()
                    {
                        FromRound = 1,
                        ToRound = null,
                        TerroristSecondaryWeapons = new List<CsItem>(),
                        CounterTerroristSecondaryWeapons = new List<CsItem> {CsItem.USPS},
                    },
                },
            });
        });
        Assert.That(error, Is.Not.Null);
        Assert.That(error!.Message, Does.Contain("no weapons configured"));
    }

    [Test]
    public void TestRoundLoadoutSequenceEmptyIsBackwardCompatible()
    {
        Assert.DoesNotThrow(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>(),
            });
        });
    }

    [Test]
    public void TestRoundLoadoutSequenceValidOfficialProgressionPasses()
    {
        Assert.DoesNotThrow(() =>
        {
            Configs.OverrideConfigDataForTests(new ConfigData
            {
                RoundLoadoutSequence = new List<RoundLoadoutStage>
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
                        CounterTerroristSecondaryWeapons =
                            new List<CsItem> {CsItem.Deagle, CsItem.P250, CsItem.FiveSeven},
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
                },
            });
        });
    }
}
