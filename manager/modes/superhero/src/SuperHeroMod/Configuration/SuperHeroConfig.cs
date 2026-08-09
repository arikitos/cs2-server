using System.Text.Json.Serialization;
using CounterStrikeSharp.API.Core;

namespace SuperHeroMod.Configuration;

public sealed class SuperHeroConfig : BasePluginConfig
{
    [JsonPropertyName("Enabled")] public bool Enabled { get; set; } = true;
    [JsonPropertyName("ChatPrefix")] public string ChatPrefix { get; set; } = "[SuperHero]";
    [JsonPropertyName("AutoAssignRandomHero")] public bool AutoAssignRandomHero { get; set; } = true;
    [JsonPropertyName("MaxEquippedHeroes")] public int MaxEquippedHeroes { get; set; } = 1;
    [JsonPropertyName("AllowHeroChangeWhileAlive")] public bool AllowHeroChangeWhileAlive { get; set; } = false;
    [JsonPropertyName("GlobalMultiplierMax")] public float GlobalMultiplierMax { get; set; } = 2.0f;
    [JsonPropertyName("MovementMultiplierMin")] public float MovementMultiplierMin { get; set; } = 0.25f;
    [JsonPropertyName("GravityMultiplierMin")] public float GravityMultiplierMin { get; set; } = 0.10f;
    [JsonPropertyName("HealthMultiplierMin")] public float HealthMultiplierMin { get; set; } = 0.10f;
    [JsonPropertyName("HeroesFile")] public string HeroesFile { get; set; } = "heroes.json";
    [JsonPropertyName("ShowHeroOnSpawn")] public bool ShowHeroOnSpawn { get; set; } = true;
}
