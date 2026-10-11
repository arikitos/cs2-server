import copy
import http.client
import threading
from http.server import ThreadingHTTPServer
import io
import json
import os
import sys
import tarfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from test_installer import ControllerFixture, FakeEngine
from panel.core import Controller, Problem, config_from, atomic_json
from panel.management import steam_id
from panel.server import Handler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from assets import extract, safe_path
from prepare import prepare, repair_metamod
from mode_manager import ModeError

IDENTITY = '76561198000000001'
OTHER = '76561198000000002'
TOKEN = 'a' * 32

class ManagementTests(ControllerFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.manager = self.controller.management
        self.manager.telemetry.mkdir(parents=True, exist_ok=True)
        self.controller.config = config_from({'gslt':TOKEN})
        self.controller.write_config()
        self.controller.job.update(installed=True)

    def seen(self, identity=IDENTITY):
        atomic_json(self.manager.telemetry / 'users-seen.json', {identity: {'name':'Arik <tag>', 'first_seen':100, 'last_seen':200, 'visits':2}})
        self.manager.ingest_history()

    def test_public_only_fixed_port_and_explicit_modes(self):
        for data in [{'gslt':TOKEN,'port':27016}, {'gslt':TOKEN,'network_mode':'local'},
                     {'gslt':TOKEN,'game_mode':'warcraft'}, {'game_mode':'retakes'}, {'gslt':TOKEN,'max_players':True}]:
            with self.subTest(data=data), self.assertRaises(Problem): config_from(data)
        value = config_from({'gslt':TOKEN, 'game_mode':'deathmatch', 'join_password':''})
        self.assertEqual(value['port'],27015)
        self.assertEqual(value['network_mode'],'internet')
        self.assertEqual(value['join_password'],'')

    def test_edit_preserves_token_and_rcon_and_empty_password_opens_server(self):
        original = config_from({'gslt':TOKEN, 'join_password':'private'})
        updated = config_from({'join_password':'', 'game_mode':'retakes'}, original)
        self.assertEqual(updated['rcon_password'],original['rcon_password'])
        self.assertEqual(updated['gslt'],TOKEN)
        self.assertEqual(updated['join_password'],'')

    def test_history_persists_while_panel_is_offline_and_policy_survives_restart(self):
        self.seen()
        self.manager.user_action({'steamid':IDENTITY, 'action':'ban'})
        self.manager.user_action({'steamid':IDENTITY, 'action':'admin'})
        self.assertEqual(json.loads((self.manager.control / 'admins.json').read_text()), {})
        restarted = Controller(self.root / 'state', self.root / 'config', self.engine)
        self.assertTrue(restarted.management.users[IDENTITY]['banned'])
        restarted.management.user_action({'steamid':IDENTITY,'action':'unban'})
        admins = json.loads((self.manager.control / 'admins.json').read_text())
        self.assertEqual(admins[IDENTITY]['flags'], ['@css/root'])
        self.assertEqual(json.loads((self.manager.control / 'policy.json').read_text())['bans'], [])
        self.assertEqual(restarted.management.users[IDENTITY]['visits'],2)

    def test_only_authenticated_seen_steamids_can_be_managed(self):
        for identity in ['BOT', '76561198000000001;quit', OTHER]:
            with self.subTest(identity=identity), self.assertRaises(Problem):
                self.manager.user_action({'steamid':identity,'action':'admin'})
        self.assertEqual(self.manager.users,{})

    def test_live_snapshot_is_fresh_and_bots_have_no_identity(self):
        self.seen(); self.controller.create_server()
        self.engine.containers['cs2-local-server']['State']['Running'] = True
        live = {'updated_at':time.time(), 'players':[{'steamid':IDENTITY,'name':'Arik','bot':False}, {'steamid':None,'name':'Bot','bot':True}]}
        atomic_json(self.manager.telemetry / 'live.json',live)
        self.assertEqual(len(self.manager.players()['players']),2)
        live['updated_at'] = time.time()-30; atomic_json(self.manager.telemetry / 'live.json',live)
        self.assertEqual(self.manager.players()['players'],[])
        self.assertIsNotNone(self.manager.players()['error'])

    def test_kick_resolves_identity_and_never_reuses_a_userid(self):
        self.seen(); self.controller.create_server()
        self.engine.containers['cs2-local-server']['State']['Running'] = True
        with patch.object(self.controller,'rcon_command',return_value='CS2LOCAL_NOT_FOUND') as command:
            with self.assertRaises(Problem):self.manager.user_action({'steamid':IDENTITY,'action':'kick'})
        command.assert_called_once_with('css_local_kick '+IDENTITY)
        self.assertFalse(self.manager.users[IDENTITY]['banned'])

    def test_ban_is_durable_when_live_rcon_is_unavailable(self):
        self.seen(); self.controller.create_server()
        self.engine.containers['cs2-local-server']['State']['Running'] = True
        with patch.object(self.controller,'rcon_command',side_effect=Problem('Offline')):
            result=self.manager.user_action({'steamid':IDENTITY,'action':'ban'})
        self.assertTrue(result['pending'])
        self.assertIn(IDENTITY,json.loads((self.manager.control/'policy.json').read_text())['bans'])
        self.assertFalse(self.controller.operation_lock.locked())

    def test_lookup_uses_public_ipv4_and_never_uses_private_or_ipv6(self):
        with patch('panel.management.urllib.request.urlopen', return_value=io.BytesIO(b'8.8.8.8\n')) as lookup:
            result=self.manager.public_address();cached=self.manager.public_address()
        self.assertEqual(result['address'],'8.8.8.8:27015');self.assertEqual(result,cached);self.assertEqual(lookup.call_count,1)
        for value in [b'192.168.1.1', b'::1', b'bad']:
            with patch('panel.management.urllib.request.urlopen',return_value=io.BytesIO(value)):
                result=self.manager.public_address(force=True)
            self.assertIsNone(result['address']);self.assertIsNotNone(result['error'])

    def test_configuration_backup_restore_and_path_boundary(self):
        self.seen();self.manager.user_action({'steamid':IDENTITY,'action':'admin'})
        identifier=self.manager.backup()
        backup=self.manager.read_backup(identifier)
        self.assertEqual(backup['config']['gslt'],TOKEN)
        self.assertTrue(backup['users'][IDENTITY]['admin'])
        self.assertNotIn(TOKEN,json.dumps(self.manager.backups()))
        for value in ['../account','/tmp/anything','']:
            with self.assertRaises(Problem):self.manager.read_backup(value)
        self.assertEqual((self.controller.state_dir/'backups'/f'{identifier}.json').stat().st_mode & 0o777,0o600)

    def test_reconfigure_failure_restores_config_users_and_previous_running_mode(self):
        self.seen();self.controller.create_server()
        self.engine.containers['cs2-local-server']['State']['Running']=True
        previous=copy.deepcopy(self.controller.config)
        updated=config_from({'game_mode':'retakes','join_password':''},previous)
        with patch.object(self.controller,'launch_server',side_effect=[Problem('Retakes failed'),None]) as launch:
            with self.assertRaises(Problem): self.controller.reconfigure('configure',{'config':updated})
        self.assertEqual(self.controller.config,previous)
        self.assertEqual(launch.call_count,2)
        self.assertTrue(self.manager.backups()['backups'])

    def test_configuration_change_on_stopped_server_does_not_start_or_download(self):
        updated=config_from({'game_mode':'deathmatch'},self.controller.config)
        with patch.object(self.controller,'launch_server') as launch, patch.object(self.controller,'run_job') as job:
            self.controller.reconfigure('configure',{'config':updated})
        launch.assert_not_called();job.assert_not_called()
        self.assertEqual(self.controller.config['game_mode'],'deathmatch')
        self.assertEqual(self.controller.job['stage'],'idle')

    def test_owner_settings_password_is_separate_from_sanitized_status(self):
        self.controller.config['join_password']='private-game-password'
        self.assertEqual(self.controller.settings()['settings']['join_password'],'private-game-password')
        for output in [self.controller.status(),self.controller.settings()]:
            self.assertNotIn(TOKEN,json.dumps(output))
            self.assertNotIn(self.controller.config['rcon_password'],json.dumps(output))
        self.assertNotIn('private-game-password',json.dumps(self.controller.status()))

    def test_maintenance_stops_game_and_backs_up_before_job(self):
        self.controller.create_server();self.engine.containers['cs2-local-server']['State']['Running']=True
        with patch.object(self.controller,'run_job') as job,patch.object(self.controller,'launch_server') as launch:
            self.controller.maintenance('validate')
        self.assertTrue(any('/stop' in path for _,path,_ in self.engine.calls))
        job.assert_called_once_with('validate');launch.assert_called_once()
        self.assertEqual(self.manager.backups()['backups'][0]['reason'],'before-validate')

    def test_reject_actions_and_config_edits_during_active_job(self):
        self.seen();self.controller.operation_lock.acquire()
        try:
            for function in [lambda:self.manager.user_action({'steamid':IDENTITY,'action':'ban'}),
                             lambda:self.controller.start_operation('configure',{'server_name':'new'})]:
                with self.assertRaises(Problem):function()
        finally:self.controller.operation_lock.release()
        self.assertFalse(self.manager.users[IDENTITY]['banned'])

class RuntimeTests(ControllerFixture, unittest.TestCase):
    def test_archive_extraction_rejects_traversal_and_links(self):
        for name in ['../../escape','/absolute','addons/../../escape','a\\b']:
            with self.subTest(name=name),self.assertRaises(ValueError):safe_path(self.root,name)
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'w') as source:source.writestr('../escape','malicious')
        with self.assertRaises(ValueError):extract(archive,self.root/'output')
        archive=self.root/'bad.tar.gz'
        with tarfile.open(archive,'w:gz') as source:
            member=tarfile.TarInfo('link');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';source.addfile(member)
        with self.assertRaises(ValueError):extract(archive,self.root/'output')

    def test_metamod_repair_ignores_comments_and_is_idempotent(self):
        path=self.root/'gameinfo.gi'
        original='"GameInfo" { SearchPaths\n {\n // Game csgo/addons/metamod\n Game csgo\n }\n }'
        path.write_text(original);repair_metamod(path);first=path.read_text();repair_metamod(path)
        self.assertEqual(path.read_text(),first)
        self.assertEqual(first.count('Game\tcsgo/addons/metamod'),1)
        self.assertEqual(path.with_suffix('.gi.cs2-local-backup').read_text(),original)

    def test_modes_keep_permanent_framework_and_remove_inactive_plugins(self):
        assets=self.root/'assets';game=self.root/'game';csgo=game/'game/csgo';csgo.mkdir(parents=True)
        (csgo/'gameinfo.gi').write_text('SearchPaths {\n Game csgo\n}')
        components={'metamod':{'version':'2'},'counterstrikesharp':{'version':'1'}}
        atomic_json(assets/'components.json',components)
        frameworks=assets/'frameworks';atomic_json(frameworks/'versions.json',{'metamod':'2','counterstrikesharp':'1'})
        for relative in ['addons/metamod/base.so','addons/counterstrikesharp/bin/linuxsteamrt64/counterstrikesharp.so','addons/counterstrikesharp/plugins/LocalManager/LocalManager.dll']:
            target=frameworks/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('permanent')
        for mode in ['matchzy','deathmatch']:
            root=assets/'modes'/mode
            atomic_json(root/'mode.json',{'id':mode,'requires':{'metamod':'2','counterstrikesharp':'1'},'startup':{'game_alias':'competitive','mode_cfg':f'mode_{mode}.cfg','runtime_cfg':'panel_runtime.cfg'},'plugins':[],'configs':[]})
            (root/'cfg').mkdir();(root/'cfg'/f'mode_{mode}.cfg').write_text('exec server.cfg')
        plugin=assets/'modes/matchzy/addons/counterstrikesharp/plugins/MatchZy/MatchZy.dll';plugin.parent.mkdir(parents=True);plugin.write_text('matchzy')
        settings={'game_mode':'matchzy','max_players':10,'map':'de_dust2'}
        prepare(settings,game,assets)
        self.assertTrue((csgo/'addons/counterstrikesharp/plugins/MatchZy/MatchZy.dll').exists())
        settings['game_mode']='deathmatch';prepare(settings,game,assets)
        self.assertFalse((csgo/'addons/counterstrikesharp/plugins/MatchZy/MatchZy.dll').exists())
        self.assertTrue((csgo/'addons/counterstrikesharp/plugins/LocalManager/LocalManager.dll').exists())
        self.assertTrue((csgo/'addons/metamod/base.so').exists())
        self.assertTrue((csgo/'addons/counterstrikesharp/configs/admins.json').is_symlink())

class ManagementHttpTests(ControllerFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        handler=type('ManagementHandler',(Handler,),{'controller':self.controller})
        self.http=ThreadingHTTPServer(('127.0.0.1',0),handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();super().tearDown()

    def request_http(self, method, path, data=None, headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_address[1])
        connection.request(method,path,json.dumps(data) if data is not None else None,{'Content-Type':'application/json',**(headers or {})})
        response=connection.getresponse();result=(response.status,dict(response.getheaders()),json.loads(response.read()))
        connection.close();return result

    def test_new_endpoints_require_authentication_and_mutations_require_csrf(self):
        for route in ['settings','address','players','users','modes','metrics','backups','audit']:
            status,_,_=self.request_http('GET','/api/'+route);self.assertEqual(status,401)
        status,headers,body=self.request_http('POST','/api/setup',{'setup_token':self.controller.bootstrap,'username':'arik','password':'private-password-123'})
        cookie=headers['Set-Cookie'].split(';')[0]
        for route in ['users/action','configure','restore','repair','validate','backup','address/refresh','mode/action']:
            status,_,_=self.request_http('POST','/api/'+route,{}, {'Cookie':cookie});self.assertEqual(status,403)
        status,_,response=self.request_http('GET','/api/modes',headers={'Cookie':cookie})
        self.assertEqual(status,200)
        self.assertEqual([row['id'] for row in response['modes']],['matchzy','retakes','deathmatch'])

if __name__ == '__main__':unittest.main()
