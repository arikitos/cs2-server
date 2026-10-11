"""Loopback-published, authenticated local control panel."""
import json
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import Controller, Problem

STATIC = Path(__file__).parent / 'static'

class Handler(BaseHTTPRequestHandler):
    controller = None

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Do not log URLs, credentials, cookies or request bodies.
        pass

    def respond(self, status, value, cookie=None, content_type='application/json'):
        body = json.dumps(value).encode() if content_type == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except Exception:
            return ''
        return cookies['cs2_session'].value if 'cs2_session' in cookies else ''

    def boundary(self):
        host = self.headers.get('Host', '')
        if urlsplit('http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise Problem('Access the panel through localhost or 127.0.0.1', 403)
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            raise Problem('Cross-origin requests are forbidden', 403)

    def do_GET(self):
        try:
            self.boundary()
            path = urlsplit(self.path).path
            if path == '/api/health':
                return self.respond(200, {'ok': True})
            if path == '/api/session':
                try:
                    session = self.controller.authorize(self.token())
                    return self.respond(200, {'authenticated': True, 'csrf': session['csrf'], 'setup_required': False})
                except Problem:
                    return self.respond(200, {'authenticated': False, 'setup_required': not bool(self.controller.account)})
            if path.startswith('/api/'):
                self.controller.authorize(self.token())
                if path == '/api/status':
                    return self.respond(200, self.controller.status())
                if path == '/api/preflight':
                    return self.respond(200, self.controller.preflight())
                if path == '/api/console':
                    return self.respond(200, {'output': self.controller.redact(self.controller.engine.logs('cs2-local-server'))})
                raise Problem('Not found', 404)
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in files:
                raise Problem('Not found', 404)
            filename, content_type = files[path]
            self.respond(200, (STATIC / filename).read_bytes(), content_type=content_type)
        except Problem as error:
            self.respond(error.status, {'error': str(error), **error.details})
        except Exception as error:
            self.respond(503, {'error': self.controller.redact(error)})

    def do_POST(self):
        try:
            self.boundary()
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise Problem('Use application/json', 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise Problem('Invalid request size')
            if not 0 < size <= 8192:
                raise Problem('Invalid request size', 413)
            try:
                data = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                raise Problem('Invalid JSON')
            if not isinstance(data, dict):
                raise Problem('Expected a JSON object')
            path = urlsplit(self.path).path
            if path in {'/api/setup', '/api/login'}:
                token, csrf = self.controller.create_account(data) if path == '/api/setup' else self.controller.login(data, self.client_address[0])
                return self.respond(200, {'csrf': csrf}, cookie=f'cs2_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
            self.controller.authorize(self.token(), self.headers.get('X-CSRF-Token', ''))
            if path == '/api/logout':
                with self.controller.lock:
                    self.controller.sessions.pop(self.token(), None)
                return self.respond(200, {'ok': True}, cookie='cs2_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if path == '/api/command':
                return self.respond(200, {'output': self.controller.command(data.get('command'))})
            operations = {'/api/install': 'install', '/api/start': 'start', '/api/stop': 'stop', '/api/restart': 'restart'}
            if path not in operations:
                raise Problem('Not found', 404)
            self.controller.start_operation(operations[path], data)
            self.respond(202, {'accepted': True})
        except Problem as error:
            self.respond(error.status, {'error': str(error), **error.details})
        except Exception as error:
            self.respond(503, {'error': self.controller.redact(error)})

def main():
    os.umask(0o077)
    Handler.controller = Controller(os.environ.get('CS2_STATE_DIR', '/state'), os.environ.get('CS2_CONFIG_DIR', '/config'))
    server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    server.daemon_threads = True
    print('CS2 Local panel listening on http://localhost:8080', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
