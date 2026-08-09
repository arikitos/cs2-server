using System.Text.Json;
using System.Text.Json.Serialization;
using SuperHeroMod.Configuration;

namespace SuperHeroMod.Core;

public sealed class HeroCatalog
{
    private readonly Dictionary<string, HeroDefinition> _byId;
    public IReadOnlyCollection<HeroDefinition> All => _byId.Values;

    public HeroCatalog(IEnumerable<HeroDefinition> heroes, SuperHeroConfig config)
    {
        _byId = new Dictionary<string, HeroDefinition>(StringComparer.OrdinalIgnoreCase);
        foreach (var hero in heroes)
        {
            Validate(hero, config);
            if (_byId.ContainsKey(hero.Id)) throw new InvalidOperationException($"Duplicate hero id '{hero.Id}'.");
            _byId[hero.Id] = hero;
        }
        if (_byId.Count == 0) throw new InvalidOperationException("Hero catalog is empty.");
    }

    public bool TryGet(string id, out HeroDefinition hero) => _byId.TryGetValue(id, out hero!);

    public HeroDefinition? FindByIdOrName(string input)
    {
        if (_byId.TryGetValue(input, out var exact)) return exact;
        return _byId.Values.FirstOrDefault(hero => hero.Name.Equals(input, StringComparison.OrdinalIgnoreCase));
    }

    public static HeroCatalog Load(string path, SuperHeroConfig config)
    {
        if (!File.Exists(path)) throw new FileNotFoundException($"Hero definition file was not found at '{path}'.", path);
        var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true, ReadCommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true };
        options.Converters.Add(new JsonStringEnumConverter());
        var heroes = JsonSerializer.Deserialize<List<HeroDefinition>>(File.ReadAllText(path), options) ?? throw new InvalidOperationException("heroes.json could not be parsed.");
        return new HeroCatalog(heroes, config);
    }

    private static void Validate(HeroDefinition hero, SuperHeroConfig config)
    {
        if (string.IsNullOrWhiteSpace(hero.Id)) throw new InvalidOperationException("Every hero must have a non-empty Id.");
        if (string.IsNullOrWhiteSpace(hero.Name)) throw new InvalidOperationException($"Hero '{hero.Id}' must have a non-empty Name.");
        var s = hero.Stats;
        ValidateMultiplier(hero.Id, nameof(s.HealthMultiplier), s.HealthMultiplier, config.HealthMultiplierMin, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.ArmorMultiplier), s.ArmorMultiplier, 0f, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.MovementSpeedMultiplier), s.MovementSpeedMultiplier, config.MovementMultiplierMin, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.GravityMultiplier), s.GravityMultiplier, config.GravityMultiplierMin, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.JumpMultiplier), s.JumpMultiplier, config.MovementMultiplierMin, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.OutgoingDamageMultiplier), s.OutgoingDamageMultiplier, 0f, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.IncomingDamageMultiplier), s.IncomingDamageMultiplier, 0f, config.GlobalMultiplierMax);
        ValidateMultiplier(hero.Id, nameof(s.MeleeDamageMultiplier), s.MeleeDamageMultiplier, 0f, config.GlobalMultiplierMax);
        if (s.RegenerationPerSecond is < 0 or > GameplaySafety.MaxRegenerationPerSecond) throw new InvalidOperationException($"Hero '{hero.Id}' RegenerationPerSecond must be between 0 and {GameplaySafety.MaxRegenerationPerSecond}.");

        var a = hero.Ability;
        if (a.CooldownSeconds < 0 || a.CooldownSeconds > GameplaySafety.MaxAbilityCooldownSeconds) throw new InvalidOperationException($"Hero '{hero.Id}' ability cooldown is out of range.");
        if (a.DurationSeconds < 0 || a.DurationSeconds > GameplaySafety.MaxAbilityDurationSeconds) throw new InvalidOperationException($"Hero '{hero.Id}' ability duration is out of range.");
        if (a.Radius < 0 || a.Radius > GameplaySafety.MaxAbilityRadiusUnits) throw new InvalidOperationException($"Hero '{hero.Id}' ability radius is out of range.");

        switch (a.Kind)
        {
            case HeroAbilityKind.SpeedBurst:
            case HeroAbilityKind.DamageBoost:
                ValidateMultiplier(hero.Id, "Ability.Magnitude", a.Magnitude, 0f, config.GlobalMultiplierMax);
                break;
            case HeroAbilityKind.RadialSlow:
                ValidateMultiplier(hero.Id, "Ability.Magnitude", a.Magnitude, GameplaySafety.MinSlowMultiplier, 1f);
                break;
            case HeroAbilityKind.RadialKnockback:
            case HeroAbilityKind.RadialPull:
                if (a.Magnitude < 0 || a.Magnitude > GameplaySafety.MaxRadialForce) throw new InvalidOperationException($"Hero '{hero.Id}' radial force is out of range.");
                break;
            case HeroAbilityKind.HighJump:
                if (a.VerticalBoost < 0 || a.VerticalBoost > GameplaySafety.MaxVerticalVelocity) throw new InvalidOperationException($"Hero '{hero.Id}' vertical boost is out of range.");
                break;
            case HeroAbilityKind.SelfHeal:
                if (a.Magnitude < 0 || a.Magnitude > GameplaySafety.MaxSelfHeal) throw new InvalidOperationException($"Hero '{hero.Id}' heal amount is out of range.");
                break;
        }
    }

    private static void ValidateMultiplier(string id, string field, float value, float min, float max)
    {
        if (float.IsNaN(value) || float.IsInfinity(value) || value < min || value > max) throw new InvalidOperationException($"Hero '{id}' {field} must be between {min:0.##} and {max:0.##}.");
    }
}
