using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Utils;

namespace RetakesAllocatorCore.Config;

public record RoundLoadoutStage
{
    public int FromRound { get; set; }

    // null means the stage continues until the match ends. Must be the last stage.
    public int? ToRound { get; set; }

    public List<CsItem> TerroristPrimaryWeapons { get; set; } = new();
    public List<CsItem> TerroristSecondaryWeapons { get; set; } = new();
    public List<CsItem> CounterTerroristPrimaryWeapons { get; set; } = new();
    public List<CsItem> CounterTerroristSecondaryWeapons { get; set; } = new();

    public CsItem? PreferredWeapon { get; set; }
    public int MaxPreferredWeapons { get; set; }

    public bool ContainsRound(int roundNumber)
    {
        return roundNumber >= FromRound && (ToRound is null || roundNumber <= ToRound);
    }

    public List<CsItem> GetPrimaryWeapons(CsTeam team) =>
        team == CsTeam.Terrorist ? TerroristPrimaryWeapons : CounterTerroristPrimaryWeapons;

    public List<CsItem> GetSecondaryWeapons(CsTeam team) =>
        team == CsTeam.Terrorist ? TerroristSecondaryWeapons : CounterTerroristSecondaryWeapons;
}
