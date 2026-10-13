# HeroShift

The self-contained payload comes from [arikitos/cs2-heroshift](https://github.com/arikitos/cs2-heroshift). Its release already includes HeroShift, RayTrace, gamedata and the required API assemblies. Extract the release paths directly into this directory.

PanelBridge and ClutchAnnounce are included as mode-local companions. The default HeroShift JSON remains release-shaped here. Panel edits are copied to `server/state/configs/heroshift`, so a later release replacement does not erase operator changes.

CS2 server convars remain panel-managed for this mode. HeroShift skill overrides remain plugin-owned and can be applied to an active server with the official `css_reload` action after the state copy is synchronized.
