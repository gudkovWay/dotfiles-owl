#!/usr/bin/env python3
"""Native unittest regressions for the reviewed dev preparation boundary."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
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


if __name__ == '__main__':
    unittest.main()
