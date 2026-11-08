#!/usr/bin/env python3
"""Native unittest regressions for the reviewed dev preparation boundary."""
from contextlib import ExitStack
import importlib
import json
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.dev = importlib.import_module('dev_support')

    def test_ready_environment_is_reused_without_install(self):
        ready = {'dependencies': 'ready', 'generated': 'ready'}
        with patch.object(self.dev, 'status', return_value=ready), patch.object(self.dev.subprocess, 'run') as run:
            self.assertEqual(self.dev.ensure_environment('admin-ui'), ready)
            run.assert_not_called()

    def test_missing_environment_is_prepared_and_rechecked(self):
        states = [{'dependencies': 'missing', 'generated': 'missing'},
                  {'dependencies': 'ready', 'generated': 'ready'}]
        with patch.object(self.dev, 'status', side_effect=states) as status, patch.object(self.dev.subprocess, 'run') as run:
            result = self.dev.ensure_environment('merchant-ui')
            self.assertEqual(result, states[1])
            self.assertEqual(status.call_count, 2)
            self.assertEqual(run.call_args.args[0], [str(self.dev.ENVIRONMENT), '--profile', 'merchant-ui', '--install', '--prepare'])
            self.assertTrue(run.call_args.kwargs['check'])

    def test_prepare_failure_never_becomes_ready(self):
        with patch.object(self.dev, 'status', return_value={'dependencies': 'missing', 'generated': 'missing'}) as status, patch.object(self.dev.subprocess, 'run', side_effect=subprocess.CalledProcessError(137, 'prepare')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.dev.ensure_environment('admin-ui')
            self.assertEqual(status.call_count, 1)

    def test_successful_prepare_with_missing_outputs_refuses_launch(self):
        with patch.object(self.dev, 'status', return_value={'dependencies': 'ready', 'generated': 'missing'}), patch.object(self.dev.subprocess, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                self.dev.ensure_environment('admin-ui')

    def test_dry_readiness_never_prepares(self):
        missing = {'dependencies': 'missing', 'generated': 'missing'}
        with patch.object(self.dev, 'status', return_value=missing), patch.object(self.dev.subprocess, 'run') as run:
            self.assertEqual(self.dev.ensure_environment('provider-ui', prepare=False), missing)
            run.assert_not_called()

    def test_supported_apps_map_to_exact_reviewed_profiles(self):
        for role in ('admin', 'merchant', 'provider'):
            self.assertEqual(self.dev.profile_for('payscrow-' + role), role + '-ui')
        for app in ('../payscrow-admin', 'lucky-merchant', 'ock-admin', 'payscrow-form'):
            with self.assertRaisesRegex(RuntimeError, 'reviewed'):
                self.dev.profile_for(app)

    def test_status_decodes_only_readonly_profile_output(self):
        value = {'dependencies': 'missing', 'generated': 'missing'}
        with patch.object(self.dev.subprocess, 'check_output', return_value=json.dumps(value)) as call:
            self.assertEqual(self.dev.status('admin-ui'), value)
            self.assertNotIn('--install', call.call_args.args[0])


class LocalhostPortTests(unittest.TestCase):
    def setUp(self):
        self.dev = importlib.import_module('dev_support')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)

    def lease(self, preferred=3000, repository='p2p'):
        return self.dev.localhost_port(repository, preferred, runtime=self.runtime)

    def test_first_free_allowed_port_is_selected(self):
        with patch.object(self.dev, 'port_available', side_effect=lambda port: port != 3000):
            with self.lease() as port:
                self.assertEqual(port, 3001)

    def test_explicit_allowed_preference_is_honored(self):
        with patch.object(self.dev, 'port_available', return_value=True):
            with self.lease(3002) as port:
                self.assertEqual(port, 3002)

    def test_three_launchers_reserve_distinct_ports_and_fourth_is_deferred(self):
        with patch.object(self.dev, 'port_available', return_value=True), ExitStack() as leases:
            ports = [leases.enter_context(self.lease()) for _ in range(3)]
            self.assertEqual(ports, [3000, 3001, 3002])
            with self.assertRaisesRegex(self.dev.Busy, '3000, 3001, 3002'):
                leases.enter_context(self.lease())

    def test_failed_start_releases_its_port_without_removing_lock_file(self):
        with patch.object(self.dev, 'port_available', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                with self.lease():
                    raise RuntimeError('startup failed')
            lock = self.runtime / 'omp-p2p-localhost/3000.lock'
            inode = lock.stat().st_ino
            with self.lease() as port:
                self.assertEqual(port, 3000)
                self.assertEqual(lock.stat().st_ino, inode)

    def test_all_foreign_listeners_defer_without_random_port(self):
        with patch.object(self.dev, 'port_available', return_value=False) as available:
            with self.assertRaises(self.dev.Busy):
                with self.lease():
                    self.fail('all ports are occupied')
            self.assertEqual([call.args[0] for call in available.call_args_list],
                             [3000, 3001, 3002])

    def test_unapproved_explicit_port_is_rejected_before_probing(self):
        with patch.object(self.dev, 'port_available') as available:
            with self.assertRaisesRegex(RuntimeError, '3000, 3001, 3002'):
                with self.lease(56777):
                    self.fail('unapproved origin')
            available.assert_not_called()

    def test_other_repository_keeps_its_requested_free_port_without_p2p_lock(self):
        with patch.object(self.dev, 'port_available', return_value=True):
            with self.lease(17960, 'ecom') as port:
                self.assertEqual(port, 17960)
            self.assertFalse((self.runtime / 'omp-p2p-localhost').exists())

    def test_real_listener_is_not_available(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.assertFalse(self.dev.port_available(listener.getsockname()[1]))

    def test_p2p_native_command_cannot_take_over_or_choose_another_port(self):
        command = self.dev.nuxt_dev_command('payscrow-admin', 3001, 'p2p')
        self.assertEqual(command, [
            'npm', 'run', 'dev', '-w', 'payscrow-admin', '--',
            '--host', '127.0.0.1', '--port', '3001', '--strictPort', '--no-takeover',
        ])
        other = self.dev.nuxt_dev_command('payscrow-admin', 17960, 'ecom')
        self.assertNotIn('--strictPort', other)
        self.assertNotIn('--no-takeover', other)


if __name__ == '__main__':
    unittest.main()
