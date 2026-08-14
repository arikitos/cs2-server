using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Utils;
using RetakesAllocatorCore.Config;

namespace RetakesAllocatorCore;

public static class RoundLoadoutAllocator
{
    // Injectable so tests can force deterministic selections. Production uses unbiased random selection.
    public static Func<int, int> RandomIndex = n => new Random().Next(n);

    public static List<CsItem> GetWeaponsForPlayer(RoundLoadoutStage stage, CsTeam team, bool givePreferredWeapon)
    {
        var items = new List<CsItem>();

        var secondaryPool = stage.GetSecondaryWeapons(team);
        if (secondaryPool.Count > 0)
        {
            items.Add(Choice(secondaryPool));
        }

        if (givePreferredWeapon && stage.PreferredWeapon is not null)
        {
            items.Add(WeaponHelpers.CoercePreferredTeam(stage.PreferredWeapon, team) ?? stage.PreferredWeapon.Value);
            return items;
        }

        var primaryPool = stage.GetPrimaryWeapons(team);
        if (primaryPool.Count > 0)
        {
            items.Add(Choice(primaryPool));
        }

        return items;
    }

    /**
     * Selects at most one player across both active teams to receive the stage's preferred weapon.
     * Returns default(T) when the stage has no preferred weapon configured or there are no eligible players.
     */
    public static T? SelectPreferredWeaponRecipient<T>(RoundLoadoutStage stage, IList<T> tPlayers, IList<T> ctPlayers)
    {
        if (stage.MaxPreferredWeapons <= 0 || stage.PreferredWeapon is null)
        {
            return default;
        }

        var activePlayers = tPlayers.Concat(ctPlayers).ToList();
        if (activePlayers.Count == 0)
        {
            return default;
        }

        return activePlayers[RandomIndex(activePlayers.Count)];
    }

    private static CsItem Choice(IReadOnlyList<CsItem> items) => items[RandomIndex(items.Count)];
}
