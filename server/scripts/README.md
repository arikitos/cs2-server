# Server commands

Run these commands from the repository root:

- Linux or Intel macOS: `bash server/scripts/setup.sh`.
- Windows: double-click `run-setup.cmd` at the repository root or run `powershell -File .\setup.ps1`. The original paths under `server/scripts` still work.
- Start only the panel and refresh its installation configuration: `bash server/scripts/start.sh`.
- Stop the game and panel: `bash server/scripts/stop.sh`.

Setup creates `.env` with random passwords when it is absent, prepares local directories, records the resolved Compose model in the ignored state directory and builds and starts only the panel. Windows setup starts Docker Desktop if needed, prepares verified Python-download CA chains using existing Windows HTTPS trust, waits for panel health and opens the browser. It never downloads game files, builds game images, or stops a running game.

After logging in, select **Maintenance > Install server**. This separate background job installs Steam files and pinned frameworks and prepares the stopped game container. Follow progress in the panel, retry failed downloads there, then choose FaceIt or Retakes and start the game.

Re-run setup after changing `.env` or Compose overrides. It preserves existing credentials and server data. Panel image downloads and Python package installation still require working registry/PyPI access and valid HTTPS certificates. CS2 requires Linux containers on an x86-64 Docker engine.
