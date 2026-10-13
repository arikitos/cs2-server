# Operational scripts

`start.sh` creates the stopped game container and starts the panel for an already configured installation.

`stop.sh` stops the game and panel without deleting containers or persistent data.

`smoke-test.sh` verifies the live panel, mode switching, file isolation and the absence of SteamCMD activity in the game container.

Use `run-setup.cmd` at the repository root for first installation and framework setup.
