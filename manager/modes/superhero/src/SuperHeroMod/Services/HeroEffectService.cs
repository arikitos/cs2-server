using CounterStrikeSharp.API;
using CounterStrikeSharp.API.Core;
using SuperHeroMod.Configuration;
using SuperHeroMod.Core;
using SuperHeroMod.Utilities;

namespace SuperHeroMod.Services;

public sealed class HeroEffectService
{
    private readonly SuperHeroConfig _config;
    private readonly PlayerStateService _states;
    private HeroCatalog _catalog;

    public HeroEffectService(SuperHeroConfig config, PlayerStateService states, HeroCatalog catalog)
    {
        _config = config; _states = states; _catalog = catalog;
    }

    public void ReplaceCatalog(HeroCatalog catalog) => _catalog = catalog;

    public AggregatedHeroStats Aggregate(PlayerHeroState state)
    {
        float health=1f, armor=1f, speed=1f, gravity=1f, jump=1f, outgoing=1f, incoming=1f, melee=1f;
        int regen=0;
        foreach (var id in state.EquippedHeroIds)
        {
            if (!_catalog.TryGet(id, out var hero) || !hero.Enabled) continue;
            var s = hero.Stats;
            health*=s.HealthMultiplier; armor*=s.ArmorMultiplier; speed*=s.MovementSpeedMultiplier; gravity*=s.GravityMultiplier;
            jump*=s.JumpMultiplier; outgoing*=s.OutgoingDamageMultiplier; incoming*=s.IncomingDamageMultiplier; melee*=s.MeleeDamageMultiplier; regen+=s.RegenerationPerSecond;
        }
        return new AggregatedHeroStats(
            Math.Clamp(health,_config.HealthMultiplierMin,_config.GlobalMultiplierMax),
            Math.Clamp(armor,0f,_config.GlobalMultiplierMax),
            Math.Clamp(speed,_config.MovementMultiplierMin,_config.GlobalMultiplierMax),
            Math.Clamp(gravity,_config.GravityMultiplierMin,_config.GlobalMultiplierMax),
            Math.Clamp(jump,_config.MovementMultiplierMin,_config.GlobalMultiplierMax),
            Math.Clamp(outgoing,0f,_config.GlobalMultiplierMax),
            Math.Clamp(incoming,0f,_config.GlobalMultiplierMax),
            Math.Clamp(melee,0f,_config.GlobalMultiplierMax),
            Math.Clamp(regen,0,GameplaySafety.MaxRegenerationPerSecond));
    }

    public void CaptureAndApplyOnSpawn(CCSPlayerController player)
    {
        if (!PlayerUtil.IsAlivePlayer(player)) return;
        var pawn = player.PlayerPawn.Value!; var state = _states.Get(player.Index);
        state.PawnHandle = pawn.Handle;
        state.BaselineHealth = Math.Max(1,pawn.Health);
        state.BaselineMaxHealth = Math.Max(1,pawn.MaxHealth);
        state.BaselineArmor = Math.Max(0,pawn.ArmorValue);
        state.ArmorBaselineCaptured = pawn.ArmorValue > 0;
        state.BaselineVelocityModifier = pawn.VelocityModifier <= 0 ? 1f : pawn.VelocityModifier;
        state.BaselineGravityScale = pawn.ActualGravityScale <= 0 ? 1f : pawn.ActualGravityScale;
        state.ResetTemporaryEffects(); state.NextRegenUtc = DateTime.UtcNow.AddSeconds(1);
        ApplyStaticPassives(player,state);
    }

    public void ApplyStaticPassives(CCSPlayerController player, PlayerHeroState state)
    {
        if (!PlayerUtil.IsAlivePlayer(player)) return;
        var pawn = player.PlayerPawn.Value!;
        if (state.PawnHandle != pawn.Handle) { CaptureAndApplyOnSpawn(player); return; }
        var stats = Aggregate(state);
        var targetMaxHealth = GameplayMath.MultiplyAndClamp(state.BaselineMaxHealth,stats.HealthMultiplier,1,Math.Max(1,state.BaselineMaxHealth*2));
        var targetHealth = Math.Min(targetMaxHealth,Math.Max(1,GameplayMath.MultiplyAndClamp(state.BaselineHealth,stats.HealthMultiplier,1,targetMaxHealth)));
        PlayerUtil.SetHealth(pawn,targetHealth,targetMaxHealth); ApplyMovement(player,state,stats);
        if (state.ArmorBaselineCaptured && stats.ArmorMultiplier != 1f)
            PlayerUtil.SetArmor(pawn,GameplayMath.MultiplyAndClamp(state.BaselineArmor,stats.ArmorMultiplier,0,Math.Max(0,state.BaselineArmor*2)));
    }

    public void TickPlayer(CCSPlayerController player, DateTime nowUtc)
    {
        if (!PlayerUtil.IsAlivePlayer(player) || !_states.TryGet(player.Index,out var state)) return;
        var pawn = player.PlayerPawn.Value!;
        if (state.PawnHandle != pawn.Handle) { CaptureAndApplyOnSpawn(player); return; }
        if (state.SpeedEffectUntilUtc <= nowUtc) state.TemporarySpeedMultiplier=1f;
        if (state.DamageEffectUntilUtc <= nowUtc) state.TemporaryOutgoingDamageMultiplier=1f;
        if (state.SlowEffectUntilUtc <= nowUtc) state.TemporarySlowMultiplier=1f;
        if (state.NoclipActive && state.NoclipUntilUtc <= nowUtc) StopNoclip(player,state);
        var stats=Aggregate(state); ApplyMovement(player,state,stats);
        if (!state.ArmorBaselineCaptured && pawn.ArmorValue > 0)
        {
            state.BaselineArmor=pawn.ArmorValue; state.ArmorBaselineCaptured=true;
            if (stats.ArmorMultiplier != 1f) PlayerUtil.SetArmor(pawn,GameplayMath.MultiplyAndClamp(state.BaselineArmor,stats.ArmorMultiplier,0,Math.Max(0,state.BaselineArmor*2)));
        }
        if (stats.RegenerationPerSecond > 0 && nowUtc >= state.NextRegenUtc)
        {
            if (pawn.Health > 0 && pawn.Health < pawn.MaxHealth)
            {
                pawn.Health=Math.Min(pawn.MaxHealth,pawn.Health+stats.RegenerationPerSecond);
                CounterStrikeSharp.API.Utilities.SetStateChanged(pawn,"CBaseEntity","m_iHealth");
            }
            state.NextRegenUtc=nowUtc.AddSeconds(1);
        }
    }

    private void ApplyMovement(CCSPlayerController player, PlayerHeroState state, AggregatedHeroStats stats)
    {
        var pawn=player.PlayerPawn.Value; if (pawn==null || !pawn.IsValid) return;
        var totalSpeedMultiplier=Math.Clamp(stats.MovementSpeedMultiplier*state.TemporarySpeedMultiplier*state.TemporarySlowMultiplier,_config.MovementMultiplierMin,_config.GlobalMultiplierMax);
        pawn.VelocityModifier=state.BaselineVelocityModifier*totalSpeedMultiplier;
        pawn.ActualGravityScale=state.BaselineGravityScale*Math.Clamp(stats.GravityMultiplier,_config.GravityMultiplierMin,_config.GlobalMultiplierMax);
    }

    public void RestoreBaseline(CCSPlayerController player)
    {
        if (!PlayerUtil.IsAlivePlayer(player) || !_states.TryGet(player.Index,out var state)) return;
        var pawn=player.PlayerPawn.Value!; if (state.PawnHandle != pawn.Handle) return;
        if (state.NoclipActive) StopNoclip(player,state);
        pawn.VelocityModifier=state.BaselineVelocityModifier; pawn.ActualGravityScale=state.BaselineGravityScale;
        pawn.MaxHealth=state.BaselineMaxHealth; CounterStrikeSharp.API.Utilities.SetStateChanged(pawn,"CBaseEntity","m_iMaxHealth");
        pawn.Health=Math.Max(1,Math.Min(pawn.Health,state.BaselineMaxHealth)); CounterStrikeSharp.API.Utilities.SetStateChanged(pawn,"CBaseEntity","m_iHealth");
        if (state.ArmorBaselineCaptured) PlayerUtil.SetArmor(pawn,Math.Min(pawn.ArmorValue,state.BaselineArmor));
        state.ResetTemporaryEffects();
    }

    public void StopNoclip(CCSPlayerController player, PlayerHeroState state)
    {
        if (!state.NoclipActive) return;
        state.NoclipActive=false; state.NoclipUntilUtc=DateTime.MinValue;
        if (!PlayerUtil.IsAlivePlayer(player)) return;
        PlayerUtil.SetNoclip(player,false);
        var pawn=player.PlayerPawn.Value;
        if (pawn!=null && pawn.IsValid && state.NoclipStartPosition!=null) pawn.Teleport(state.NoclipStartPosition,null,new CounterStrikeSharp.API.Modules.Utils.Vector(0,0,0));
        state.NoclipStartPosition=null;
    }
}
