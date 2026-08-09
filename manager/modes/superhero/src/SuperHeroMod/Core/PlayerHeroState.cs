using CounterStrikeSharp.API.Modules.Utils;

namespace SuperHeroMod.Core;

public sealed class PlayerHeroState
{
    public List<string> EquippedHeroIds { get; } = [];
    public List<string> PendingHeroIds { get; } = [];
    public nint PawnHandle { get; set; }
    public int BaselineHealth { get; set; } = 100;
    public int BaselineMaxHealth { get; set; } = 100;
    public int BaselineArmor { get; set; }
    public bool ArmorBaselineCaptured { get; set; }
    public float BaselineVelocityModifier { get; set; } = 1f;
    public float BaselineGravityScale { get; set; } = 1f;
    public float TemporarySpeedMultiplier { get; set; } = 1f;
    public DateTime SpeedEffectUntilUtc { get; set; } = DateTime.MinValue;
    public float TemporaryOutgoingDamageMultiplier { get; set; } = 1f;
    public DateTime DamageEffectUntilUtc { get; set; } = DateTime.MinValue;
    public float TemporarySlowMultiplier { get; set; } = 1f;
    public DateTime SlowEffectUntilUtc { get; set; } = DateTime.MinValue;
    public Dictionary<string, DateTime> NextPowerUseUtcByHero { get; } = new(StringComparer.OrdinalIgnoreCase);
    public DateTime NextRegenUtc { get; set; } = DateTime.MinValue;
    public bool NoclipActive { get; set; }
    public DateTime NoclipUntilUtc { get; set; } = DateTime.MinValue;
    public Vector? NoclipStartPosition { get; set; }

    public void ResetTemporaryEffects()
    {
        TemporarySpeedMultiplier = 1f;
        SpeedEffectUntilUtc = DateTime.MinValue;
        TemporaryOutgoingDamageMultiplier = 1f;
        DamageEffectUntilUtc = DateTime.MinValue;
        TemporarySlowMultiplier = 1f;
        SlowEffectUntilUtc = DateTime.MinValue;
        NoclipActive = false;
        NoclipUntilUtc = DateTime.MinValue;
        NoclipStartPosition = null;
    }
}
