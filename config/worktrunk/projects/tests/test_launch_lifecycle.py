#!/usr/bin/env python3
"""Finite native launcher scenarios, with no Nuxt, personal browser or backend."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_support as dev
from test_ui_session import load, ROOT


class LauncherLifecycleTests(unittest.TestCase):
    def test_successful_readiness_emits_selected_origin_identity_and_expiry(self):
        process = unittest.mock.Mock(pid=123)
        process.poll.return_value = None
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(dev, 'owned_listener', return_value=True), \
                patch.object(dev, 'loopback_response', return_value=response), \
                patch.object(dev.subprocess, 'check_output', side_effect=['DEV-capitalism-slave-example\n', 'a' * 40]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            record = dev.wait_ready(process, 3001, time.monotonic() + 30, Path('/owned'), 'payscrow-admin', 'preview')
        self.assertEqual(record['url'], 'http://localhost:3001')
        self.assertEqual(record['root'], '/owned')
        self.assertEqual(record['server_pid'], 123)
        self.assertEqual(record['head'], 'a' * 40)
        self.assertEqual(record['mode'], 'preview')
        self.assertGreater(record['expires_at'], time.time())
        self.assertEqual(json.loads(output.getvalue())['event'], 'ready')

    def test_manual_preview_has_no_expiry_but_retains_readiness_and_identity(self):
        process = unittest.mock.Mock(pid=123)
        process.poll.return_value = None
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(dev, 'owned_listener', return_value=True), \
                patch.object(dev, 'loopback_response', return_value=response), \
                patch.object(dev.subprocess, 'check_output', side_effect=['DEV-capitalism-slave-example\n', 'a' * 40]), \
                contextlib.redirect_stdout(io.StringIO()):
            record = dev.wait_ready(process, 3001, None, Path('/owned'), 'payscrow-admin', 'preview')
        self.assertIsNone(record['expires_at'])
        self.assertIsNone(record['remaining_seconds'])
        self.assertEqual(record['server_pid'], 123)

    def test_manual_preview_waits_for_native_exit_without_timeout(self):
        process = unittest.mock.Mock()
        process.wait.return_value = 75
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dev.wait_finite(process, None), 75)
        process.wait.assert_called_once_with()

    def test_child_failure_preserves_deferred_exit_instead_of_success(self):
        module = load('dev_session_lifecycle', ROOT / 'dev-session')
        root = Path('/owned')
        process = unittest.mock.Mock(pid=123)
        process.wait.return_value = 75
        with patch.object(sys, 'argv', ['dev-session', '--inside', '--app', 'payscrow-admin', '--port', '3000']), \
                patch.object(module.subprocess, 'check_output', return_value=str(root)), \
                patch.object(module.os, 'chdir'), patch.object(Path, 'is_dir', side_effect=[False, True]), \
                patch.object(module, 'assert_guarded'), \
                patch.object(module, 'localhost_port', return_value=contextlib.nullcontext(3001)), \
                patch.object(module, 'ensure_environment', return_value={'dependencies': 'ready', 'generated': 'ready'}), \
                patch.object(module.subprocess, 'Popen', return_value=process), \
                patch.object(module, 'wait_ready'), patch.object(module, 'stop') as stop:
            self.assertEqual(module.main(), 75)
        stop.assert_called_once_with(process)

    def test_expired_finite_preview_has_explicit_reason(self):
        process = unittest.mock.Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('owned-server', 1)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(dev.wait_finite(process, time.monotonic() + 1), 0)
        self.assertIn('finite-session-complete', output.getvalue())

    def test_exited_server_is_not_reported_ready(self):
        process = unittest.mock.Mock()
        process.poll.return_value = 75
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            dev.wait_ready(process, 3002, time.monotonic() + 10, Path('/owned'), 'payscrow-admin', 'preview')
        self.assertEqual(caught.exception.returncode, 75)

    def test_nuxt_thread_defaults_preserve_explicit_owner_settings(self):
        original = {'RAYON_NUM_THREADS': '2', 'NODE_OPTIONS': '--trace-warnings'}
        result = dev.nuxt_environment(original, 'p2p')
        self.assertEqual(result['RAYON_NUM_THREADS'], '2')
        self.assertEqual(result['UV_THREADPOOL_SIZE'], '4')
        self.assertEqual(result['GOMAXPROCS'], '4')
        self.assertEqual(result['TOKIO_WORKER_THREADS'], '4')
        self.assertEqual(result['NODE_OPTIONS'], '--trace-warnings')
        self.assertEqual(original, {'RAYON_NUM_THREADS': '2', 'NODE_OPTIONS': '--trace-warnings'})
        self.assertEqual(dev.nuxt_environment(original, 'ecom'), original)

    def test_native_owned_child_group_is_stopped_and_reaped(self):
        module = load('dev_session_stop', ROOT / 'dev-session')
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        module.stop(process)
        self.assertIsNotNone(process.poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)


if __name__ == '__main__':
    unittest.main()
