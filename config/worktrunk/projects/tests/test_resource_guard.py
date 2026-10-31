#!/usr/bin/env python3
"""Finite resource-guard regressions; Python standard library only."""
import contextlib
import io
import json
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resource_guard as guard

G = 1024 ** 3
SCOPE = 'omp-heavy-job-' + 'a' * 32 + '.scope'
OTHER = 'omp-heavy-job-' + 'b' * 32 + '.scope'


def job(limit=3 * G, pid=1, start=1, keys=()):
    return {'limit': limit, 'pid': pid, 'start': start,
            'launcher_pid': 0, 'launcher_start': 0, 'keys': list(keys)}


class Observations:
    """External process/systemd observations, not an allocation double."""
    def __init__(self, alive=(), live=()):
        self.identities = set(alive)
        self.live = set(live)

    def alive(self, pid, start):
        return (pid, start) in self.identities

    def populated(self, unit):
        return unit in self.live

    def units(self):
        return sorted(self.live)


class AdmissionReceiptTests(unittest.TestCase):
    def test_two_windows_never_launch_or_reserve_when_admission_stays_busy(self):
        import resource_executor as executor
        with tempfile.TemporaryDirectory() as directory:
            registry = guard.Registry(Path(directory))
            backend = guard.Systemd()
            args = guard.argparse.Namespace(goal_ticket=None, elastic=False, memory=None,
                need=G, ceiling=None, runtime=600, exclusive_key=None, job_id=None,
                gpu_key=None, tasks=256, wait=60, admission_windows=2)
            now = [0.]
            with patch.object(guard, 'Registry', return_value=registry), \
                    patch.object(guard, 'Systemd', return_value=backend), \
                    patch.object(backend, 'infrastructure'), \
                    patch.object(guard, 'reconcile', side_effect=guard.Busy('environment_busy')) as reconcile, \
                    patch.object(guard, 'start_launcher') as launch, \
                    patch.object(executor.signal, 'signal'), \
                    patch.object(executor.time, 'monotonic', side_effect=lambda: now[0]), \
                    patch.object(executor.time, 'sleep', side_effect=lambda _: now.__setitem__(0, now[0] + 60)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(guard.Busy):
                    guard.execute(args, ['/usr/bin/true'], '')
            launch.assert_not_called()
            self.assertEqual(reconcile.call_count, 3)
            self.assertEqual(registry.load()['jobs'], {})
            receipts = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(receipts[-1]['event'], 'deferred')
            self.assertEqual(receipts[-1]['phase'], 'admission')
            self.assertIs(receipts[-1]['workload_started'], False)
            self.assertIs(receipts[-1]['admitted'], False)
            self.assertEqual(receipts[-1]['admission_windows'], 2)


class BudgetTests(unittest.TestCase):
    def test_small_job_can_fit_below_old_ten_gib_threshold(self):
        state = {'budget': 0, 'jobs': {}}
        self.assertEqual(guard.admission(state, 5 * G, G), 4 * G)
        self.assertEqual(guard.admission(state, 2 * G, G), G)
        with self.assertRaises(guard.Busy):
            guard.admission(state, 2 * G, 2 * G)
        self.assertEqual(guard.admission(state, 20 * G + 1, 16 * G), 19 * G)

    def test_live_epoch_keeps_budget_and_accounts_for_unused_headroom(self):
        state = {'budget': 8 * G, 'jobs': {SCOPE: job()}}
        original = copy.deepcopy(state)
        self.assertEqual(guard.admission(state, 20 * G, 3 * G, {SCOPE: G}), 20 * G)
        with self.assertRaises(guard.Busy):
            guard.admission(state, 4 * G, 2 * G, {SCOPE: G})
        self.assertEqual(state, original)
        with self.assertRaises(guard.GuardError):
            guard.admission(state, 20 * G, G)

    def test_reservations_and_eight_job_limit_bound_admission(self):
        state = {'budget': 6 * G, 'jobs': {SCOPE: job(), OTHER: job()}}
        with self.assertRaises(guard.Busy):
            guard.admission(state, 5 * G, G, {SCOPE: G, OTHER: G})
        names = ['omp-heavy-job-' + f'{number:032x}' + '.scope' for number in range(8)]
        state = {'budget': 24 * G, 'jobs': {name: job() for name in names}}
        with self.assertRaises(guard.Busy):
            guard.admission(state, 30 * G, G, {name: G for name in names})

    def test_existing_parent_cap_is_retained_but_fresh_admission_checks_available_ram(self):
        self.assertEqual(guard.admission({'budget': 16 * G, 'jobs': {}}, 8 * G, 3 * G), 16 * G)
        self.assertEqual(guard.admission({'budget': 0, 'jobs': {}}, 8 * G, 3 * G), 7 * G)
        with self.assertRaises(guard.Busy):
            guard.admission({'budget': 16 * G, 'jobs': {}}, 3 * G, 3 * G)

    def test_memory_request_is_not_silently_clamped(self):
        for value in ['0', '-1G', 'infinity', '80%']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                guard.parse_memory(value)
        self.assertEqual(guard.parse_memory('3G'), 3 * G)
        self.assertEqual(guard.parse_memory('512M'), G // 2)
        self.assertEqual(guard.parse_memory('12G'), 12 * G)

    def test_large_request_uses_fresh_shared_budget_not_a_fixed_cap(self):
        state = {'budget': 0, 'jobs': {}}
        self.assertEqual(guard.admission(state, 20 * G, 12 * G), 19 * G)
        with self.assertRaises(guard.Busy):
            guard.admission(state, 10 * G, 12 * G)
        state = {'budget': 16 * G, 'jobs': {SCOPE: job(12 * G)}}
        with self.assertRaises(guard.Busy):
            guard.admission(state, 20 * G, 20 * G, {SCOPE: 12 * G})
        self.assertEqual(guard.admission(state, 20 * G, 4 * G, {SCOPE: 12 * G}), 31 * G)

    def test_budget_rounds_down_and_rejects_invalid_memory_accounting(self):
        for available in (0, 1, G, 3 * G + 123, 20 * G - 1):
            budget = guard.available_budget(available)
            safe = max(0, available - G)
            self.assertLessEqual(budget, safe)
            self.assertLess(safe - budget, guard.STEP)
        for available in (-1, None, True, 1.5):
            with self.subTest(available=available), self.assertRaises(guard.GuardError):
                guard.available_budget(available)

    def test_node_heap_preserves_smaller_limits_and_other_flags(self):
        self.assertEqual(guard.node_options('--trace-warnings --max_old_space_size=512'),
                         '--trace-warnings --max-old-space-size=512')


class AllocationTests(unittest.TestCase):
    def test_default_reserves_expected_peak_plus_buffer_not_all_free_ram(self):
        state = {'budget': 0, 'jobs': {}}
        self.assertEqual(guard.allocate_memory(state, 20 * G, None, {}),
                         (19 * G, 11 * G // 4, 19 * G // 8))
        self.assertEqual(state, {'budget': 0, 'jobs': {}})
        self.assertEqual(guard.allocate_memory(state, 20 * G, 4 * G, {}),
                         (19 * G, 4 * G, 4 * G * 2 // 3))

    def test_default_accounts_for_every_live_unused_promise(self):
        state = {'budget': 8 * G, 'jobs': {SCOPE: job()}}
        original = copy.deepcopy(state)
        self.assertEqual(guard.allocate_memory(state, 20 * G, None, {SCOPE: G}),
                         (20 * G, 11 * G // 4, 19 * G // 8))
        self.assertEqual(state, original)
        state['jobs'][OTHER] = job(5 * G)
        with self.assertRaises(guard.Busy):
            guard.allocate_memory(state, 9 * G, None, {SCOPE: G, OTHER: G})

    def test_adaptive_maximum_is_bounded_by_fresh_ram_and_reserved_headroom(self):
        state = {'budget': 16 * G, 'jobs': {SCOPE: job()}}
        self.assertEqual(guard.allocate_memory(state, 6 * G, None, {SCOPE: G}),
                         (16 * G, 11 * G // 4, 19 * G // 8))
        with self.assertRaises(guard.Busy):
            guard.allocate_memory(state, 5 * G, None, {SCOPE: G})
        with self.assertRaises(guard.GuardError):
            guard.allocate_memory(state, 20 * G, None, {})
        with self.assertRaises(guard.Busy):
            guard.allocate_memory({'budget': 0, 'jobs': {}}, 2 * G, None, {})

    def test_node_heap_scales_with_hard_maximum_and_keeps_non_heap_headroom(self):
        self.assertEqual(guard.node_options('--trace-warnings', 4 * G),
                         '--trace-warnings --max-old-space-size=3072')
        self.assertEqual(guard.node_options('--max-old-space-size=512', 16 * G),
                         '--max-old-space-size=512')
        self.assertEqual(guard.node_options('--max-old-space-size=20000', 16 * G),
                         '--max-old-space-size=12288')
        with self.assertRaises(guard.GuardError):
            guard.node_options('--max-old-space-size=0', 4 * G)

    def test_native_heap_flags_cannot_override_the_admitted_heap_budget(self):
        guard.validate_node_command(['node', '--max-old-space-size=3072'], 4 * G)
        for command in (['node', '--max-old-space-size=4096'],
                        ['node', '--max_old_space_size', '4096'],
                        ['node', '--max-old-space-size=0']):
            with self.subTest(command=command), self.assertRaises(guard.GuardError):
                guard.validate_node_command(command, 4 * G)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = guard.Registry(Path(self.tmp.name))

    def test_pending_reservation_is_durable_and_not_double_allocated(self):
        state = {'budget': 6 * G, 'jobs': {SCOPE: job(6 * G)}}
        with self.registry.lock():
            self.registry.save(state)
        with self.registry.lock():
            observed = self.registry.load()
            with self.assertRaises(guard.Busy):
                guard.admission(observed, 7 * G, G, {SCOPE: 0})

    def test_admission_lock_is_exclusive_and_does_not_wait_without_permission(self):
        with self.registry.lock():
            with self.assertRaises(guard.Busy):
                with guard.Registry(Path(self.tmp.name)).lock():
                    self.fail('second caller acquired the admission lock')
        with self.registry.lock():
            self.registry.save({'budget': 0, 'jobs': {}})

    def test_same_stable_lock_is_reusable_after_short_admission(self):
        other = guard.Registry(Path(self.tmp.name))
        with self.registry.lock():
            inode = self.registry.lock_path.stat().st_ino
            self.registry.save({'budget': 0, 'jobs': {}})
            with self.assertRaises(guard.Busy):
                with other.lock():
                    pass
        with other.lock():
            self.assertEqual(other.load()['jobs'], {})
            self.assertEqual(other.lock_path.stat().st_ino, inode)

    def test_dead_owner_cannot_release_a_live_scope(self):
        state = {'budget': 6 * G, 'jobs': {SCOPE: job(6 * G)}}
        guard.reconcile(state, Observations(live=[SCOPE]))
        self.assertIn(SCOPE, state['jobs'])

    def test_launcher_identity_retains_reservation_before_scope_creation(self):
        pending = job()
        pending.update(launcher_pid=2, launcher_start=23)
        state = {'budget': 6 * G, 'jobs': {SCOPE: pending}}
        guard.reconcile(state, Observations(alive=[(2, 23)]))
        self.assertIn(SCOPE, state['jobs'])

    def test_pid_reuse_does_not_keep_a_completed_reservation(self):
        state = {'budget': 6 * G, 'jobs': {SCOPE: job(start=11)}}
        guard.reconcile(state, Observations(alive=[(1, 12)]))
        self.assertEqual(state['jobs'], {})

    def test_unknown_scope_cannot_be_ignored_as_if_it_were_registered(self):
        with self.assertRaises(guard.GuardError):
            guard.reconcile({'budget': 0, 'jobs': {}}, Observations(live=[SCOPE]))

    def test_corrupted_or_symlinked_state_is_rejected_not_reset(self):
        self.registry.state_path.write_text('{broken')
        with self.assertRaises(guard.GuardError):
            self.registry.load()
        self.registry.state_path.unlink()
        outside = Path(self.tmp.name) / 'outside'
        outside.write_text('{}')
        self.registry.state_path.symlink_to(outside)
        with self.assertRaises(guard.GuardError):
            self.registry.load()

    def test_environment_claim_is_reentrant_only_within_its_own_reservation(self):
        state = {'budget': 6 * G,
                 'jobs': {SCOPE: job(), OTHER: job(keys=['/other'])}}
        guard.claim_key(state, SCOPE, '/one')
        guard.claim_key(state, SCOPE, '/one')
        self.assertEqual(state['jobs'][SCOPE]['keys'], ['/one'])
        with self.assertRaises(guard.Busy):
            guard.claim_key(state, SCOPE, '/other')

    def test_native_command_starts_only_after_durable_launcher_reservation(self):
        marker = Path(self.tmp.name) / 'launched'
        state = {'budget': 6 * G,
                 'jobs': {SCOPE: job(pid=os.getpid(), start=guard.pid_identity(os.getpid()))}}
        with self.registry.lock() as fd:
            pid = guard.start_launcher(self.registry, fd, state, SCOPE,
                                       ['/usr/bin/touch', str(marker)])
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertTrue(marker.is_file())
        self.assertEqual(self.registry.load()['jobs'][SCOPE]['launcher_pid'], pid)

    def test_failed_publication_cannot_launch_an_unreserved_command(self):
        marker = Path(self.tmp.name) / 'unreserved'
        state = {'budget': 6 * G,
                 'jobs': {SCOPE: job(pid=os.getpid(), start=guard.pid_identity(os.getpid()))}}
        with self.registry.lock() as fd, patch.object(
                self.registry, 'save', side_effect=guard.GuardError('publication failed')):
            with self.assertRaises(guard.GuardError):
                guard.start_launcher(self.registry, fd, state, SCOPE,
                                     ['/usr/bin/touch', str(marker)])
        self.assertFalse(marker.exists())

    def test_runtime_is_durable_and_invalid_values_are_rejected(self):
        reservation = job(12 * G)
        reservation['runtime'] = 1200
        state = {'budget': 16 * G, 'jobs': {SCOPE: reservation}}
        with self.registry.lock():
            self.registry.save(state)
        self.assertEqual(self.registry.load()['jobs'][SCOPE]['runtime'], 1200)
        for runtime in (0, 600.0, True, 28801, None, '600', 'unlimited'):
            invalid = copy.deepcopy(state)
            invalid['jobs'][SCOPE]['runtime'] = runtime
            with self.subTest(runtime=runtime), self.assertRaises(guard.GuardError):
                guard.validate_state(invalid)

    def test_explicit_infinite_runtime_survives_registry_roundtrip(self):
        reservation = job()
        reservation['runtime'] = 'infinity'
        state = {'budget': 6 * G, 'jobs': {SCOPE: reservation}}
        with self.registry.lock():
            self.registry.save(state)
        self.assertEqual(self.registry.load()['jobs'][SCOPE]['runtime'], 'infinity')

    def test_soft_limit_is_durable_and_legacy_reservations_remain_readable(self):
        reservation = job(8 * G)
        reservation['memory_high'] = 2 * G
        state = {'budget': 16 * G, 'jobs': {SCOPE: reservation, OTHER: job()}}
        with self.registry.lock():
            self.registry.save(state)
        self.assertEqual(self.registry.load(), state)
        for high in (0, -1, True, None, 9 * G):
            invalid = copy.deepcopy(state)
            invalid['jobs'][SCOPE]['memory_high'] = high
            with self.subTest(high=high), self.assertRaises(guard.GuardError):
                guard.validate_state(invalid)



class ContextTests(unittest.TestCase):
    def test_foreign_cgroup_is_rejected_even_when_environment_claims_ownership(self):
        with patch.object(guard, 'current_cgroup', return_value='/app.slice/foreign.scope'):
            with self.assertRaises(guard.GuardError):
                guard.assert_guarded()


class CliTests(unittest.TestCase):
    def launch_options(self, arguments):
        with patch.object(sys, 'argv', ['guarded-run', *arguments, '--', '/usr/bin/true']), \
                patch.object(guard, 'current_cgroup', return_value='/foreign'), \
                patch.object(guard, 'execute', return_value=0) as execute:
            self.assertEqual(guard.main(), 0)
        return execute.call_args.args[0]

    def test_default_selects_adaptive_allocation_and_explicit_approval_doubles_fixed_caps(self):
        ordinary = self.launch_options([])
        self.assertIsNone(ordinary.memory)
        self.assertEqual(ordinary.runtime, 600)
        approved = self.launch_options(['--memory', '6G', '--approved-double'])
        self.assertEqual((approved.memory, approved.runtime), (12 * G, 1200))
        with self.assertRaises(guard.GuardError):
            self.launch_options(['--approved-double'])

    def test_no_timeout_preserves_memory_and_can_combine_with_separate_double_approval(self):
        approved = self.launch_options(['--memory', '6G', '--approved-no-timeout'])
        self.assertEqual((approved.memory, approved.runtime), (6 * G, 'infinity'))
        both = self.launch_options(['--memory', '6G', '--approved-double', '--approved-no-timeout'])
        self.assertEqual((both.memory, both.runtime), (12 * G, 'infinity'))

    def test_second_admission_window_does_not_extend_runtime_or_caps(self):
        args = self.launch_options(['--wait', '60', '--admission-windows', '2', '--memory', '3G'])
        self.assertEqual((args.wait, args.admission_windows, args.runtime, args.memory),
                         (60, 2, 600, 3 * G))
        with self.assertRaises(SystemExit):
            self.launch_options(['--admission-windows', '3'])

    def test_approval_cannot_raise_a_nested_reservation(self):
        for flag in ('--approved-double', '--approved-no-timeout'):
            with self.subTest(flag=flag), \
                    patch.object(sys, 'argv', ['guarded-run', flag, '--', '/usr/bin/true']), \
                    patch.object(guard, 'current_cgroup', return_value='/omp-heavy.slice/' + SCOPE):
                with self.assertRaises(guard.GuardError):
                    guard.main()


class LifecycleTests(unittest.TestCase):
    def test_admission_lock_releases_but_reservation_lives_until_teardown(self):
        self.run_lifecycle(600)

    def test_no_timeout_retains_reservation_and_releases_after_native_exit(self):
        self.run_lifecycle('infinity')
    def test_adaptive_reservation_lives_until_teardown(self):
        self.run_lifecycle(600, memory=None)

    def run_lifecycle(self, runtime, memory=6 * G):
        with tempfile.TemporaryDirectory() as directory:
            registry = guard.Registry(Path(directory))
            other = guard.Registry(Path(directory))
            backend = guard.Systemd()
            marker = Path(directory) / 'launched'
            start = guard.start_launcher
            import resource_executor as executor
            cleanup = executor.cleanup_launcher

            def launch(*args):
                with self.assertRaises(guard.Busy):
                    with other.lock():
                        self.fail('admission lock released before publication')
                return start(*args)

            def teardown(*args):
                self.assertTrue(marker.is_file())
                with other.lock():
                    jobs = other.load()['jobs']
                    self.assertEqual(len(jobs), 1)
                    self.assertEqual(next(iter(jobs.values()))['runtime'], runtime)
                    reservation = next(iter(jobs.values()))
                    self.assertEqual(reservation['limit'], 11 * G // 4 if memory is None else memory)
                    self.assertEqual(reservation['memory_high'],
                                     19 * G // 8 if memory is None else memory * 2 // 3)
                cleanup(*args)

            args = guard.argparse.Namespace(exclusive_key=None, wait=0, memory=memory, runtime=runtime,
                goal_ticket=None, elastic=False, need=None, ceiling=None, job_id=None,
                gpu_key=None, tasks=256, admission_windows=1)
            with patch.object(guard, 'Registry', return_value=registry), \
                    patch.object(guard, 'Systemd', return_value=backend), \
                    patch.object(backend, 'infrastructure'), \
                    patch.object(backend, 'configure_slice'), \
                    patch.object(backend, 'units', return_value=[]), \
                    patch.object(backend, 'populated', return_value=False), \
                    patch.object(guard, 'heavy_processes', return_value=[]), \
                    patch.object(guard, 'mem_available', return_value=10 * G), \
                    patch.object(guard, 'scope_command', return_value=['/usr/bin/touch', str(marker)]), \
                    patch.object(guard, 'start_launcher', side_effect=launch), \
                    patch.object(executor.signal, 'signal'), \
                    patch.object(executor, 'cleanup_launcher', side_effect=teardown):
                self.assertEqual(guard.execute(args, ['/usr/bin/touch', str(marker)], ''), 0)
            self.assertEqual(registry.load()['jobs'], {})
            with other.lock():
                pass


class CapsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in {'memory.high': 4294967296, 'memory.max': 6442450944,
                            'memory.swap.max': 0, 'pids.max': 256,
                            'cpu.max': '200000 100000'}.items():
            (self.root / name).write_text(str(value))
        self.backend = guard.Systemd()
        self.info = {'ActiveState': 'active', 'ControlGroup': '/private/job.scope',
                     'CPUWeight': '20', 'IOWeight': '20', 'RuntimeMaxUSec': '10min',
                     'OOMPolicy': 'kill'}
        self.info_patch = patch.object(self.backend, 'info', return_value=self.info)
        self.root_patch = patch.object(guard, 'cgroup_root', return_value=self.root)
        self.info_patch.start()
        self.root_patch.start()
        self.addCleanup(self.info_patch.stop)
        self.addCleanup(self.root_patch.stop)

    def test_valid_task_count_is_not_page_rounded(self):
        guard.verify_caps(self.backend, SCOPE, 6 * G, True)
        (self.root / 'pids.max').write_text('max')
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True)

    def test_missing_or_unbounded_resource_caps_are_rejected(self):
        for name in ('memory.max', 'memory.swap.max', 'cpu.max'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text('max 100000' if name == 'cpu.max' else 'max')
                with self.assertRaises(guard.GuardError):
                    guard.verify_caps(self.backend, SCOPE, 6 * G, True)
                path.write_text(original)

    def test_scope_without_runtime_or_oom_protection_is_rejected(self):
        self.info['OOMPolicy'] = 'continue'
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True)

    def test_runtime_must_match_the_registered_approved_duration(self):
        self.info['RuntimeMaxUSec'] = '20min'
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True)
        guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime=1200)
        self.info['RuntimeMaxUSec'] = '1200000000'
        guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime=1200)
        self.info['RuntimeMaxUSec'] = 'infinity'
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime=1200)

    def test_infinite_runtime_requires_matching_systemd_and_keeps_oom_and_memory_caps(self):
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime='infinity')
        self.info['RuntimeMaxUSec'] = 'infinity'
        guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime='infinity')
        self.info['OOMPolicy'] = 'continue'
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime='infinity')
        self.info['OOMPolicy'] = 'kill'
        (self.root / 'memory.max').write_text('max')
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True, runtime='infinity')

    def test_adaptive_soft_threshold_is_verified_separately_from_hard_maximum(self):
        (self.root / 'memory.high').write_text(str(2 * G))
        guard.verify_caps(self.backend, SCOPE, 6 * G, True, memory_high=2 * G)
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True)
        (self.root / 'memory.high').write_text(str(4 * G))
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(self.backend, SCOPE, 6 * G, True, memory_high=2 * G)

    def test_entering_adaptive_scope_uses_recorded_soft_threshold_and_keeps_legacy_caps(self):
        parent = '/private/omp-heavy.slice'
        child = parent + '/' + SCOPE
        parent_root = self.root / 'parent'
        parent_root.mkdir()
        page = os.sysconf('SC_PAGE_SIZE')
        for name, value in {'memory.high': (8 * G * 2 // 3) // page * page,
                            'memory.max': 8 * G, 'memory.swap.max': 0,
                            'pids.max': 256, 'cpu.max': '200000 100000'}.items():
            (parent_root / name).write_text(str(value))
        (self.root / 'memory.high').write_text(str(2 * G))
        reservation = {**job(6 * G), 'memory_high': 2 * G}
        state = {'budget': 8 * G, 'jobs': {SCOPE: reservation}}
        with patch.object(self.backend, 'info', side_effect=lambda unit: {
                **self.info, 'ControlGroup': parent if unit == guard.SLICE else child}), \
                patch.object(guard, 'cgroup_root',
                             side_effect=lambda path: parent_root if path == parent else self.root):
            self.assertEqual(guard.context_from_state(state, self.backend, child), SCOPE)
            (self.root / 'memory.high').write_text(str(4 * G))
            with self.assertRaises(guard.GuardError):
                guard.context_from_state(state, self.backend, child)
            del reservation['memory_high']
            self.assertEqual(guard.context_from_state(state, self.backend, child), SCOPE)

    def test_no_timeout_scope_request_does_not_remove_other_protections(self):
        command = guard.scope_command(SCOPE, 6 * G, ['/usr/bin/true'], '', runtime='infinity')
        properties = [command[index + 1] for index, value in enumerate(command) if value == '-p']
        self.assertIn('RuntimeMaxSec=infinity', properties)
        self.assertIn('MemoryMax=6442450944', properties)
        self.assertIn('OOMPolicy=kill', properties)
        self.assertIn('MemorySwapMax=0', properties)
        self.assertIn(f'CPUQuota={guard.CPU_COUNT * 100}%', properties)
        self.assertIn('TasksMax=256', properties)

    def test_reclaimable_cache_does_not_reduce_reserved_headroom(self):
        (self.root / 'memory.current').write_text(str(3 * G))
        (self.root / 'memory.stat').write_text(
            f'file {2 * G}\nshmem {G // 2}\nslab_reclaimable {G // 4}\n')
        self.assertEqual(self.backend.memory_usage(SCOPE), 5 * G // 4)
        state = {'budget': 8 * G, 'jobs': {SCOPE: job()}}
        with self.assertRaises(guard.Busy):
            guard.admission(state, 3 * G, 2 * G, {SCOPE: self.backend.memory_usage(SCOPE)})
        (self.root / 'memory.stat').unlink()
        with self.assertRaises(guard.GuardError):
            self.backend.memory_usage(SCOPE)

    def test_membership_requires_real_scope_under_matching_parent(self):
        state = {'budget': 8 * G, 'jobs': {SCOPE: job()}}
        parent = '/user.slice/omp-heavy.slice'
        child = parent + '/' + SCOPE
        def caps(_backend, unit, _limit, _timed, **_kwargs):
            return parent if unit == guard.SLICE else child
        with patch.object(guard, 'verify_caps', side_effect=caps):
            self.assertEqual(guard.context_from_state(state, self.backend, child), SCOPE)
            with self.assertRaises(guard.GuardError):
                guard.context_from_state(state, self.backend, '/foreign/' + SCOPE)


class PidProfileTests(unittest.TestCase):
    def test_ui_profile_has_512_tasks_without_changing_parent_budget(self):
        import resource_policy as policy
        self.assertEqual(policy.PARENT_PIDS, 2048)
        policy.admit_tasks({'jobs': {}}, 512)
        command = guard.scope_command(SCOPE, G, ['/usr/bin/true'], '', tasks=512)
        self.assertIn('TasksMax=512', command)
        self.assertNotIn('TasksMax=256', command)

    def test_promised_caps_are_counted_and_legacy_jobs_keep_256(self):
        import resource_policy as policy
        state = {'jobs': {str(n): {'tasks': 512} for n in range(3)}}
        policy.admit_tasks(state, 512)
        state['jobs']['old'] = {}
        with self.assertRaisesRegex(guard.Busy, 'pid_budget'):
            policy.admit_tasks(state, 512)
        for tasks in (0, -1, 2049, True):
            with self.assertRaises(guard.GuardError):
                policy.admit_tasks({'jobs': {}}, tasks)

    def test_pid_queue_skips_unfittable_request_without_blocking_smaller_one(self):
        import resource_policy as policy
        state = {'jobs': {'running': {'tasks': 1792}}, 'queue': [
            {'id': 'ui', 'tasks': 512, 'deadline': 100, 'keys': [], 'enqueued_at': 0, 'required': G, 'goal': 'a'},
            {'id': 'small', 'tasks': 256, 'deadline': 100, 'keys': [], 'enqueued_at': 1, 'required': G, 'goal': 'b'}]}
        self.assertEqual(policy.queue_choice(state, 2 * G, set(), 2), 'small')
        state['jobs']['running']['tasks'] = 2048
        self.assertIsNone(policy.queue_choice(state, 2 * G, set(), 2))

    def test_registry_keeps_pid_measurements_and_rejects_overcommit(self):
        reservation = {**job(), 'tasks': 512, 'pids_peak': 107, 'pids_events': 0}
        state = {'budget': 6 * G, 'jobs': {SCOPE: reservation},
                 'history': {'a' * 64: [{'seconds': 1, 'peak': 0, 'exit': 0, 'pids_peak': 107, 'pids_events': 0}]}}
        guard.validate_state(state)
        invalid = copy.deepcopy(state)
        invalid['jobs'][SCOPE]['tasks'] = 2049
        with self.assertRaises(guard.GuardError):
            guard.validate_state(invalid)
        invalid = copy.deepcopy(state)
        invalid['history']['a' * 64][0]['pids_peak'] = -1
        with self.assertRaises(guard.GuardError):
            guard.validate_state(invalid)

    def test_ui_kernel_cap_is_verified_not_merely_requested(self):
        fixture = CapsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.root / 'cpu.max').write_text(f'{guard.CPU_COUNT * 100000} 100000')
        (fixture.root / 'pids.max').write_text('512')
        guard.verify_caps(fixture.backend, SCOPE, 6 * G, True, tasks=512, policy_version=2)
        with self.assertRaises(guard.GuardError):
            guard.verify_caps(fixture.backend, SCOPE, 6 * G, True, tasks=256, policy_version=2)

    def test_nested_command_cannot_request_a_larger_task_cap(self):
        from contextlib import contextmanager
        @contextmanager
        def unlocked():
            yield
        registry = unittest.mock.Mock()
        registry.lock = unlocked
        registry.load.return_value = {'jobs': {SCOPE: {'limit': G, 'tasks': 256}}}
        with patch.object(sys, 'argv', ['guarded-run', '--tasks', '512', '--', '/usr/bin/true']), \
                patch.object(guard, 'current_cgroup', return_value='/omp-heavy.slice/' + SCOPE), \
                patch.object(guard, 'assert_guarded', return_value=SCOPE), \
                patch.object(guard, 'Registry', return_value=registry):
            with self.assertRaisesRegex(guard.GuardError, 'task'):
                guard.main()


class CollectedCgroupTests(unittest.TestCase):
    def test_inactive_collected_scope_has_no_root(self):
        backend = guard.Systemd()
        with patch.object(backend, 'info', return_value={'ActiveState': 'inactive', 'ControlGroup': ''}):
            self.assertIsNone(backend.scope_root(SCOPE))

    def test_active_scope_without_accounting_stays_fail_closed(self):
        backend = guard.Systemd()
        with patch.object(backend, 'info', return_value={'ActiveState': 'active', 'ControlGroup': ''}):
            with self.assertRaisesRegex(guard.GuardError, 'accounting'):
                backend.scope_root(SCOPE)

    def test_scope_collected_between_info_and_read_is_rechecked(self):
        backend = guard.Systemd()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(backend, 'info', side_effect=[
                    {'ActiveState': 'active', 'ControlGroup': '/gone'},
                    {'ActiveState': 'inactive', 'ControlGroup': ''}]), \
                patch.object(guard, 'cgroup_root', return_value=Path(temporary) / 'gone'):
            self.assertIsNone(backend.scope_root(SCOPE))

    def test_cleanup_stops_scope_before_reaping_launcher(self):
        import resource_executor as executor
        events = []
        backend = unittest.mock.Mock()
        backend.populated.side_effect = [True, False]
        backend.stop.side_effect = lambda unit: events.append('stop')
        with patch.object(executor.os, 'waitpid', side_effect=lambda *args: (events.append('reap') or (123, 0))):
            executor.cleanup_launcher(backend, guard, SCOPE, 123, 1)
        self.assertEqual(events, ['stop', 'reap'])


class NativeGuardRuntimeTests(unittest.TestCase):
    def test_actual_scope_caps_match_the_durable_profile(self):
        import json
        import time
        unit = guard.assert_guarded()
        registry = guard.Registry()
        with registry.lock():
            record = registry.load()['jobs'][unit]
        root = guard.cgroup_root(guard.current_cgroup())
        tasks = int((root / 'pids.max').read_text())
        self.assertEqual(tasks, record['tasks'])
        self.assertLessEqual(tasks, guard.PARENT_PIDS)
        self.assertEqual((root.parent / 'pids.max').read_text().strip(), str(guard.PARENT_PIDS))
        print(json.dumps({'event': 'native-profile-verified', 'unit': unit, 'tasks': tasks,
                          'parent_tasks': guard.PARENT_PIDS}), flush=True)
        # Keep the native fixture alive for one controller sample.
        time.sleep(.6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
