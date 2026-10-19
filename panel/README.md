# Control panel

The panel keeps the existing Flask/Docker architecture. Gunicorn serves `wsgi:app` with one process and four threads so the lifecycle locks and background-job registry are shared. `wsgi.py` installs runtime configuration, maintenance and HTTP safeguards before accepting requests.

`templates/index.html`, `static/style.css` and `static/app.js` implement three screens: the dashboard (a viewport-sized 2×2 grid of server controls with the join password, players, game log and RCON console; the full log and the server overview open as dialogs), the tabbed mode editor, which asks before restarting a running mode to apply saved changes, and maintenance (installation, jobs, backups, container logs and panel activity). An empty join password makes the server public; a filled one makes it private, applied live over RCON. The browser uses the authenticated `/api/v3` API; no external frontend dependencies or build tooling are needed.

Write requests require the `X-CS2-Panel: 1` header and a JSON object. The frontend sends both automatically. `/healthz` exposes only readiness for Docker health checks. All management data requires owner authentication.

Build and start from the repository root with `docker compose up -d --build --no-deps panel`. See the root README for first installation.

The panel works with no game image, container or Steam installation present. Run the host setup script once to save the resolved Compose model, then use **Maintenance > Install server**. `installation.py` uses that model and the panel's inspected host mounts to build and run the existing maintenance services through the Docker SDK, including Docker Desktop path translation. No host Python or Docker CLI inside the panel is needed. Installation logs and stage progress use the existing background-job API. Failed downloads leave the panel available and the game stopped; starting a game is disabled until the game files, framework versions, Metamod activation and game container are present.
