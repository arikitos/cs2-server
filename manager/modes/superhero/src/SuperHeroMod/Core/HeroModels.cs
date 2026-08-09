using System.Text.Json.Serialization;

namespace SuperHeroMod.Core;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum HeroAbilityKind { None, SelfHeal, SpeedBurst, DamageBoost, HighJump, RadialSlow, RadialKnockback, RadialPull, Noclip }

public sealed class HeroStats
{
    public float HealthMultiplier { get; set; } = 1f;
    public float ArmorMultiplier { get; set; } = 1f;
    public float MovementSpeedMultiplier { get; set; } = 1f;
    public float GravityMultiplier { get; set; } = 1f;
    public float JumpMultiplier { get; set; } = 1f;
    public float OutgoingDamageMultiplier { get; set; } = 1f;
    public float IncomingDamageMultiplier { get; set; } = 1f;
    public float MeleeDamageMultiplier { get; set; } = 1f;
    public int RegenerationPerSecond { get; set; }
}

public sealed class HeroAbility
{
    public HeroAbilityKind Kind { get; set; } = HeroAbilityKind.None;
    public float CooldownSeconds { get; set; } = 20f;
    public float DurationSeconds { get; set; } = 3f;
    public float Magnitude { get; set; } = 1f;
    public float Radius { get; set; } = 350f;
    public float VerticalBoost { get; set; } = 400f;
}

public sealed class HeroDefinition
{
    public required string Id { get; set; }
    public required string Name { get; set; }
    public string Description { get; set; } = "";
    public bool Enabled { get; set; } = true;
    public HeroStats Stats { get; set; } = new();
    public HeroAbility Ability { get; set; } = new();
}

public readonly record struct AggregatedHeroStats(float HealthMultiplier, float ArmorMultiplier, float MovementSpeedMultiplier, float GravityMultiplier, float JumpMultiplier, float OutgoingDamageMultiplier, float IncomingDamageMultiplier, float MeleeDamageMultiplier, int RegenerationPerSecond)
{
    public static AggregatedHeroStats Neutral => new(1f,1f,1f,1f,1f,1f,1f,1f,0);
}
