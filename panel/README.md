# Control panel

The panel keeps the existing Flask/Docker architecture. Gunicorn serves `wsgi:app` with one process and four threads so the lifecycle locks and background-job registry are shared. `wsgi.py` installs runtime configuration, maintenance and HTTP safeguards before accepting requests.

`templates/index.html`, `static/style.css` and `static/app.js` implement the dashboard, console, players, mode editor, access settings, maintenance and activity screens. The browser uses the authenticated `/api/v3` API; no external frontend dependencies or build tooling are needed.

Write requests require the `X-CS2-Panel: 1` header and a JSON object. The frontend sends both automatically. `/healthz` exposes only readiness for Docker health checks. All management data requires owner authentication.

Build and start from the repository root with `docker compose up -d --build --no-deps panel`. See the root README for first installation.
