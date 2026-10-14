# Server commands

Run these commands from the repository root:

- Linux or Intel macOS: `bash server/scripts/setup.sh`.
- Windows: `server\scripts\run-setup.cmd` or `powershell -File server/scripts/setup.ps1`.
- Start the panel and create a stopped game container: `bash server/scripts/start.sh`.
- Stop the game and panel: `bash server/scripts/stop.sh`.

Setup creates `.env` with random passwords when it is absent, stops the game before maintenance, prepares bind-mount permissions, installs Steam files and pinned frameworks, and starts the panel. It leaves the game stopped until a mode is selected. CS2 requires Linux containers on an x86-64 Docker engine.
