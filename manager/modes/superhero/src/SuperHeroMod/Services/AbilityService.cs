using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using SuperHeroMod.Configuration;
using SuperHeroMod.Core;
using SuperHeroMod.Utilities;

namespace SuperHeroMod.Services;

public sealed class AbilityService
{
    private readonly SuperHeroConfig _config;
    private readonly PlayerStateService _states;
    private readonly HeroEffectService _effects;

    public AbilityService(SuperHeroConfig config, PlayerStateService states, HeroEffectService effects)
    {
        _config = config; _states = states; _effects = effects;
    }

    public string Use(CCSPlayerController player, HeroDefinition hero)
    {
        if (!PlayerUtil.IsAlivePlayer(player)) return "You must be alive to use your power.";
        var ability = hero.Ability;
        if (ability.Kind == HeroAbilityKind.None) return $"{hero.Name} has no active power.";
        var state = _states.Get(player.Index); var now = DateTime.UtcNow;
        var nextUseUtc = state.NextPowerUseUtcByHero.GetValueOrDefault(hero.Id, DateTime.MinValue);
        if (nextUseUtc > now) return $"Power cooldown, {Math.Max(0, (int)Math.Ceiling((nextUseUtc - now).TotalSeconds))}s remaining.";

        var result = ability.Kind switch
        {
            HeroAbilityKind.SelfHeal => SelfHeal(player, ability),
            HeroAbilityKind.SpeedBurst => SpeedBurst(state, ability, now),
            HeroAbilityKind.DamageBoost => DamageBoost(state, ability, now),
            HeroAbilityKind.HighJump => HighJump(player, ability),
            HeroAbilityKind.RadialSlow => RadialSlow(player, ability, now),
            HeroAbilityKind.RadialKnockback => RadialForce(player, ability, false),
            HeroAbilityKind.RadialPull => RadialForce(player, ability, true),
            HeroAbilityKind.Noclip => StartNoclip(player, state, ability, now),
            _ => new AbilityResult(false, "Power is not implemented.")
        };
        if (result.Success) state.NextPowerUseUtcByHero[hero.Id] = now.AddSeconds(ability.CooldownSeconds);
        return result.Message;
    }

    private static AbilityResult SelfHeal(CCSPlayerController player, HeroAbility ability)
    {
        var pawn = player.PlayerPawn.Value!; var before = pawn.Health;
        pawn.Health = Math.Min(pawn.MaxHealth, pawn.Health + Math.Max(0, (int)Math.Round(ability.Magnitude)));
        CounterStrikeSharp.API.Utilities.SetStateChanged(pawn, "CBaseEntity", "m_iHealth");
        return new(true, $"Healed {pawn.Health - before} HP.");
    }

    private AbilityResult SpeedBurst(PlayerHeroState state, HeroAbility ability, DateTime now)
    {
        state.TemporarySpeedMultiplier = Math.Clamp(ability.Magnitude, 1f, _config.GlobalMultiplierMax);
        state.SpeedEffectUntilUtc = now.AddSeconds(ability.DurationSeconds);
        return new(true, $"Speed burst active for {ability.DurationSeconds:0.#}s.");
    }

    private AbilityResult DamageBoost(PlayerHeroState state, HeroAbility ability, DateTime now)
    {
        state.TemporaryOutgoingDamageMultiplier = Math.Clamp(ability.Magnitude, 1f, _config.GlobalMultiplierMax);
        state.DamageEffectUntilUtc = now.AddSeconds(ability.DurationSeconds);
        return new(true, $"Damage boost active for {ability.DurationSeconds:0.#}s.");
    }

    private static AbilityResult HighJump(CCSPlayerController player, HeroAbility ability)
    {
        var pawn = player.PlayerPawn.Value!;
        pawn.AbsVelocity.Z = Math.Min(pawn.AbsVelocity.Z + ability.VerticalBoost, GameplaySafety.MaxVerticalVelocity);
        return new(true, "Super jump activated.");
    }

    private AbilityResult RadialSlow(CCSPlayerController player, HeroAbility ability, DateTime now)
    {
        var sourcePawn = player.PlayerPawn.Value!;
        if (sourcePawn.AbsOrigin == null) return new(false, "No valid origin.");
        var affected = 0;
        foreach (var target in CounterStrikeSharp.API.Utilities.GetPlayers())
        {
            if (!PlayerUtil.IsAlivePlayer(target) || target.Index == player.Index || target.Team == player.Team) continue;
            var targetPawn = target.PlayerPawn.Value!;
            if (targetPawn.AbsOrigin == null || PlayerUtil.Distance(sourcePawn.AbsOrigin, targetPawn.AbsOrigin) > ability.Radius) continue;
            var state = _states.Get(target.Index);
            if (state.PawnHandle != targetPawn.Handle) { _effects.CaptureAndApplyOnSpawn(target); state = _states.Get(target.Index); }
            state.TemporarySlowMultiplier = Math.Min(state.TemporarySlowMultiplier, Math.Clamp(ability.Magnitude, GameplaySafety.MinSlowMultiplier, 1f));
            state.SlowEffectUntilUtc = now.AddSeconds(ability.DurationSeconds); affected++;
        }
        return affected > 0 ? new(true, $"Slowed {affected} enemies.") : new(false, "No enemies in range.");
    }

    private static AbilityResult RadialForce(CCSPlayerController player, HeroAbility ability, bool pull)
    {
        var sourcePawn = player.PlayerPawn.Value!;
        if (sourcePawn.AbsOrigin == null) return new(false, "No valid origin.");
        var affected = 0;
        foreach (var target in CounterStrikeSharp.API.Utilities.GetPlayers())
        {
            if (!PlayerUtil.IsAlivePlayer(target) || target.Index == player.Index || target.Team == player.Team) continue;
            var targetPawn = target.PlayerPawn.Value!;
            if (targetPawn.AbsOrigin == null) continue;
            var dx = targetPawn.AbsOrigin.X - sourcePawn.AbsOrigin.X; var dy = targetPawn.AbsOrigin.Y - sourcePawn.AbsOrigin.Y; var dz = targetPawn.AbsOrigin.Z - sourcePawn.AbsOrigin.Z;
            var length = MathF.Sqrt((dx * dx) + (dy * dy) + (dz * dz));
            if (length <= 1f || length > ability.Radius) continue;
            var sign = pull ? -1f : 1f; var strength = Math.Clamp(ability.Magnitude, 0f, GameplaySafety.MaxRadialForce);
            targetPawn.AbsVelocity.X += sign * (dx / length) * strength;
            targetPawn.AbsVelocity.Y += sign * (dy / length) * strength;
            targetPawn.AbsVelocity.Z += sign * (dz / length) * strength + (pull ? 0f : 120f); affected++;
        }
        return affected > 0 ? new(true, $"{(pull ? "Pulled" : "Knocked back")} {affected} enemies.") : new(false, "No enemies in range.");
    }

    private AbilityResult StartNoclip(CCSPlayerController player, PlayerHeroState state, HeroAbility ability, DateTime now)
    {
        if (state.NoclipActive) return new(false, "Noclip is already active.");
        var pawn = player.PlayerPawn.Value!;
        if (pawn.AbsOrigin == null) return new(false, "No valid origin.");
        state.NoclipStartPosition = PlayerUtil.Copy(pawn.AbsOrigin); state.NoclipActive = true; state.NoclipUntilUtc = now.AddSeconds(ability.DurationSeconds);
        PlayerUtil.SetNoclip(player, true);
        return new(true, $"Noclip active for {ability.DurationSeconds:0.#}s. You return to the activation point when it ends.");
    }

    private readonly record struct AbilityResult(bool Success, string Message);
}
