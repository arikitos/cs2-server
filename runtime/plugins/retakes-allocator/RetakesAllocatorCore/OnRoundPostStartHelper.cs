using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Utils;
using RetakesAllocatorCore.Config;
using RetakesAllocatorCore.Db;
using RetakesAllocatorCore.Managers;
using System;

namespace RetakesAllocatorCore;

public class OnRoundPostStartHelper
{
    public static void Handle<T>(
        ICollection<T> allPlayers,
        Func<T?, ulong> getSteamId,
        Func<T, CsTeam> getTeam,
        Action<T> giveDefuseKit,
        Action<T, ICollection<CsItem>, string?> allocateItemsForPlayer,
        Func<T, bool> isVip,
        out RoundType currentRoundType
    ) where T : notnull
    {
        var tPlayers = new List<T>();
        var ctPlayers = new List<T>();
        var playerIds = new List<ulong>();
        foreach (var player in allPlayers)
        {
            var steamId = getSteamId(player);
            if (steamId != 0)
            {
                playerIds.Add(steamId);
            }

            var playerTeam = getTeam(player);
            if (playerTeam == CsTeam.Terrorist)
            {
                tPlayers.Add(player);
            }
            else if (playerTeam == CsTeam.CounterTerrorist)
            {
                ctPlayers.Add(player);
            }
        }

        Log.Debug($"#T Players: {string.Join(",", tPlayers.Select(getSteamId))}");
        Log.Debug($"#CT Players: {string.Join(",", ctPlayers.Select(getSteamId))}");

        if (RoundTypeManager.Instance.IsLoadoutSequenceActive())
        {
            currentRoundType = HandleLoadoutSequence(
                allPlayers,
                tPlayers,
                ctPlayers,
                getTeam,
                giveDefuseKit,
                allocateItemsForPlayer
            );
            return;
        }

        var roundType = RoundTypeManager.Instance.GetNextRoundType();
        currentRoundType = roundType;

        var userSettingsByPlayerId = Queries.GetUsersSettings(playerIds);

        var defusingPlayer = Utils.Choice(ctPlayers);

        HashSet<T> FilterByPreferredWeaponPreference(IEnumerable<T> ps) =>
            ps.Where(p =>
                    userSettingsByPlayerId.TryGetValue(getSteamId(p), out var userSetting) &&
                    userSetting.GetWeaponPreference(getTeam(p), WeaponAllocationType.Preferred) is not null)
                .ToHashSet();

        ICollection<T> tPreferredPlayers = new List<T>();
        ICollection<T> ctPreferredPlayers = new List<T>();
        var automaticPreferredPlayers = new HashSet<T>();

        Random random = new Random();
        double generatedChance = random.NextDouble() * 100;

        if (roundType == RoundType.FullBuy && generatedChance <= Configs.GetConfigData().ChanceForPreferredWeapon)
        {
            if (Configs.GetConfigData().EnableAutomaticPreferredWeapon)
            {
                var activePlayers = tPlayers.Concat(ctPlayers).ToList();
                if (activePlayers.Count >= Configs.GetConfigData().MinPlayersForAutomaticPreferredWeapon)
                {
                    Utils.Shuffle(activePlayers);
                    automaticPreferredPlayers = activePlayers
                        .Take(Configs.GetConfigData().MaxAutomaticPreferredWeaponsPerRound)
                        .ToHashSet();
                }
            }
            else
            {
                tPreferredPlayers =
                    WeaponHelpers.SelectPreferredPlayers(FilterByPreferredWeaponPreference(tPlayers), isVip,
                        CsTeam.Terrorist);
                ctPreferredPlayers =
                    WeaponHelpers.SelectPreferredPlayers(FilterByPreferredWeaponPreference(ctPlayers), isVip,
                        CsTeam.CounterTerrorist);
            }
        }

        var nadesByPlayer = new Dictionary<T, ICollection<CsItem>>();
        NadeHelpers.AllocateNadesToPlayers(
            NadeHelpers.GetUtilForTeam(
                RoundTypeManager.Instance.Map,
                roundType,
                CsTeam.Terrorist,
                tPlayers.Count
            ),
            tPlayers,
            nadesByPlayer
        );
        NadeHelpers.AllocateNadesToPlayers(
            NadeHelpers.GetUtilForTeam(
                RoundTypeManager.Instance.Map,
                roundType,
                CsTeam.CounterTerrorist,
                tPlayers.Count
            ),
            ctPlayers,
            nadesByPlayer
        );

        foreach (var player in allPlayers)
        {
            var team = getTeam(player);
            var playerSteamId = getSteamId(player);
            userSettingsByPlayerId.TryGetValue(playerSteamId, out var userSetting);
            var items = new List<CsItem>
            {
                RoundTypeHelpers.GetArmorForRoundType(roundType),
                team == CsTeam.Terrorist ? CsItem.DefaultKnifeT : CsItem.DefaultKnifeCT,
            };

            var giveAutomaticPreferred = automaticPreferredPlayers.Contains(player);
            var givePreferred = giveAutomaticPreferred || (team switch
            {
                CsTeam.Terrorist => tPreferredPlayers.Contains(player),
                CsTeam.CounterTerrorist => ctPreferredPlayers.Contains(player),
                _ => false,
            });

            items.AddRange(
                WeaponHelpers.GetWeaponsForRoundType(
                    roundType,
                    team,
                    userSetting,
                    givePreferred,
                    giveAutomaticPreferred ? Configs.GetConfigData().AutomaticPreferredWeapon : null
                )
            );

            if (nadesByPlayer.TryGetValue(player, out var playerNades))
            {
                items.AddRange(playerNades);
            }

            if (team == CsTeam.CounterTerrorist)
            {
                // On non-pistol rounds, everyone gets defuse kit and util
                if (roundType != RoundType.Pistol)
                {
                    giveDefuseKit(player);
                }
                else if (getSteamId(defusingPlayer) == getSteamId(player))
                {
                    // On pistol rounds, only one person gets a defuse kit
                    giveDefuseKit(player);
                }
            }

            if (Configs.GetConfigData().ZeusPreference == ZeusPreference.Always)
            {
                items.Add(CsItem.Zeus);
            }

            allocateItemsForPlayer(player, items, team == CsTeam.Terrorist ? "slot5" : "slot1");
        }
    }

    private static RoundType HandleLoadoutSequence<T>(
        ICollection<T> allPlayers,
        List<T> tPlayers,
        List<T> ctPlayers,
        Func<T, CsTeam> getTeam,
        Action<T> giveDefuseKit,
        Action<T, ICollection<CsItem>, string?> allocateItemsForPlayer
    ) where T : notnull
    {
        var stage = RoundTypeManager.Instance.GetCurrentLoadoutStage();
        RoundTypeManager.Instance.AdvanceLoadoutSequenceRound();

        // Stages with no primary weapons for either team behave like a pistol round for
        // armor, util, and defuse-kit distribution; everything else behaves like a full buy.
        var isPistolStyleStage = stage.TerroristPrimaryWeapons.Count == 0 && stage.CounterTerroristPrimaryWeapons.Count == 0;
        var roundType = isPistolStyleStage ? RoundType.Pistol : RoundType.FullBuy;

        var preferredWeaponRecipient =
            RoundLoadoutAllocator.SelectPreferredWeaponRecipient(stage, tPlayers, ctPlayers);

        var defusingPlayer = Utils.Choice(ctPlayers);

        var nadesByPlayer = new Dictionary<T, ICollection<CsItem>>();
        NadeHelpers.AllocateNadesToPlayers(
            NadeHelpers.GetUtilForTeam(RoundTypeManager.Instance.Map, roundType, CsTeam.Terrorist, tPlayers.Count),
            tPlayers,
            nadesByPlayer
        );
        NadeHelpers.AllocateNadesToPlayers(
            NadeHelpers.GetUtilForTeam(RoundTypeManager.Instance.Map, roundType, CsTeam.CounterTerrorist, tPlayers.Count),
            ctPlayers,
            nadesByPlayer
        );

        foreach (var player in allPlayers)
        {
            var team = getTeam(player);
            var items = new List<CsItem>
            {
                RoundTypeHelpers.GetArmorForRoundType(roundType),
                team == CsTeam.Terrorist ? CsItem.DefaultKnifeT : CsItem.DefaultKnifeCT,
            };

            var givePreferred = EqualityComparer<T>.Default.Equals(player, preferredWeaponRecipient!) &&
                                 preferredWeaponRecipient is not null;

            items.AddRange(RoundLoadoutAllocator.GetWeaponsForPlayer(stage, team, givePreferred));

            if (nadesByPlayer.TryGetValue(player, out var playerNades))
            {
                items.AddRange(playerNades);
            }

            if (team == CsTeam.CounterTerrorist)
            {
                if (roundType != RoundType.Pistol)
                {
                    giveDefuseKit(player);
                }
                else if (defusingPlayer is not null &&
                         EqualityComparer<T>.Default.Equals(defusingPlayer, player))
                {
                    giveDefuseKit(player);
                }
            }

            if (Configs.GetConfigData().ZeusPreference == ZeusPreference.Always)
            {
                items.Add(CsItem.Zeus);
            }

            allocateItemsForPlayer(player, items, team == CsTeam.Terrorist ? "slot5" : "slot1");
        }

        return roundType;
    }
}
