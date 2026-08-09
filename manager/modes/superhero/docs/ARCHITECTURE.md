# Architecture

The MVP is data driven. `heroes.json` is validated by `HeroCatalog`, player state is owned by `PlayerStateService`, passive effects by `HeroEffectService`, and active powers by `AbilityService`.

Normalized modifiers use `1.0` as neutral CS2 behavior. Movement, gravity and health use positive safety minima; the general multiplier ceiling is `2.0`.

Damage direction is explicit. `OutgoingDamageMultiplier` modifies damage dealt by the attacker, while `IncomingDamageMultiplier` modifies damage received by the victim. Melee is an additional attacker-side layer.

Spawn-time baselines capture health, max health, armor, velocity modifier and gravity scale. Repeated effects are recomputed from the captured baseline rather than multiplying mutable properties every tick.

Generic active powers in the MVP are `SelfHeal`, `SpeedBurst`, `DamageBoost`, `HighJump`, `RadialSlow`, `RadialKnockback`, `RadialPull`, and `Noclip`. Cooldowns are stored per hero id so multiple hero slots can be added later without replacing the cooldown model.

CounterStrikeSharp owns `SuperHeroMod.json` under `configs/plugins/SuperHeroMod`. `heroes.json` is resolved relative to the same directory. `css_shreload` reloads both with rollback when validation fails.
