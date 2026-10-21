#!/usr/bin/env python3
"""UI launcher contracts; standard-library unittest, no browser or backend."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ui = load('ui_session', ROOT / 'ui-session')
environment = load('project_environment', ROOT / 'project-environment')


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / '.secrets').mkdir(mode=0o700)
        self.path = self.home / '.secrets/payscrow-admin'
        self.path.touch(mode=0o600)

    def test_empty_file_is_explicit_not_missing_access(self):
        result = ui.authentication('p2p', 'payscrow-admin', self.home)
        self.assertEqual(result['state'], 'empty')
        self.assertEqual(result['credentials_file'], str(self.path))

    def test_two_lines_supply_flow_without_disclosing_values(self):
        self.path.write_text('test-user\n private-password \n')
        result = ui.authentication('p2p', 'payscrow-admin', self.home)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['username_selector'], '#username')
        self.assertEqual(result['password_selector'], '#password')
        self.assertNotIn('test-user', json.dumps(result))
        self.assertNotIn('private-password', json.dumps(result))
        self.assertIn('permissions_procedure', result)
        self.assertIn('repository-testing/SKILL.md', result['permissions_procedure'])

    def test_each_application_selects_its_own_file(self):
        for app in ('payscrow-merchant', 'payscrow-provider'):
            path = self.home / '.secrets' / app
            path.touch(mode=0o600)
            path.write_text('other-user\nother-password')
            self.assertEqual(ui.authentication('p2p', app, self.home)['credentials_file'], str(path))

    def test_missing_file_has_actionable_state(self):
        self.path.unlink()
        self.assertEqual(ui.authentication('p2p', 'payscrow-admin', self.home)['state'], 'missing')

    def test_invalid_line_count_or_partial_credentials_refused_without_values(self):
        for value in ('only-user', 'test-user\n\n', 'test-user\nprivate-password\nextra'):
            self.path.write_text(value)
            with self.assertRaisesRegex(RuntimeError, 'exactly two nonempty lines') as caught:
                ui.authentication('p2p', 'payscrow-admin', self.home)
            self.assertNotIn('test-user', str(caught.exception))
            self.assertNotIn('private-password', str(caught.exception))

    def test_world_readable_file_refused(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, '0600'):
            ui.authentication('p2p', 'payscrow-admin', self.home)

    def test_symlink_file_and_directory_refused(self):
        self.path.unlink()
        target = self.home / 'elsewhere'
        target.touch(mode=0o600)
        self.path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            ui.authentication('p2p', 'payscrow-admin', self.home)
        self.path.unlink()
        (self.home / '.secrets').rmdir()
        folder = self.home / 'other-secrets'
        folder.mkdir(mode=0o700)
        (self.home / '.secrets').symlink_to(folder, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            ui.authentication('p2p', 'payscrow-admin', self.home)

    def test_ecom_never_uses_p2p_credentials(self):
        self.assertEqual(ui.authentication('ecom', 'payscrow-admin', self.home)['state'], 'not-configured')

    def test_unknown_application_refused(self):
        with self.assertRaises(RuntimeError):
            ui.authentication('p2p', '../other', self.home)


class ProfileTests(unittest.TestCase):
    def test_role_profiles_prepare_common_role_and_selected_app(self):
        for role in ('admin', 'merchant', 'provider'):
            steps = environment.profile_steps('p2p', role + '-ui')
            self.assertEqual([step[0] for step in steps],
                             ['lib/common-layer', 'lib/' + role + '-layer', 'apps/payscrow-' + role])
            self.assertEqual(steps[-1][1][-1], 'apps/payscrow-' + role)

    def test_ecom_new_roles_are_not_silently_enabled(self):
        for role in ('merchant', 'provider'):
            with self.assertRaises(RuntimeError):
                environment.profile_steps('ecom', role + '-ui')

    def test_admin_tests_and_commit_keep_existing_roots(self):
        self.assertEqual([s[0] for s in environment.profile_steps('p2p', 'admin-tests')],
                         ['lib/common-layer', 'lib/admin-layer'])
        self.assertEqual(environment.profile_steps('p2p', 'commit'),
                         environment.profile_steps('p2p', 'admin-ui'))

    def test_native_test_profiles_prepare_only_common_and_selected_layer(self):
        for role in ('admin', 'form', 'merchant', 'provider'):
            self.assertEqual([s[0] for s in environment.profile_steps('p2p', role + '-tests')],
                             ['lib/common-layer', 'lib/' + role + '-layer'])
        self.assertEqual([s[0] for s in environment.profile_steps('p2p', 'common-tests')],
                         ['lib/common-layer'])
        with self.assertRaises(RuntimeError):
            environment.profile_steps('ecom', 'form-tests')

    def test_generated_key_tracks_selected_role_not_admin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in ('lib/common-layer', 'lib/admin-layer', 'lib/merchant-layer', 'apps/payscrow-merchant'):
                (root / directory).mkdir(parents=True)
                (root / directory / 'nuxt.config.ts').write_text('initial')
            key = environment.generated_key(root, 'apps/payscrow-merchant', 'deps')
            (root / 'lib/merchant-layer/nuxt.config.ts').write_text('changed')
            changed = environment.generated_key(root, 'apps/payscrow-merchant', 'deps')
            self.assertNotEqual(key, changed)
            (root / 'lib/admin-layer/nuxt.config.ts').write_text('unrelated')
            self.assertEqual(changed, environment.generated_key(root, 'apps/payscrow-merchant', 'deps'))


if __name__ == '__main__':
    unittest.main()
