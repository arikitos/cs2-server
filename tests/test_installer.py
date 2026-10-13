import http.client
import json
import socket
import struct
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from panel.core import Controller, Problem, config_from as real_config_from, installed_build, public_build, rcon, verify_password

def config_from(data):
    return real_config_from({"gslt":"a" * 32, **data})
from panel.docker_engine import DockerEngine, EngineError
from panel.server import Handler

def metadata(build):
    return f'''Steam Console Client
    "730" {{ "depots" {{ "branches" {{ "beta" {{ "buildid" "999999" }}
    "public" {{ "buildid" "{build}" }} }} }} }}'''

class FakeEngine:
    def __init__(self):
        self.calls = []
        self.containers = {}
        self.built = False
        self.image_present = False

    def request(self, method, path, data=None, **kwargs):
        self.calls.append((method, path, data))
        if path == '/info':
            return {'Architecture': 'x86_64', 'OSType': 'linux', 'MemTotal': 8 * 2**30}
        if path.startswith('/images/') and not self.image_present:
            raise EngineError('Image not found', 404)
        if '/containers/create' in path:
            name = path.split('name=')[1]
            self.containers[name] = {'Config': data, 'State': {'Running': False, 'ExitCode': 0}}
        elif '/start' in path:
            name = path.split('/')[2]
            self.containers[name]['State'].update(Running=True, Health={'Status': 'healthy'})
        elif '/stop' in path:
            name = path.split('/')[2]
            self.containers[name]['State']['Running'] = False
        return {}

    def inspect(self, name):
        return self.containers.get(name)

    def remove(self, name):
        self.containers.pop(name, None)

    def volume(self, name):
        self.calls.append(('volume', name, None))

    def build(self, context, image, log):
        self.built = True
        self.image_present = True
        log('Runtime built')

    def logs(self, name, tail=200):
        return 'simulated console'

class ControllerFixture:
    def setUp(self):
        self.chown = patch('panel.core.os.chown').start()
        patch('panel.core.Controller.verify_plugins').start()
        self.addCleanup(patch.stopall)
        self.print_patch = patch('builtins.print').start()
        self.temporary = tempfile.TemporaryDirectory(prefix=".cs2-test-")
        self.root = Path(self.temporary.name)
        self.engine = FakeEngine()
        self.controller = Controller(self.root / 'state', self.root / 'config', self.engine)

    def tearDown(self):
        self.temporary.cleanup()

    def configured(self, build='100'):
        self.engine.image_present = True
        self.controller.config = config_from({})
        self.controller.write_config()
        self.controller.job.update(installed=True, installed_build=build)

    def worker(self, operation, data=None):
        self.controller.operation_lock.acquire()
        self.controller.worker(operation, data or {})

class ControllerTests(ControllerFixture, unittest.TestCase):
    def test_credentials_hashed_setup_single_use_and_csrf(self):
        password = 'a long private password'
        token, csrf = self.controller.create_account({'setup_token': self.controller.bootstrap,
                                                    'username': 'arik', 'password': password})
        self.assertTrue(verify_password(password, self.controller.account['password_hash']))
        self.assertNotIn(password, (self.root / 'state/account.json').read_text())
        self.assertFalse((self.root / 'state/bootstrap.json').exists())
        self.controller.authorize(token, csrf)
        with self.assertRaises(Problem):
            self.controller.authorize(token, 'wrong')
        with self.assertRaises(Problem):
            self.controller.create_account({})

    def test_install_build_download_persistence_and_readiness(self):
        self.controller.config = config_from({'server_name': 'Arik CS2'})
        empty = {'manifest': '', 'exists': False, 'missing_files': ['game/cs2.sh'], 'free_bytes': 100 * 2**30}
        installed = {'manifest': '"buildid" "100"', 'exists': True, 'missing_files': [], 'free_bytes': 10 * 2**30}
        with patch.object(self.controller, 'manifest', side_effect=[empty, installed]), patch.object(self.controller, 'run_job', side_effect=['', metadata('100')]) as run:
            self.worker('install')
        self.assertTrue(self.engine.built)
        self.assertEqual([call.args[0] for call in run.call_args_list], ['install', 'check'])
        self.assertEqual(self.controller.job['stage'], 'ready')
        self.assertTrue(self.controller.job['installed'])
        create = next(data for method, path, data in self.engine.calls if path.startswith('/containers/create'))
        self.assertEqual(create['HostConfig']['Mounts'][0]['Source'], 'cs2-local-game')
        self.assertEqual(create['HostConfig']['RestartPolicy']['Name'], 'unless-stopped')
        self.assertEqual(create['HostConfig']['PortBindings']['27015/udp'][0]['HostIp'], '0.0.0.0')
        self.assertNotIn('rcon_password', json.dumps(create))

    def test_update_requires_matching_approval_and_rechecks_on_start(self):
        self.configured()
        with patch.object(self.controller, 'manifest', return_value={'manifest': '"buildid" "100"'}), patch.object(self.controller, 'run_job', return_value=metadata('200')) as run:
            self.worker('start', {'approved_build': '199'})
        self.assertEqual(self.controller.job['stage'], 'update_available')
        self.assertEqual(self.controller.job['available_build'], '200')
        self.assertNotIn('cs2-local-server', self.engine.containers)
        self.assertEqual([call.args[0] for call in run.call_args_list], ['check'])
        with patch.object(self.controller, 'manifest', side_effect=[{'manifest':'"buildid" "100"'}, {'manifest':'"buildid" "200"'}]), patch.object(self.controller, 'run_job', side_effect=[metadata('200'), 'updated']) as run:
            self.worker('start', {'approved_build': '200'})
        self.assertEqual(self.controller.job['stage'], 'ready')
        self.assertEqual(self.controller.job['installed_build'], '200')
        self.assertEqual([call.args[0] for call in run.call_args_list], ['check', 'update'])
        self.assertFalse(self.engine.built)

    def test_same_build_starts_without_download(self):
        self.configured()
        with patch.object(self.controller, 'manifest', return_value={'manifest':'"buildid" "100"'}), patch.object(self.controller, 'run_job', return_value=metadata('100')) as run:
            self.worker('start')
        self.assertEqual(self.controller.job['stage'], 'ready')
        run.assert_called_once_with('check')
        self.assertFalse(self.engine.built)

    def test_failed_check_never_starts_or_updates(self):
        self.configured()
        with patch.object(self.controller, 'manifest', return_value={'manifest':'"buildid" "100"'}), patch.object(self.controller, 'run_job', return_value='Steam offline'):
            self.worker('start')
        self.assertEqual(self.controller.job['stage'], 'failed')
        self.assertNotIn('cs2-local-server', self.engine.containers)

    def test_failed_install_can_retry_and_reuses_volume(self):
        self.controller.config = config_from({})
        with patch.object(self.controller, 'manifest', return_value={'manifest':'', 'exists':False, 'missing_files':['game/cs2.sh'], 'free_bytes':100 * 2**30}), patch.object(self.controller, 'run_job', side_effect=Problem('Network unavailable')):
            self.worker('install')
        self.assertEqual(self.controller.job['stage'], 'failed')
        self.assertFalse(self.controller.job['installed'])
        self.assertFalse(self.controller.operation_lock.locked())
        self.assertEqual(self.engine.calls[0][1], 'cs2-local-game')

    def test_resumes_still_running_install_before_inspection(self):
        self.controller.config = config_from({})
        self.engine.image_present = True
        self.engine.containers['cs2-local-job'] = {'Config':{'Labels':{'io.cs2-local.operation':'install', 'io.cs2-local.runtime':'3'}}, 'State':{'Running':True}}
        with patch.object(self.controller, 'manifest', return_value={'manifest':'"buildid" "100"', 'missing_files':[]}), patch.object(self.controller, 'run_job', side_effect=['download complete', metadata('100')]) as run:
            self.worker('install')
        self.assertEqual([call.args[0] for call in run.call_args_list], ['install', 'check'])
        self.assertFalse(self.engine.built)
        self.assertEqual(self.controller.job['stage'], 'ready')

    def test_insufficient_space_fails_before_download(self):
        self.controller.config = config_from({})
        with patch.object(self.controller, 'manifest', return_value={'manifest':'', 'exists':False, 'missing_files':['game/cs2.sh'], 'free_bytes':10 * 2**30}), patch.object(self.controller, 'run_job') as run:
            self.worker('install')
        run.assert_not_called()
        self.assertEqual(self.controller.job['stage'], 'failed')
        self.assertIn('80 GiB', self.controller.job['error'])

    def test_internet_udp_open_but_rcon_loopback_only(self):
        self.controller.config = config_from({'network_mode':'internet','gslt':'a' * 32,'port':27015})
        self.controller.create_server()
        creation = self.engine.containers['cs2-local-server']['Config']
        ports = creation['HostConfig']['PortBindings']
        self.assertEqual(ports['27015/udp'][0]['HostIp'], '0.0.0.0')
        self.assertEqual(ports['27016/tcp'][0]['HostIp'], '127.0.0.1')

    def test_unsupported_engine_never_creates_installation(self):
        with patch.object(self.controller, 'preflight', return_value={'supported':False}):
            with self.assertRaises(Problem):
                self.controller.start_operation('install', {})
        self.assertIsNone(self.controller.config)
        self.assertFalse(self.controller.operation_lock.locked())

    def test_single_operation_and_restart_releases_lock(self):
        self.configured()
        self.controller.operation_lock.acquire()
        with self.assertRaises(Problem) as error:
            self.controller.start_operation('start')
        self.assertEqual(error.exception.status, 409)
        self.controller.operation_lock.release()
        with patch.object(self.controller, 'manifest', return_value={'manifest':'"buildid" "100"'}), patch.object(self.controller, 'run_job', return_value=metadata('200')):
            self.worker('restart')
        self.assertEqual(self.controller.job['stage'], 'update_available')
        self.assertFalse(self.controller.operation_lock.locked())

    def test_no_secrets_in_status_or_logs(self):
        self.controller.config = config_from({'network_mode':'internet','gslt':'a' * 32,'join_password':'super-secret'})
        self.controller.log('token ' + self.controller.config['gslt'] + ' password super-secret')
        output = json.dumps(self.controller.status())
        for key in ['gslt', 'join_password', 'rcon_password']:
            self.assertNotIn(self.controller.config[key], output)

    def test_validation_blocks_config_injection_and_requires_gslt(self):
        for data in [{'server_name':'bad\nexec evil'}, {'network_mode':'lan'}, {'gslt':''}, {'port':'bad'}, {'port':27016}, {'map':'+quit'}, {'gslt':'not-a-token'}]:
            with self.subTest(data=data), self.assertRaises(Problem):
                config_from(data)

    def test_interrupted_install_is_retryable_after_panel_restart(self):
        self.controller.set_stage('installing')
        restarted = Controller(self.root / 'state', self.root / 'config', self.engine)
        self.assertEqual(restarted.job['stage'], 'failed')
        self.assertIn('Retry', restarted.job['error'])

class MetadataTests(unittest.TestCase):
    def test_only_public_branch_build_is_selected(self):
        self.assertEqual(public_build(metadata('123')), '123')
        self.assertIsNone(public_build('offline'))
        self.assertEqual(installed_build('"buildid"\t"123"'), '123')

class EngineSafetyTests(unittest.TestCase):
    def test_cannot_adopt_or_remove_someone_elses_container(self):
        engine = DockerEngine()
        with patch.object(engine, 'request', return_value={'Config':{'Labels':None}}) as request:
            with self.assertRaises(EngineError):
                engine.remove('cs2-local-server')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], 'GET')

    def test_cannot_adopt_unlabelled_existing_game_volume(self):
        engine = DockerEngine()
        with patch.object(engine, 'request', return_value={'Labels':None}) as request:
            with self.assertRaises(EngineError):
                engine.volume('cs2-local-game')
        self.assertEqual(request.call_count, 1)

    def test_docker_build_error_is_not_reported_as_success(self):
        engine = DockerEngine()
        def request(method, path, data, **options):
            options['stream']({'error':'Failed to download runtime image'})
        with patch.object(engine, 'request', side_effect=request):
            with self.assertRaises(EngineError):
                engine.build(Path(__file__).parent.parent / 'runtime', 'test-runtime', lambda line: None)

class HttpTests(ControllerFixture, unittest.TestCase):
    # Keep this suite focused on boundaries; inherit fixtures, not controller tests.
    def setUp(self):
        super().setUp()
        handler = type('TestHandler', (Handler,), {'controller':self.controller})
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.http.server_address[1]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        super().tearDown()

    def request_http(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Content-Type':'application/json', **(headers or {})}
        conn.request(method, path, json.dumps(data) if data is not None else None, headers)
        response = conn.getresponse()
        body = response.read()
        result = response.status, dict(response.getheaders()), json.loads(body)
        conn.close()
        return result

    def test_http_auth_csrf_origin_host_and_secret_boundaries(self):
        status, _, _ = self.request_http('GET', '/api/status')
        self.assertEqual(status, 401)

        status, headers, body = self.request_http('POST', '/api/setup', {'setup_token':self.controller.bootstrap, 'username':'arik','password':'private-password-123'})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        status, _, _ = self.request_http('POST','/api/stop',{}, {'Cookie':cookie})
        self.assertEqual(status, 403)
        status, _, _ = self.request_http('GET','/api/status',headers={'Cookie':cookie,'Origin':'https://evil.example'})
        self.assertEqual(status, 403)
        status, _, _ = self.request_http('GET','/api/session',headers={'Host':'evil.example'})
        self.assertEqual(status, 403)
        status, _, _ = self.request_http('GET','/api/status',headers={'Cookie':cookie})
        self.assertEqual(status, 200)
        status, _, _ = self.request_http('POST','/api/logout',{}, {'Cookie':cookie,'X-CSRF-Token':body['csrf']})
        self.assertEqual(status, 200)
        status, _, _ = self.request_http('GET','/api/status',headers={'Cookie':cookie})
        self.assertEqual(status, 401)

    def test_install_requires_initial_panel_account_csrf_and_steam_token(self):
        status, _, _ = self.request_http('POST', '/api/install', {'gslt': 'a' * 32})
        self.assertEqual(status, 401)
        status, headers, body = self.request_http('POST', '/api/setup', {'setup_token': self.controller.bootstrap,
                                                                      'username': 'first-owner', 'password': 'private-password-123'})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        status, _, _ = self.request_http('POST', '/api/install', {'gslt': 'a' * 32}, {'Cookie': cookie})
        self.assertEqual(status, 403)
        status, _, response = self.request_http('POST', '/api/install', {}, {'Cookie': cookie, 'X-CSRF-Token': body['csrf']})
        self.assertEqual(status, 400)
        self.assertIn('Game Server Login Token', response['error'])
        self.assertIsNone(self.controller.config)
        self.assertEqual(self.engine.containers, {})

class RconTests(unittest.TestCase):
    def test_authentication_and_multipart_command_response(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen()
        def send(sock, request_id, kind, text):
            packet = struct.pack('<ii',request_id,kind) + text.encode() + b'\0\0'
            sock.sendall(struct.pack('<i',len(packet)) + packet)
        def receive(sock):
            data = b''
            while len(data) < 4:
                data += sock.recv(4-len(data))
            length = struct.unpack('<i',data)[0]
            body = b''
            while len(body) < length:
                body += sock.recv(length-len(body))
            return body[8:-2].decode()
        def respond():
            with server.accept()[0] as sock:
                assert receive(sock) == 'private-rcon'
                send(sock,1,0,''); send(sock,1,2,'')
                assert receive(sock) == 'status'
                receive(sock)
                send(sock,2,0,'first packet'); send(sock,2,0,'second packet'); send(sock,3,0,'')
        thread = threading.Thread(target=respond)
        thread.start()
        try:
            result = rcon('127.0.0.1',server.getsockname()[1],'private-rcon','status')
            self.assertEqual(result,'first packet\nsecond packet')
        finally:
            thread.join(5)
            server.close()

if __name__ == '__main__':
    unittest.main()
