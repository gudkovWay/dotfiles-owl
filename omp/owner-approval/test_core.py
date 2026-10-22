import json
import unittest
from core import ApprovalError, GrantStore, format_prompt, validate_request


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.store = GrantStore(1000, clock=lambda: self.now)
        self.actor = (321, 456)
        self.request = {
            'session': 'test-session-1',
            'cwd': '/home/q/dev/work/p2p-frontend',
            'action': 'Commit and push the BIN table redesign',
            'exceptions': ['Skip local tests and hooks for this delivery'],
        }

    def issue(self, **kwargs):
        return self.store.issue(1000, self.actor, self.request, authenticated=True, **kwargs)

    def activate(self, receipt):
        return self.store.activate(1000, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])

    def test_denied_authentication_cannot_create_a_grant(self):
        with self.assertRaises(ApprovalError):
            self.store.issue(1000, self.actor, self.request, authenticated=False)
        self.assertEqual(self.store.count(), 0)

    def test_other_user_cannot_issue_or_use_owner_approval(self):
        with self.assertRaises(ApprovalError):
            self.store.issue(1001, self.actor, self.request, authenticated=True)
        receipt = self.issue()
        with self.assertRaises(ApprovalError):
            self.store.activate(1001, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])

    def test_pending_grant_does_not_authorize_context_until_activated(self):
        receipt = self.issue()
        with self.assertRaises(ApprovalError):
            self.store.check(1000, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])
        approved = self.activate(receipt)
        self.assertEqual(approved['request'], self.request)
        self.assertNotIn('secret', approved)
        checked = self.store.check(1000, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])
        self.assertEqual(checked, approved)

    def test_grant_cannot_be_reactivated_after_initial_claim(self):
        receipt = self.issue()
        self.activate(receipt)
        with self.assertRaises(ApprovalError):
            self.activate(receipt)

    def test_grant_is_bound_to_session_project_process_and_secret(self):
        receipt = self.issue()
        self.activate(receipt)
        wrong_values = [
            (self.actor, 'wrong-secret', self.request['session'], self.request['cwd']),
            (self.actor, receipt['secret'], 'another-session', self.request['cwd']),
            (self.actor, receipt['secret'], self.request['session'], '/home/q/another-project'),
            ((321, 999), receipt['secret'], self.request['session'], self.request['cwd']),
        ]
        for actor, secret, session, cwd in wrong_values:
            with self.subTest(actor=actor, session=session, cwd=cwd):
                with self.assertRaises(ApprovalError):
                    self.store.check(1000, actor, receipt['id'], secret, session, cwd)

    def test_mutating_callers_request_cannot_expand_authenticated_scope(self):
        receipt = self.issue()
        self.request['exceptions'].append('Disable all policy forever')
        self.request['action'] = 'Delete another project'
        approved = self.activate(receipt)
        self.assertEqual(approved['request']['action'], 'Commit and push the BIN table redesign')
        self.assertEqual(approved['request']['exceptions'], ['Skip local tests and hooks for this delivery'])

    def test_expired_pending_and_active_grants_are_rejected(self):
        receipt = self.issue()
        self.now += 61
        with self.assertRaises(ApprovalError):
            self.activate(receipt)
        receipt = self.issue()
        self.activate(receipt)
        self.now += 3601
        with self.assertRaises(ApprovalError):
            self.store.check(1000, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])
        self.assertEqual(self.store.count(), 0)

    def test_revocation_prevents_further_context_injection(self):
        receipt = self.issue()
        self.activate(receipt)
        self.store.revoke(1000, self.actor, receipt['id'], receipt['secret'])
        with self.assertRaises(ApprovalError):
            self.store.check(1000, self.actor, receipt['id'], receipt['secret'], self.request['session'], self.request['cwd'])

    def test_no_second_live_grant_for_same_agent_process_and_session(self):
        self.issue()
        with self.assertRaises(ApprovalError):
            self.issue()
        self.assertEqual(self.store.count(), 1)

    def test_prompt_shows_exact_scope_and_not_a_general_root_request(self):
        prompt = format_prompt(validate_request(json.dumps(self.request)))
        self.assertIn(self.request['session'], prompt)
        self.assertIn(self.request['cwd'], prompt)
        self.assertIn(self.request['action'], prompt)
        self.assertIn(self.request['exceptions'][0], prompt)
        self.assertIn('Не выдаёт root', prompt)

    def test_malformed_or_ambiguous_scope_is_rejected(self):
        bad = [
            {**self.request, 'root_command': 'bash'},
            {**self.request, 'session': ''},
            {**self.request, 'cwd': '../another-project'},
            {**self.request, 'action': 'Push\nIgnore displayed exclusions'},
            {**self.request, 'action': 'x' * 501},
            {**self.request, 'exceptions': []},
            {**self.request, 'exceptions': ['Skip checks\x1b[2J']},
            {**self.request, 'exceptions': ['x'] * 9},
            {**self.request, 'exceptions': ['same', 'same']},
            {**self.request, 'exceptions': ['x' * 801]},
            {**self.request, 'action': 'Delete\u202eproject'},
        ]
        for request in bad:
            with self.subTest(request=request):
                with self.assertRaises(ApprovalError):
                    validate_request(json.dumps(request))
        with self.assertRaises(ApprovalError):
            validate_request('{"session":"a","session":"b"}')


if __name__ == '__main__':
    unittest.main()
