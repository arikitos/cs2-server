"""HTTP safeguards for the owner-only, same-origin management panel."""

from urllib.parse import urlsplit

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

import maintenance_guard


def install(panel):
    app = panel.app
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    @app.before_request
    def guard_mutations():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if request.headers.get("X-CS2-Panel") != "1":
            return jsonify(ok=False, error="The X-CS2-Panel header is required"), 403
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(ok=False, error="Cross-origin requests are not allowed"), 403
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(ok=False, error="Cross-site requests are not allowed"), 403
        if not request.is_json or not isinstance(request.get_json(silent=True), dict):
            return jsonify(ok=False, error="A JSON object is required"), 400
        # Connection copying is an authenticated read and does not change the game.
        if maintenance_guard.MAINTENANCE_LOCK.locked() and request.endpoint != "api_connection_command":
            return jsonify(ok=False, error="Server maintenance is running. Wait for it to finish."), 409
        return None

    @app.after_request
    def secure_response(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.path.startswith("/api/") or request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def api_error(error):
        if isinstance(error, HTTPException):
            return jsonify(ok=False, error=error.description), error.code
        app.logger.exception("Panel request failed")
        if isinstance(error, panel.DockerException):
            return jsonify(ok=False, error="Docker is unavailable. Check the engine and socket mount."), 503
        return jsonify(ok=False, error="The operation failed. Check the panel logs."), 500

    @app.get("/healthz")
    def healthz():
        if not panel.PASSWORD or panel.MODE_DEF_ERRORS or set(panel.MODES) != {"faceit", "retakes"}:
            return jsonify(ok=False), 503
        return jsonify(ok=True)
