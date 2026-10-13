import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from panel.core import Problem
from test_installer import ControllerFixture, config_from, metadata

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from inspection import inspect_installation, REQUIRED_FILES
from install import run, steamcmd_arguments


def volume(build='100', missing=(), exists=True, free=10 * 2**30):
    return {'path': '/game', 'exists': exists, 'manifest': f'"buildid" "{build}"' if build else '',
            'missing_files': list(missing), 'free_bytes': free}


class InstallationTests(ControllerFixture, unittest.TestCase):
    def test_reinstall_preserves_panel_credentials_and_settings_and_stops_before_validation(self):
        self.configured()
        self.controller.create_account({'setup_token': self.controller.bootstrap,
                                        'username': 'arik', 'password': 'private-password-123'})
        account = (self.controller.state_dir / 'account.json').read_bytes()
        config = dict(self.controller.config)
        self.controller.create_server()
        self.engine.containers['cs2-local-server']['State']['Running'] = True

        def job(operation):
            self.assertFalse(self.engine.containers['cs2-local-server']['State']['Running'])
            return metadata('100') if operation == 'check' else ''

        with patch.object(self.controller, 'manifest', return_value=volume()), patch.object(self.controller, 'run_job', side_effect=job) as jobs:
            self.worker('install')
        self.assertEqual([call.args[0] for call in jobs.call_args_list], ['install', 'check'])
        self.assertEqual(self.controller.config, config)
        self.assertEqual((self.controller.state_dir / 'account.json').read_bytes(), account)
        self.assertTrue(self.controller.management.backups())
        self.assertEqual(self.controller.job['verification']['build'], '100')
        self.assertEqual(self.controller.job['stage'], 'ready')
        self.assertFalse(self.engine.built)
        self.assertTrue(any('Existing server files' in line for line in self.controller.logs))

    def test_repeated_install_endpoint_accepts_saved_configuration(self):
        self.configured()
        config = dict(self.controller.config)
        with patch('panel.core.threading.Thread') as thread:
            self.controller.start_operation('install', {})
            self.assertEqual(thread.call_args.kwargs['args'], ('install', {'config': config}))
            self.assertTrue(self.controller.operation_lock.locked())
            self.controller.operation_lock.release()

    def test_missing_steam_data_is_rejected_before_any_installation(self):
        with self.assertRaises(Problem):
            self.controller.start_operation('install', {'server_name': 'Arik'})
        self.assertEqual(self.engine.containers, {})
        self.assertFalse(self.controller.operation_lock.locked())

    def test_partial_directory_without_manifest_is_repaired_without_requiring_fresh_install_space(self):
        self.controller.config = config_from({})
        with patch.object(self.controller, 'manifest', side_effect=[volume('', REQUIRED_FILES), volume('200')]), patch.object(self.controller, 'run_job', side_effect=['repaired', metadata('200')]):
            self.worker('install')
        self.assertEqual(self.controller.job['stage'], 'ready')
        self.assertEqual(self.controller.job['installed_build'], '200')

    def test_stale_existing_files_are_updated_before_starting(self):
        self.configured()
        with patch.object(self.controller, 'manifest', side_effect=[volume('100'), volume('200')]), patch.object(self.controller, 'run_job', side_effect=['updated', metadata('200')]):
            self.worker('install')
        self.assertEqual(self.controller.job['verification']['build'], '200')
        self.assertEqual(self.controller.job['stage'], 'ready')

    def test_failed_or_incomplete_validation_never_starts_the_server(self):
        for result in (Problem('Steam verification failed'), 'success but files still missing'):
            with self.subTest(result=str(result)):
                self.controller.config = config_from({})
                with patch.object(self.controller, 'manifest', side_effect=[volume('100'), volume('100', ['game/cs2.sh'])]), patch.object(self.controller, 'run_job', side_effect=result if isinstance(result, Exception) else None, return_value=result):
                    self.worker('install')
                self.assertEqual(self.controller.job['stage'], 'failed')
                self.assertFalse(self.controller.job['installed'])
                self.assertNotIn('cs2-local-server', self.engine.containers)

    def test_unverifiable_or_newer_public_build_prevents_start(self):
        for output in ('Steam is offline', metadata('200')):
            with self.subTest(output=output):
                self.controller.config = config_from({})
                with patch.object(self.controller, 'manifest', return_value=volume('100')), patch.object(self.controller, 'run_job', side_effect=['validated', output]):
                    self.worker('install')
                self.assertEqual(self.controller.job['stage'], 'failed')
                self.assertFalse(self.controller.job['installed'])
                self.assertNotIn('cs2-local-server', self.engine.containers)

    def test_legacy_running_installer_is_followed_by_current_file_validation(self):
        self.controller.config = config_from({})
        self.engine.image_present = True
        self.engine.containers['cs2-local-job'] = {'Config': {'Labels': {'io.cs2-local.operation': 'install', 'io.cs2-local.runtime': '2'}}, 'State': {'Running': True}}
        with patch.object(self.controller, 'manifest', return_value=volume('100')), patch.object(self.controller, 'run_job', side_effect=['old install', 'new validation', metadata('100')]) as jobs:
            self.worker('install')
        self.assertEqual([call.args[0] for call in jobs.call_args_list], ['install', 'install', 'check'])
        self.assertEqual(self.controller.job['stage'], 'ready')


class RuntimeInstallationTests(ControllerFixture, unittest.TestCase):
    def test_inspection_distinguishes_empty_partial_complete_and_damaged_installations(self):
        empty = inspect_installation(self.root)
        self.assertFalse(empty['exists'])
        self.assertEqual(empty['missing_files'], list(REQUIRED_FILES))
        (self.root / 'game').mkdir()
        self.assertTrue(inspect_installation(self.root)['exists'])
        for relative in REQUIRED_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('"buildid" "100"' if relative.endswith('.acf') else 'game data')
            path.chmod(0o755)
        self.assertEqual(inspect_installation(self.root)['missing_files'], [])
        (self.root / 'game/cs2.sh').chmod(0o644)
        (self.root / 'game/csgo/gameinfo.gi').write_text('')
        self.assertEqual(inspect_installation(self.root)['missing_files'], ['game/cs2.sh', 'game/csgo/gameinfo.gi'])

    def test_install_and_validate_check_contents_and_update_retains_normal_download_behavior(self):
        for operation in ('install', 'validate', 'update'):
            arguments = steamcmd_arguments(operation)
            self.assertEqual('validate' in arguments, operation != 'update')
            self.assertEqual(arguments[arguments.index('+login') + 1], 'anonymous')
            self.assertEqual(arguments[arguments.index('+app_update') + 1], '730')
        with self.assertRaises(ValueError):
            steamcmd_arguments('erase')

    def test_steam_creates_missing_directory_and_preserves_existing_files(self):
        target = self.root / 'server'
        process = Mock(stdout=io.StringIO("Success! App '730' fully installed.\n"))
        process.wait.return_value = 0
        with patch('install.subprocess.Popen', return_value=process) as popen:
            self.assertEqual(run('install', target), 0)
            self.assertTrue(target.is_dir())
            self.assertIn('validate', popen.call_args.args[0])
        saved = target / 'custom.cfg'
        saved.write_text('keep this setting')
        process.stdout = io.StringIO("Success! App '730' already up to date.\n")
        with patch('install.subprocess.Popen', return_value=process):
            self.assertEqual(run('install', target), 0)
        self.assertEqual(saved.read_text(), 'keep this setting')

    def test_zero_exit_without_explicit_steam_success_is_not_accepted(self):
        process = Mock(stdout=io.StringIO('ERROR! Failed to install app 730.\n'))
        process.wait.return_value = 0
        with patch('install.subprocess.Popen', return_value=process):
            self.assertEqual(run('install', self.root), 1)
