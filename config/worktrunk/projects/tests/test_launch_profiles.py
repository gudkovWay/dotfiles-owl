#!/usr/bin/env python3
"""Cold preparation must finish before requesting a smaller warm scope."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_ui_session import load, ROOT


class Launched(Exception):
    pass


class WarmLaunchTests(unittest.TestCase):
    def test_dev_finishes_cold_preparation_before_admitting_warm_scope(self):
        module = load('dev_profile_cold', ROOT / 'dev-session')
        events = []
        def prepare(profile, prepare=True):
            events.append(('prepared' if prepare else 'readiness', profile))
            return {'repository': 'p2p', 'dependencies': 'ready', 'generated': 'ready'}
        def launch(path, command):
            events.append(('warm-admission', command))
            raise Launched
        with patch.object(sys, 'argv', ['dev-session', '--app', 'payscrow-admin', '--port', '3000']), \
                patch.object(module.subprocess, 'check_output', return_value='/owned'), \
                patch.object(module.os, 'chdir'), \
                patch.object(Path, 'is_dir', side_effect=[False, True]), \
                patch.object(module, 'ensure_environment', side_effect=prepare), \
                patch.object(module.os, 'execv', side_effect=launch):
            with self.assertRaises(Launched):
                module.main()
        self.assertEqual(events[0], ('prepared', 'admin-ui'))
        command = events[-1][1]
        self.assertEqual(command[command.index('--need') + 1], '3G')
        self.assertIn('--elastic', command)
        self.assertEqual(command[command.index('--ceiling') + 1], '8G')
        self.assertEqual(command[command.index('--tasks') + 1], '512')
        self.assertEqual(command[command.index('--exclusive-key') + 1], '/owned')

    def test_failed_cold_preparation_never_starts_a_warm_scope(self):
        module = load('dev_profile_failure', ROOT / 'dev-session')
        with patch.object(sys, 'argv', ['dev-session', '--app', 'payscrow-admin', '--port', '3000']), \
                patch.object(module.subprocess, 'check_output', return_value='/owned'), \
                patch.object(module.os, 'chdir'), patch.object(Path, 'is_dir', side_effect=[False, True]), \
                patch.object(module, 'ensure_environment', side_effect=RuntimeError('cold failure')), \
                patch.object(module.os, 'execv') as launch:
            with self.assertRaisesRegex(RuntimeError, 'cold failure'):
                module.main()
            launch.assert_not_called()

    def test_stale_environment_is_not_prepared_inside_warm_scope(self):
        module = load('dev_profile_stale', ROOT / 'dev-session')
        calls = []
        def status(profile, prepare=True):
            calls.append(prepare)
            return {'repository': 'p2p', 'dependencies': 'ready', 'generated': 'missing-or-stale'}
        with patch.object(sys, 'argv', ['dev-session', '--inside', '--app', 'payscrow-admin', '--port', '3000']), \
                patch.object(module.subprocess, 'check_output', return_value='/owned'), \
                patch.object(module.os, 'chdir'), patch.object(Path, 'is_dir', side_effect=[False, True]), \
                patch.object(module, 'assert_guarded'), \
                patch.object(module, 'ensure_environment', side_effect=status), \
                patch.object(module, 'localhost_port', return_value=contextlib.nullcontext(3000)), \
                patch.object(module.subprocess, 'Popen') as start, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                module.main()
        self.assertEqual(calls, [False])
        start.assert_not_called()

    def test_ui_prepares_p2p_before_requesting_warm_scope(self):
        module = load('ui_profile_cold', ROOT / 'ui-session')
        events = []
        ready = {'repository': 'p2p', 'dependencies': 'ready', 'generated': 'ready'}
        def prepare(profile, prepare=True):
            events.append(('prepared' if prepare else 'readiness', profile))
            return ready
        def launch(path, command):
            events.append(('warm-admission', command))
            raise Launched
        with patch.object(sys, 'argv', ['ui-session', '--app', 'payscrow-admin']), \
                patch.object(module, 'git', return_value='/owned'), \
                patch.object(module.os, 'chdir'), \
                patch.object(module, 'ensure_environment', side_effect=prepare), \
                patch.object(module.os, 'execv', side_effect=launch):
            with self.assertRaises(Launched):
                with contextlib.ExitStack() as leases:
                    module.main(leases)
        self.assertIn(('prepared', 'admin-ui'), events[:-1])
        command = events[-1][1]
        self.assertEqual(command[command.index('--need') + 1], '3G')
        self.assertIn('--elastic', command)
        self.assertEqual(command[command.index('--ceiling') + 1], '8G')


if __name__ == '__main__':
    unittest.main(verbosity=2)
