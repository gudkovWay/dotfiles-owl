#!/usr/bin/env python3
"""Queue fairness, durable request refresh and diagnostic admission regressions."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resource_policy as policy
import resource_guard as guard
import resource_executor as executor

G = 1024 ** 3


def request(name, required, *, age=0, goal='one', keys=(), tasks=256):
    return dict(id=name, pid=1, start=1, goal=goal, enqueued_at=age,
                deadline=1000, required=required, keys=list(keys), tasks=tasks)



class QueueSelectionTests(unittest.TestCase):
    def test_aged_ram_head_still_allows_a_fitting_candidate(self):
        state = dict(jobs={}, queue=[request('large', 12 * G), request('small', G, age=1)])
        self.assertIsNotNone(policy.queue_choice(state, 8 * G, set(), 80))
    def decide(self, queue, capacity, now=80, jobs=None, target='small'):
        state = dict(jobs=jobs or {}, queue=queue, last_goal='one')
        keys = {key for job in state['jobs'].values() for key in job.get('keys', [])}
        result = policy.queue_choice(state, capacity, keys, now, request=target)
        self.assertIsInstance(result, dict)
        return result

    def test_aged_unfittable_head_does_not_idle_an_empty_executor(self):
        result = self.decide([request('large', 49 * G // 4), request('small', 2 * G, age=1)], 8 * G)
        self.assertEqual(result['selected'], 'small')

    def test_aged_fitting_head_wins_over_other_goal(self):
        result = self.decide([request('large', 6 * G), request('small', G, age=1, goal='two')], 8 * G)
        self.assertEqual(result['selected'], 'large')
        self.assertEqual(result['reason_code'], 'queue_turn')
        self.assertEqual(result['blocking_job_id'], 'large')

    def test_running_reservations_can_drain_for_an_aged_large_request(self):
        jobs = {'running': dict(limit=4 * G, tasks=256, keys=[])}
        result = self.decide([request('large', 8 * G), request('small', G, age=1)], 6 * G, now=65, jobs=jobs)
        self.assertIsNone(result['selected'])
        self.assertEqual(result['reason_code'], 'queue_head_drain')
        self.assertEqual(result['blocking_job_id'], 'large')

    def test_drain_does_not_wait_for_capacity_running_jobs_cannot_supply(self):
        jobs = {'running': dict(limit=4 * G, tasks=256, keys=[])}
        result = self.decide([request('large', 12 * G), request('small', G, age=1)], 6 * G, jobs=jobs)
        self.assertEqual(result['selected'], 'small')

    def test_drain_has_a_finite_window_without_resetting_head_age(self):
        jobs = {'running': dict(limit=4 * G, tasks=256, keys=[])}
        result = self.decide([request('large', 8 * G), request('small', G, age=1)], 6 * G, now=121, jobs=jobs)
        self.assertEqual(result['selected'], 'small')

    def test_foreign_environment_does_not_block_independent_work(self):
        jobs = {'running': dict(limit=G, tasks=256, keys=['/owned'])}
        queue = [request('large', G, keys=['/owned']), request('small', G, age=1)]
        self.assertEqual(self.decide(queue, 4 * G, jobs=jobs)['selected'], 'small')
        result = self.decide(queue, 4 * G, jobs=jobs, target='large')
        self.assertEqual(result['reason_code'], 'environment_busy')
        self.assertEqual(result['blocking_job_id'], 'running')
        self.assertEqual(result['blocked_keys'], ['/owned'])

    def test_gpu_lock_is_distinct_from_ram_and_environment(self):
        jobs = {'gpu': dict(limit=G, tasks=256, keys=['/gpu/host'])}
        result = self.decide([request('small', G, keys=['/gpu/host'])], 8 * G, jobs=jobs)
        self.assertEqual(result['reason_code'], 'gpu_busy')

    def test_pid_unfittable_head_does_not_block_smaller_request(self):
        jobs = {'running': dict(limit=G, tasks=1792, keys=[])}
        queue = [request('large', G, tasks=512), request('small', G, age=1)]
        self.assertEqual(self.decide(queue, 8 * G, jobs=jobs)['selected'], 'small')
        result = self.decide(queue, 8 * G, jobs=jobs, target='large')
        self.assertEqual(result['reason_code'], 'pid_budget')

    def test_ram_shortage_has_numeric_requirement_not_an_unknown_eta(self):
        result = self.decide([request('small', 6 * G)], 3 * G)
        self.assertEqual(result['reason_code'], 'ram')
        self.assertEqual(result['required_bytes'], 6 * G)
        self.assertEqual(result['free_capacity_bytes'], 3 * G)

    def test_expired_request_is_not_selected(self):
        entry = request('small', G)
        entry['deadline'] = 70
        self.assertIsNone(self.decide([entry], 8 * G)['selected'])

    def test_full_job_slots_do_not_misreport_ram(self):
        jobs = {str(n): dict(limit=G, tasks=1, keys=[]) for n in range(8)}
        result = self.decide([request('small', G)], 20 * G, jobs=jobs)
        self.assertEqual(result['reason_code'], 'job_slots')


class QueueRefreshTests(unittest.TestCase):
    def test_refresh_updates_resources_without_restarting_age_or_deadline(self):
        entry = request('same', G, age=5)
        state = {'queue': [copy.deepcopy(entry)]}
        newer = dict(entry, required=6 * G, tasks=512, keys=['/owned'], enqueued_at=100, deadline=2000)
        policy.enqueue(state, newer)
        self.assertEqual(len(state['queue']), 1)
        self.assertEqual(state['queue'][0], dict(entry, required=6 * G, tasks=512, keys=['/owned']))

    def test_same_queue_id_cannot_be_reused_by_another_process(self):
        entry = request('same', G)
        state = {'queue': [copy.deepcopy(entry)]}
        with self.assertRaises(policy.GuardError):
            policy.enqueue(state, dict(entry, pid=2))
        self.assertEqual(state['queue'], [entry])


class AdmissionDiagnosticsTests(unittest.TestCase):
    def test_ram_deferral_preserves_preexec_receipt_and_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = guard.Registry(Path(directory))
            backend = guard.Systemd()
            args = guard.argparse.Namespace(goal_ticket=None, elastic=False, memory=6 * G,
                need=None, ceiling=None, runtime=600, exclusive_key=None, job_id=None,
                gpu_key=None, tasks=256, wait=60, admission_windows=1)
            now = [0.]
            with patch.object(guard, 'Registry', return_value=registry), \
                    patch.object(guard, 'Systemd', return_value=backend), \
                    patch.object(backend, 'infrastructure'), \
                    patch.object(backend, 'units', return_value=[]), \
                    patch.object(guard, 'mem_available', return_value=2 * G), \
                    patch.object(executor.signal, 'signal'), \
                    patch.object(executor.time, 'monotonic', side_effect=lambda: now[0]), \
                    patch.object(executor.time, 'sleep', side_effect=lambda _: now.__setitem__(0, now[0] + 60)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(guard.Busy):
                    guard.execute(args, ['/usr/bin/true'], '')
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            for record in records:
                self.assertEqual(record['reason_code'], 'ram')
                self.assertEqual(record['required_bytes'], 6 * G)
                self.assertEqual(record['available_bytes'], 2 * G)
                self.assertEqual(record['unused_promises_bytes'], 0)
                self.assertEqual(record['free_capacity_bytes'], G)
                self.assertTrue(record['boot_id'])
                self.assertTrue(record['timestamp_utc'].endswith('+00:00'))
            self.assertEqual(records[-1]['event'], 'deferred')
            self.assertIs(records[-1]['admitted'], False)
            self.assertIs(records[-1]['workload_started'], False)
            self.assertEqual(registry.load()['jobs'], {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
