"""Small Docker Engine client, using only Python's standard library."""
import http.client
import io
import json
import socket
import struct
import tarfile
from pathlib import Path
from urllib.parse import urlencode

class EngineError(RuntimeError):
    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status

class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=90):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)

class DockerEngine:
    def __init__(self, socket_path='/var/run/docker.sock'):
        self.socket_path = socket_path
        self.api = None

    def request(self, method, path, data=None, raw=False, stream=None, content_type='application/json'):
        if self.api is None and path != '/version':
            version = self.request('GET', '/version')
            self.api = '/v' + version['ApiVersion']
        connection = UnixConnection(self.socket_path)
        payload = data if isinstance(data, bytes) else (json.dumps(data).encode() if data is not None else None)
        try:
            connection.request(method, (self.api or '') + path, payload, {'Content-Type': content_type})
            response = connection.getresponse()
            if response.status >= 400:
                body = response.read().decode(errors='replace')
                try:
                    body = json.loads(body).get('message', body)
                except ValueError:
                    pass
                raise EngineError(body, response.status)
            if stream:
                for line in response:
                    if line.strip():
                        stream(json.loads(line))
                return None
            body = response.read()
            if raw:
                return body
            return json.loads(body) if body else {}
        finally:
            connection.close()

    def inspect(self, name):
        try:
            value = self.request('GET', f'/containers/{name}/json')
        except EngineError as error:
            if error.status == 404:
                return None
            raise
        if (value['Config'].get('Labels') or {}).get('io.cs2-local.managed') != 'true':
            raise EngineError(f'Container name {name} belongs to another application. Rename it first.')
        return value

    def remove(self, name):
        if self.inspect(name):
            self.request('DELETE', f'/containers/{name}?force=1')

    def build(self, context, image, log):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            for path in sorted(Path(context).rglob('*')):
                relative = path.relative_to(context)
                if any(part in {'__pycache__', 'bin', 'obj', '.git'} for part in relative.parts):
                    continue
                if path.is_symlink():
                    raise EngineError('Runtime build context must not contain symbolic links')
                if path.is_file() and path.suffix != '.pyc':
                    tar.add(path, arcname=relative.as_posix())
        def on_event(event):
            if event.get('error'):
                raise EngineError(event['error'])
            if event.get('stream'):
                log(event['stream'])
            elif event.get('status'):
                log(event['status'])
        self.request('POST', '/build?' + urlencode({'t': image, 'platform': 'linux/amd64', 'rm': 'true'}),
                     archive.getvalue(), stream=on_event, content_type='application/x-tar')

    def volume(self, name):
        # Refuse to adopt an unrelated volume: it could contain someone's game/data.
        try:
            volume = self.request('GET', '/volumes/' + name)
            if (volume.get('Labels') or {}).get('io.cs2-local.managed') != 'true':
                raise EngineError(f'Volume {name} exists but is not managed by this panel.')
        except EngineError as error:
            if error.status != 404:
                raise
            self.request('POST', '/volumes/create', {'Name': name, 'Labels': {'io.cs2-local.managed': 'true'}})

    def logs(self, name, tail=200):
        info = self.inspect(name)
        if not info:
            return ''
        data = self.request('GET', f'/containers/{name}/logs?stdout=1&stderr=1&tail={tail}', raw=True)
        if info['Config'].get('Tty'):
            return data.decode(errors='replace')
        result = bytearray()
        offset = 0
        while offset + 8 <= len(data):
            size = struct.unpack('>I', data[offset + 4:offset + 8])[0]
            offset += 8
            result.extend(data[offset:offset + size])
            offset += size
        return result.decode(errors='replace')
