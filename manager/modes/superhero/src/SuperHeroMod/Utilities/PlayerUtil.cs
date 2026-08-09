using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Modules.Entities;
using CounterStrikeSharp.API.Modules.Entities.Constants;
using CounterStrikeSharp.API.Modules.Memory;
using CounterStrikeSharp.API.Modules.Utils;

namespace SuperHeroMod.Utilities;

public static class PlayerUtil
{
    public static bool IsAlivePlayer(CCSPlayerController? player) => player != null && player.IsValid && player.PawnIsAlive && player.Team is CsTeam.Terrorist or CsTeam.CounterTerrorist && player.PlayerPawn.Value is { IsValid: true };

    public static double Distance(Vector a, Vector b)
    {
        var x = b.X - a.X; var y = b.Y - a.Y; var z = b.Z - a.Z;
        return Math.Sqrt((x * x) + (y * y) + (z * z));
    }

    public static void SetHealth(CCSPlayerPawn pawn, int health, int maxHealth)
    {
        pawn.MaxHealth = maxHealth;
        CounterStrikeSharp.API.Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iMaxHealth");
        pawn.Health = Math.Clamp(health, 1, maxHealth);
        CounterStrikeSharp.API.Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
    }

    public static void SetArmor(CCSPlayerPawn pawn, int armor)
    {
        pawn.ArmorValue = Math.Max(0, armor);
        CounterStrikeSharp.API.Utilities.SetStateChanged(pawn, "CCSPlayerPawn", "m_ArmorValue");
    }

    public static void SetNoclip(CCSPlayerController player, bool enabled)
    {
        if (!IsAlivePlayer(player)) return;
        var pawn = player.PlayerPawn.Value;
        if (pawn == null || !pawn.IsValid) return;
        pawn.MoveType = enabled ? MoveType_t.MOVETYPE_NOCLIP : MoveType_t.MOVETYPE_WALK;
        Schema.SetSchemaValue(pawn.Handle, "CBaseEntity", "m_nActualMoveType", (int)pawn.MoveType);
        CounterStrikeSharp.API.Utilities.SetStateChanged(pawn, "CBaseEntity", "m_MoveType");
    }

    public static Vector Copy(Vector value) => new(value.X, value.Y, value.Z);
}
