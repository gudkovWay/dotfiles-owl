#!/usr/bin/env python3
"""Review provenance and evolution decisions; no model, network or product runtime."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = importlib.import_module('review_contract')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.session = self.root / 'session.jsonl'
        self.entries = [
            {'type': 'session', 'id': 'owner-session', 'cwd': '/p2p-frontend'},
            {'type': 'custom', 'customType': 'q.prompt-card.submitted', 'data': {'text': 'Use deals as reference; redesign appeals only.'}},
            {'type': 'message', 'message': {'role': 'user', 'attribution': 'user', 'content': [{'type': 'text', 'text': 'Use deals as reference; redesign appeals only.'}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'I approve changing all ID cells.'}]}},
            {'type': 'message', 'message': {'role': 'user', 'attribution': 'user', 'content': [{'type': 'text', 'text': 'Keep the ID presentation; no merge.'}]}},
        ]
        self.write_session()
        self.context = self.contract.capture_context([self.session])
        (self.root / 'new.vue').write_text('new ID rendering')
        (self.root / 'deals.vue').write_text('established ID rendering')

    def write_session(self):
        self.session.write_text(''.join(json.dumps(entry) + '\n' for entry in self.entries))

    def reference(self, name):
        return {'path': name, 'revision': 'worktree',
                'sha256': hashlib.sha256((self.root / name).read_bytes()).hexdigest()}

    def report(self):
        return {'context_key': self.context['context_key'], 'coverage': [{
            'paths': ['new.vue'], 'scenario': 'appeal ID',
            'inspected': [self.reference('new.vue'), self.reference('deals.vue')],
            'comparisons': [{'candidate': self.reference('new.vue'), 'reference': self.reference('deals.vue'),
                             'direction': 'preserve-reference', 'basis': ['r1', 'r2'],
                             'decision': 'Keep the established deals ID; do not roll out the new local version.',
                             'rollout': []}],
            'findings': [], 'verification': 'source only; runtime proof separate'}]}

    def test_context_keeps_owner_corrections_not_assistant_approval(self):
        texts = [item['text'] for item in self.context['requirements']]
        self.assertEqual(texts, ['Use deals as reference; redesign appeals only.', 'Keep the ID presentation; no merge.'])
        self.assertEqual(self.context['sources'][0]['session'], 'owner-session')
        self.assertFalse(self.context['authority'])
        self.contract.validate_context(self.context)

    def test_new_owner_correction_invalidates_captured_context(self):
        self.entries.append({'type': 'message', 'message': {'role': 'user', 'content': 'Now use the new payment flow.'}})
        self.write_session()
        with self.assertRaisesRegex(RuntimeError, 'context changed'):
            self.contract.validate_context(self.context)

    def test_assistant_append_does_not_invalidate_owner_context(self):
        self.entries.append({'type': 'message', 'message': {'role': 'assistant', 'content': 'more investigation'}})
        self.write_session()
        self.contract.validate_context(self.context)

    def test_report_preserves_established_reference_without_per_cell_approval_document(self):
        self.contract.validate_review(self.root, self.report(), ['new.vue'], self.context)

    def test_newer_code_is_not_itself_authority_for_new_flow(self):
        report = self.report()
        comparison = report['coverage'][0]['comparisons'][0]
        comparison.update(direction='adopt-new-flow', basis=[])
        with self.assertRaisesRegex(RuntimeError, 'owner requirement'):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_owner_directed_new_flow_can_replace_legacy_analog(self):
        self.entries[-1]['message']['content'] = 'Replace the old payment flow with this new flow in both consumers.'
        self.write_session()
        self.context = self.contract.capture_context([self.session])
        report = self.report()
        comparison = report['coverage'][0]['comparisons'][0]
        comparison.update(direction='adopt-new-flow', basis=['r2'],
                          decision='Owner requests the new flow; the old consumer is legacy.')
        self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_outside_mr_rollout_needs_owner_evidence_not_reviewer_preference(self):
        report = self.report()
        comparison = report['coverage'][0]['comparisons'][0]
        comparison.update(rollout=['deals.vue'], basis=[])
        with self.assertRaisesRegex(RuntimeError, 'rollout'):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_missing_scope_or_duplicate_coverage_is_rejected(self):
        for paths in (['new.vue', 'unreviewed.vue'], []):
            with self.assertRaisesRegex(RuntimeError, 'coverage'):
                self.contract.validate_review(self.root, self.report(), paths, self.context)
        report = self.report()
        report['coverage'] *= 2
        with self.assertRaisesRegex(RuntimeError, 'coverage'):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_changed_reference_bytes_invalidate_review(self):
        report = self.report()
        (self.root / 'deals.vue').write_text('different reference')
        with self.assertRaisesRegex(RuntimeError, 'reference bytes'):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_fake_owner_requirement_and_empty_comparison_are_rejected(self):
        report = self.report()
        report['coverage'][0]['comparisons'][0]['basis'] = ['made-up']
        with self.assertRaises(RuntimeError):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)
        report = self.report()
        report['coverage'][0]['comparisons'] = []
        with self.assertRaisesRegex(RuntimeError, 'analog'):
            self.contract.validate_review(self.root, report, ['new.vue'], self.context)
        report['coverage'][0]['no_analog'] = 'Searched related list components; no analogous behavior exists.'
        self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_likely_secret_is_not_exported_to_reviewer(self):
        self.entries[-1]['message']['content'] = 'password=private-value'
        self.write_session()
        with self.assertRaisesRegex(RuntimeError, 'secret'):
            self.contract.capture_context([self.session])

    def test_reference_cannot_read_outside_repo_or_secret_files(self):
        for name in ('../outside', '.env', 'apps/payscrow-admin/.env'):
            report = self.report()
            report['coverage'][0]['inspected'][0]['path'] = name
            with self.assertRaises(RuntimeError):
                self.contract.validate_review(self.root, report, ['new.vue'], self.context)

    def test_native_capture_and_validate_entrypoints(self):
        helper = Path(self.contract.__file__)
        result = subprocess.run([sys.executable, str(helper), 'capture', '--root', str(self.root),
                                 '--session', str(self.session)], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['context_key'], self.context['context_key'])
        report = self.root / 'review.json'
        paths = self.root / 'paths.json'
        report.write_text(json.dumps(self.report()))
        paths.write_text(json.dumps(['new.vue']))
        result = subprocess.run([sys.executable, str(helper), 'validate', '--root', str(self.root),
                                 '--report', str(report), '--paths', str(paths)],
                                text=True, capture_output=True, check=True)
        self.assertIn('semantic/runtime quality is separate', result.stdout)


if __name__ == '__main__':
    unittest.main()
