SuperHero MVP 0.1.0 for Counter-Strike 2

Target runtime.
CounterStrikeSharp 1.0.371
Metamod Source 2.0.0-git1410

Install.
Extract the ZIP into <CS2_DATA_PATH>/game/csgo so the addons directory merges with the existing addons directory.
Restart the cs2-game container.
Verify with css_plugins list.

Commands.
!sh
!heroes
!selecthero <name>
!drophero <name>
!myheroes
!power
css_sh_reload from server console or RCON

Heroes.
Superman, extra health, armor and lower gravity.
Flash, increased speed.
Wolverine, health regeneration.
Batman, tactical spawn loadout.
Dracula, lifesteal.
Hulk, active rage power with cooldown.

Player XP and selected heroes are persisted in players.json next to the plugin DLL.
The normal CounterStrikeSharp plugin configuration is generated on first load and can be edited afterward.
