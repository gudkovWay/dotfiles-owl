"""Shared adaptive heavy-job budget with verified per-job and parent cgroup caps."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from resource_policy import (
    GuardError, Busy, MAX_JOBS, CPU_COUNT, PARENT_PIDS, DEFAULT_TASKS, admit_tasks,
    available_budget, reservation_headroom, admission, allocate_memory,
)

GIB = 1024 ** 3
STEP = 256 * 1024 ** 2
DEFAULT_MEMORY = 2 * GIB
DEFAULT_RUNTIME = 600
POLICY_VERSION = 2
SLICE = 'omp-heavy.slice'
SCOPE_RE = re.compile(r'omp-heavy-job-[0-9a-f]{32}\.scope\Z')
HEAP_RE = re.compile(r'--max[-_]old[-_]space[-_]size(?:=|\s+)(\d+)')
ACTIVE = {'active', 'activating', 'deactivating', 'reloading'}
HEAVY = {'vitest', 'playwright', 'jest', 'pytest', 'vue-tsc', 'nuxt', 'nuxi',
         'esbuild', 'tsc', 'cargo', 'vite', 'rollup', 'node-gyp', 'cmake', 'ninja', 'make'}
COMMON = (f'CPUQuota={CPU_COUNT * 100}%', 'CPUWeight=20', 'MemorySwapMax=0',
          'IOWeight=20')




def parse_memory(value):
    match = re.fullmatch(r'(\d+)([KMGT]?)(?:I?B)?', value.upper())
    if not match:
        raise ValueError('memory must be a positive byte size, e.g. 512M or 3G')
    amount = int(match[1]) * 1024 ** ('KMGT'.find(match[2]) + 1 if match[2] else 0)
    if amount <= 0:
        raise ValueError('memory must be positive; admission enforces the fresh shared budget')
    return amount


def node_heap_limit(limit):
    # Leave 25% of the scope for native allocations, stacks and child processes.
    heap = limit * 3 // 4 // (1024 ** 2)
    if heap < 1:
        raise GuardError('memory limit is too small for a bounded Node heap')
    return heap


def node_options(value, limit=DEFAULT_MEMORY):
    limits = [int(x) for x in HEAP_RE.findall(value)]
    if any(size <= 0 for size in limits):
        raise GuardError('Node heap limit must be positive')
    remainder = HEAP_RE.sub('', value).strip()
    shlex.split(remainder)
    return (remainder + ' ' if remainder else '') + f'--max-old-space-size={min([node_heap_limit(limit)] + limits)}'


def validate_node_command(command, limit):
    maximum = node_heap_limit(limit)
    if any(not 0 < int(value) <= maximum for value in HEAP_RE.findall(' '.join(command))):
        raise GuardError(f'command overrides the admitted Node heap budget ({maximum} MiB)')




def claim_key(state, unit, key):
    if any(name != unit and key in job['keys'] for name, job in state['jobs'].items()):
        raise Busy(f'environment_busy: {key}')
    keys = state['jobs'][unit]['keys']
    if key not in keys:
        keys.append(key)


def pid_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else int(fields[19])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError) as exc:
        raise GuardError(f'cannot inspect process identity {pid}: {exc}') from exc


def current_cgroup():
    for line in Path('/proc/self/cgroup').read_text().splitlines():
        if line.startswith('0::'):
            return line[3:]
    raise GuardError('cgroup v2 membership unavailable')


def cgroup_root(relative):
    path = Path('/sys/fs/cgroup') / relative.lstrip('/')
    if not relative.startswith('/') or '..' in Path(relative).parts:
        raise GuardError('invalid cgroup path')
    return path



def validate_state(state):
    if not isinstance(state, dict) or not {'budget', 'jobs'}.issubset(state) or not set(state).issubset(
            {'budget', 'jobs', 'queue', 'history', 'last_goal', 'policy_version'}):
        raise GuardError('invalid resource registry schema')
    if type(state['budget']) is not int or state['budget'] < 0 or state['budget'] % STEP:
        raise GuardError('invalid resource registry budget')
    jobs = state['jobs']
    if not isinstance(jobs, dict) or len(jobs) > MAX_JOBS:
        raise GuardError('invalid resource registry jobs')
    for name, job in jobs.items():
        if not SCOPE_RE.fullmatch(name) or not isinstance(job, dict):
            raise GuardError('invalid resource registry scope')
        fields = {'limit', 'pid', 'start', 'launcher_pid', 'launcher_start', 'keys'}
        if not fields.issubset(job) or not set(job).issubset(fields | {
                'runtime', 'memory_high', 'policy_version', 'ceiling', 'elastic',
                'pending_limit', 'pending_high', 'started_at', 'workload', 'last_reclaim',
                'last_sample', 'last_usage', 'goal', 'peak', 'deadline',
                'tasks', 'pids_peak', 'pids_events'}):
            raise GuardError('invalid resource registry reservation')
        tasks = job.get('tasks', DEFAULT_TASKS)
        if type(tasks) is not int or not 1 <= tasks <= PARENT_PIDS:
            raise GuardError('invalid resource registry task cap')
        for metric in ('pids_peak', 'pids_events'):
            if metric in job and (type(job[metric]) is not int or job[metric] < 0):
                raise GuardError('invalid resource registry PID metric')
        runtime = job.get('runtime', DEFAULT_RUNTIME)
        if runtime != 'infinity' and (type(runtime) is not int or not 1 <= runtime <= 28800):
            raise GuardError('invalid resource registry runtime')
        if job.get('policy_version', 1) not in (1, 2):
            raise GuardError('invalid reservation policy')
        if ('pending_limit' in job) != ('pending_high' in job):
            raise GuardError('incomplete growth reservation')
        for field in ('pending_limit', 'ceiling'):
            if field in job and (type(job[field]) is not int or
                                 type(job['limit']) is not int or job[field] < job['limit']):
                raise GuardError('invalid growth reservation')
        if 'pending_high' in job and (type(job['pending_high']) is not int or
                                     not 0 < job['pending_high'] <= job['pending_limit']):
            raise GuardError('invalid pending soft threshold')
        if 'elastic' in job and type(job['elastic']) is not bool:
            raise GuardError('invalid elasticity flag')
        if type(job['limit']) is not int or job['limit'] <= 0:
            raise GuardError('invalid resource registry memory limit')
        if 'memory_high' in job and (
                type(job['memory_high']) is not int or not 0 < job['memory_high'] <= job['limit']):
            raise GuardError('invalid resource registry soft memory threshold')
        for field in ('pid', 'start', 'launcher_pid', 'launcher_start'):
            if type(job[field]) is not int or job[field] < 0:
                raise GuardError('invalid resource registry process identity')
        if not job['pid'] or not job['start']:
            raise GuardError('missing reservation owner identity')
        if not isinstance(job['keys'], list) or any(
                not isinstance(key, str) or not key.startswith('/') for key in job['keys']):
            raise GuardError('invalid resource registry environment keys')
    if sum(max(job['limit'], job.get('pending_limit', 0)) for job in jobs.values()) > state['budget']:
        raise GuardError('resource registry is overcommitted')
    if sum(job.get('tasks', DEFAULT_TASKS) for job in jobs.values()) > PARENT_PIDS:
        raise GuardError('resource registry PID budget is overcommitted')
    for field in ('queue',):
        entries = state.get(field, [])
        if not isinstance(entries, list) or len(entries) > 128:
            raise GuardError('invalid admission queue')
        identities = set()
        for entry in entries:
            if not isinstance(entry, dict) or not {
                    'id', 'pid', 'start', 'goal', 'enqueued_at', 'deadline', 'required', 'keys'
            }.issubset(entry) or set(entry) - {
                    'id', 'pid', 'start', 'goal', 'enqueued_at', 'deadline', 'required', 'keys', 'tasks'}:
                raise GuardError('invalid admission queue entry')
            if type(entry.get('tasks', DEFAULT_TASKS)) is not int or not 1 <= entry.get('tasks', DEFAULT_TASKS) <= PARENT_PIDS:
                raise GuardError('invalid queued task cap')
            if not isinstance(entry['id'], str) or not SCOPE_RE.fullmatch(entry['id']) or entry['id'] in identities:
                raise GuardError('invalid queue identity')
            identities.add(entry['id'])
            if any(type(entry[k]) is not int or entry[k] <= 0 for k in ('pid', 'start', 'required')):
                raise GuardError('invalid queue reservation')
            if any(type(entry[k]) not in (int, float) or not math.isfinite(entry[k])
                   for k in ('enqueued_at', 'deadline')):
                raise GuardError('invalid queue deadline')
            if not isinstance(entry['goal'], str) or not isinstance(entry['keys'], list) or any(
                    not isinstance(key, str) or not key.startswith('/') for key in entry['keys']):
                raise GuardError('invalid queue scope')
    history = state.get('history', {})
    if not isinstance(history, dict) or len(history) > 256:
        raise GuardError('invalid workload history')
    for digest, entries in history.items():
        if not re.fullmatch('[a-f0-9]{64}', digest) or not isinstance(entries, list) or len(entries) > 20:
            raise GuardError('invalid workload history entry')
        for entry in entries:
            if not isinstance(entry, dict) or not {'seconds', 'peak', 'exit'}.issubset(entry) or set(entry) - {'seconds', 'peak', 'exit', 'pids_peak', 'pids_events'} or (
                    type(entry['seconds']) not in (int, float) or not math.isfinite(entry['seconds']) or
                    entry['seconds'] < 0 or type(entry['peak']) is not int or entry['peak'] < 0 or
                    (entry['exit'] is not None and type(entry['exit']) is not int)):
                raise GuardError('invalid workload measurement')
            for metric in ('pids_peak', 'pids_events'):
                if metric in entry and (type(entry[metric]) is not int or entry[metric] < 0):
                    raise GuardError('invalid workload PID measurement')


class Registry:
    def __init__(self, runtime=None):
        self.runtime = Path(runtime) if runtime else Path(f'/run/user/{os.getuid()}')
        self.directory = self.runtime / 'omp-heavy-jobs'
        self.directory.mkdir(mode=0o700, exist_ok=True)
        for path in (self.runtime, self.directory):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise GuardError(f'unsafe resource registry directory: {path}')
        self.state_path = self.directory / 'registry.json'
        # Keep the original inode shared with old executors during cutover.
        self.lock_path = self.runtime / 'omp-heavy-jobs.lock'

    @contextmanager
    def lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise GuardError('unsafe resource lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy('resource_busy: admission lock occupied') from exc
            yield fd
        finally:
            os.close(fd)


    def load(self):
        try:
            fd = os.open(self.state_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return {'budget': 0, 'jobs': {}}
        except OSError as exc:
            raise GuardError(f'cannot open resource registry: {exc}') from exc
        try:
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise GuardError('unsafe resource registry file')
                state = json.load(stream)
            validate_state(state)
            return state
        except (ValueError, TypeError) as exc:
            raise GuardError(f'invalid resource registry: {exc}') from exc

    def save(self, state):
        validate_state(state)
        fd, name = tempfile.mkstemp(prefix='registry-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.state_path)
        finally:
            Path(name).unlink(missing_ok=True)


class Systemd:
    def command(self, *args):
        try:
            return subprocess.check_output(['systemctl', '--user', *args], text=True,
                                           stderr=subprocess.PIPE, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GuardError(f'systemd control-plane failed: {exc}') from exc

    def info(self, unit):
        output = self.command('show', unit, '--property=LoadState,ActiveState,ControlGroup,'
                              'CPUWeight,IOWeight,RuntimeMaxUSec,OOMPolicy,Result')
        values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if not values.get('ActiveState') or not values.get('LoadState'):
            raise GuardError(f'cannot inspect {unit}')
        return values

    def units(self):
        output = self.command('list-units', '--all', '--plain', '--no-legend',
                              'omp-heavy-job*.scope')
        return [line.split()[0] for line in output.splitlines() if line.strip()]

    def alive(self, pid, start):
        return bool(pid and start and pid_identity(pid) == start)

    def populated(self, unit):
        info = self.info(unit)
        if info.get('ControlGroup'):
            root = cgroup_root(info['ControlGroup'])
            try:
                events = dict(line.split() for line in (root / 'cgroup.events').read_text().splitlines())
            except FileNotFoundError:
                # A collected cgroup may disappear between show and read.
                refreshed = self.info(unit)
                if refreshed['ActiveState'] not in ACTIVE and not refreshed.get('ControlGroup'):
                    return False
                raise GuardError(f'cannot verify scope population: {unit}')
            if events.get('populated') == '1':
                return True
            if events.get('populated') != '0':
                raise GuardError(f'invalid scope population: {unit}')
        return info['ActiveState'] in ACTIVE

    def scope_root(self, unit):
        info = self.info(unit)
        if info.get('ControlGroup'):
            root = cgroup_root(info['ControlGroup'])
            if (root / 'memory.current').exists():
                return root
            info = self.info(unit)
        if info['ActiveState'] not in ACTIVE and not info.get('ControlGroup'):
            return None
        raise GuardError('live scope accounting unavailable: ' + unit)

    def memory_usage(self, unit):
        root = self.scope_root(unit)
        if root is None:
            return 0
        try:
            current = int((root / 'memory.current').read_text())
            stats = dict(line.split() for line in (root / 'memory.stat').read_text().splitlines())
            # Reclaimable cache is not guaranteed consumed reservation space.
            cache = max(0, int(stats['file']) - int(stats['shmem'])) + int(stats['slab_reclaimable'])
            return max(0, current - cache)
        except FileNotFoundError as exc:
            if self.scope_root(unit) is None:
                return 0
            raise GuardError('live memory accounting unavailable: ' + unit) from exc
        except (OSError, ValueError, KeyError) as exc:
            raise GuardError('live memory accounting unavailable: ' + unit) from exc


    def configure_slice(self, budget):
        self.command('set-property', '--runtime', SLICE, *COMMON,
                     f'TasksMax={PARENT_PIDS}', f'MemoryHigh={budget}', f'MemoryMax={budget}')

    def stop(self, unit):
        self.command('stop', unit)

    def infrastructure(self):
        if not {'cpu', 'memory', 'pids'}.issubset(
                Path('/sys/fs/cgroup/cgroup.controllers').read_text().split()):
            raise GuardError('cgroup v2 cpu/memory/pids controllers unavailable')
        self.command('show-environment')
        if self.populated('omp-heavy-job.scope'):
            raise Busy('resource_busy: legacy fixed scope still active; cutover waits for its owner')


def reconcile(state, backend):
    unknown = set(backend.units()) - set(state['jobs'])
    if unknown:
        raise GuardError('unregistered guarded scopes: ' + ', '.join(sorted(unknown)))
    for unit, job in list(state['jobs'].items()):
        if not (backend.alive(job['pid'], job['start']) or
                backend.alive(job['launcher_pid'], job['launcher_start']) or backend.populated(unit)):
            del state['jobs'][unit]


def runtime_matches(value, seconds):
    if seconds == 'infinity':
        return value == 'infinity'
    if not isinstance(value, str):
        return False
    if value.isdigit():
        return int(value) == seconds*1000000
    units = {'d': 86400000000, 'h': 3600000000, 'min': 60000000,
             's': 1000000, 'ms': 1000, 'us': 1}
    parts = re.findall(r'(\d+)(min|ms|us|d|h|s)', value)
    if not parts or ''.join(n+unit for n, unit in parts) != value.replace(' ', ''):
        return False
    return sum(int(n)*units[unit] for n, unit in parts) == seconds*1000000


def verify_caps(backend, unit, memory, timed, runtime=DEFAULT_RUNTIME, memory_high=None, policy_version=1, tasks=DEFAULT_TASKS):
    info = backend.info(unit)
    if info['ActiveState'] not in ACTIVE or not info.get('ControlGroup'):
        raise GuardError(f'resource cgroup is not active: {unit}')
    root = cgroup_root(info['ControlGroup'])
    try:
        high = memory * 2 // 3 if memory_high is None else memory_high
        if not timed and policy_version == 2:
            high = memory
        expected_tasks = PARENT_PIDS if not timed and policy_version == 2 else tasks
        for name, expected in {'memory.high': high, 'memory.max': memory,
                               'memory.swap.max': 0, 'pids.max': expected_tasks}.items():
            actual = (root / name).read_text().strip()
            # Kernel rounds memory byte thresholds to pages, not task counts.
            if name in {'memory.high', 'memory.max'}:
                expected = expected // os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PAGE_SIZE')
            if actual != str(expected):
                raise GuardError(f'{unit}: {name} cap not applied ({actual})')
        quota, period = (root / 'cpu.max').read_text().split()
        if quota == 'max' or int(quota) != (CPU_COUNT if policy_version == 2 else 2) * int(period):
            raise GuardError(f'{unit}: CPUQuota cap not applied')
        if info.get('CPUWeight') != '20' or info.get('IOWeight') != '20':
            raise GuardError(f'{unit}: CPU/IO priority not applied')
        if timed:
            if not runtime_matches(info.get('RuntimeMaxUSec'), runtime) or info.get('OOMPolicy') != 'kill':
                raise GuardError(f'{unit}: runtime/OOM policy not applied')
    except (OSError, ValueError) as exc:
        raise GuardError(f'cannot verify {unit} caps: {exc}') from exc
    return info['ControlGroup']


def context_from_state(state, backend, relative):
    unit = next((part for part in Path(relative).parts if SCOPE_RE.fullmatch(part)), None)
    if unit not in state['jobs']:
        raise GuardError('internal execution requires a registered guarded scope')
    job = state['jobs'][unit]
    if 'pending_limit' in job:
        raise Busy('growth_transition: scope caps are being reconciled')
    version = job.get('policy_version', 1)
    scope = verify_caps(backend, unit, job['limit'], True,
                        runtime=job.get('runtime', DEFAULT_RUNTIME),
                        memory_high=job.get('memory_high'), policy_version=version,
                        tasks=job.get('tasks', DEFAULT_TASKS))
    parent = verify_caps(backend, SLICE, state['budget'], False,
                         policy_version=state.get('policy_version', 1))
    if not scope.startswith(parent + '/') or not (relative == scope or relative.startswith(scope + '/')):
        raise GuardError('scope/cgroup/registry membership mismatch')
    return unit


def assert_guarded():
    relative = current_cgroup()
    if not any(SCOPE_RE.fullmatch(part) for part in Path(relative).parts):
        raise GuardError('internal execution requires a guarded scope')
    registry, backend = Registry(), Systemd()
    deadline = time.monotonic() + 5
    while True:
        try:
            with registry.lock():
                return context_from_state(registry.load(), backend, relative)
        except Busy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def reserve_environment(root, wait=60):
    """Reserve a writable environment for this whole scope; nesting is reentrant."""
    key = str(Path(root).resolve(strict=True))
    registry, backend = Registry(), Systemd()
    relative = current_cgroup()
    deadline = time.monotonic() + wait
    while True:
        try:
            with registry.lock():
                state = registry.load()
                reconcile(state, backend)
                unit = context_from_state(state, backend, relative)
                claim_key(state, unit, key)
                registry.save(state)
            break
        except Busy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def ancestors():
    result = set()
    pid = os.getpid()
    while pid > 1 and pid not in result:
        result.add(pid)
        try:
            pid = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
        except FileNotFoundError:
            break
    return result


def heavy_processes(backend, jobs):
    own = ancestors()
    roots = [backend.info(unit).get('ControlGroup') for unit in jobs]
    roots = [root for root in roots if root]
    found = []
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        pid = int(path.parent.name)
        if pid in own:
            continue
        try:
            args = path.read_bytes().decode(errors='replace').strip('\0').split('\0')
        except FileNotFoundError:
            continue
        if not args or not args[0]:
            continue
        words = {Path(a).name.removesuffix('.js').removesuffix('.mjs').removesuffix('.cjs')
                 for a in args[:3] if not a.startswith('-') and not any(c.isspace() for c in a)}
        package = bool(words & {'npm', 'npm-cli', 'pnpm', 'yarn', 'bun'})
        install = package and any(a in {'install', 'ci'} for a in args[1:])
        run = package and any(a.split(':', 1)[0] in {'test', 'build', 'prepare', 'dev', 'typecheck'}
                              for a in args[1:5])
        native_test = Path(args[0]).name in {'node', 'bun'} and any(
            a == '--test' or a.startswith('--test=') or a == 'test' for a in args[1:3])
        go_test = Path(args[0]).name == 'go' and 'test' in args[1:]
        if not (HEAVY & words or install or run or native_test or go_test):
            continue
        try:
            relative = next(line[3:] for line in path.with_name('cgroup').read_text().splitlines()
                            if line.startswith('0::'))
        except FileNotFoundError:
            continue
        except StopIteration as exc:
            raise GuardError(f'cannot classify heavy process {pid}') from exc
        if not any(relative == root or relative.startswith(root + '/') for root in roots):
            found.append(f'{pid}: ' + shlex.join(args)[:500])
    return found


def mem_available():
    memory = Path('/proc/meminfo').read_text()
    match = re.search(r'^MemAvailable:\s+(\d+)', memory, re.M)
    if not match:
        raise GuardError('MemAvailable unavailable')
    return int(match[1]) * 1024


def scope_command(unit, limit, command, options, runtime=DEFAULT_RUNTIME, memory_high=None, tasks=DEFAULT_TASKS):
    duration = 'infinity' if runtime == 'infinity' else f'{runtime}s'
    high = limit * 2 // 3 if memory_high is None else memory_high
    properties = (*COMMON, f'TasksMax={tasks}', f'MemoryHigh={high}', f'MemoryMax={limit}',
                  f'RuntimeMaxSec={duration}', 'OOMPolicy=kill')
    return ['systemd-run', '--user', '--scope', f'--unit={unit}', '--collect',
            f'--slice={SLICE}', '--expand-environment=no',
            *[item for prop in properties for item in ('-p', prop)], '--', 'nice', '-n', '10',
            'env', 'NODE_OPTIONS=' + options, sys.executable, str(Path(__file__).resolve()),
            '--inside', '--', *command]


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def start_launcher(registry, lock_fd, state, unit, command):
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(write_fd)
        os.close(lock_fd)
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            allowed = os.read(read_fd, 1) == b'1'
            os.close(read_fd)
            if allowed:
                os.execvp(command[0], command)
            os._exit(1)
        except BaseException as exc:
            print(f'guarded-run: launcher failed: {exc}', file=sys.stderr, flush=True)
            os._exit(1)
    os.close(read_fd)
    published = False
    try:
        job = state['jobs'][unit]
        job['launcher_pid'], job['launcher_start'] = pid, pid_identity(pid)
        if not job['launcher_start']:
            raise GuardError('launcher exited before reservation publication')
        # Publish launcher identity BEFORE it can create a scope. EOF aborts an
        # orphaned gated child, closing the death-before-scope-creation race.
        registry.save(state)
        os.write(write_fd, b'1')
        published = True
    finally:
        os.close(write_fd)
        if not published:
            os.waitpid(pid, 0)
    return pid


def release(registry, backend, unit):
    deadline = time.monotonic() + 5
    while backend.populated(unit):
        if time.monotonic() >= deadline:
            raise GuardError('owned scope still live; reservation retained: ' + unit)
        time.sleep(0.05)
    while True:
        try:
            with registry.lock():
                state = registry.load()
                state['jobs'].pop(unit, None)
                registry.save(state)
            return
        except Busy:
            if time.monotonic() >= deadline:
                raise GuardError('cannot release reservation; retained for reconciliation')
            time.sleep(0.05)


def execute(args, command, options):
    from resource_executor import execute as run
    return run(args, command, options, sys.modules[__name__])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory', type=parse_memory, metavar='SIZE',
                        help='exact fixed maximum; omitted uses expected memory plus a dynamic buffer')
    parser.add_argument('--need', type=parse_memory, help='expected peak RAM, before the dynamic buffer')
    parser.add_argument('--tasks', type=int, help='fixed process/thread cap, reserved within parent budget')
    parser.add_argument('--elastic', action='store_true', help='permit admitted live growth before OOM')
    parser.add_argument('--ceiling', type=parse_memory, help='elastic authority ceiling, not a reservation')
    parser.add_argument('--goal-ticket', help='broker-issued descendant ticket file')
    parser.add_argument('--runtime', type=int, default=DEFAULT_RUNTIME)
    parser.add_argument('--job-id', help='stable idempotency key for a supervised request')
    parser.add_argument('--gpu-key', help='exclusive GPU/display resource name')
    parser.add_argument('--status', action='store_true', help='show owned queue and active accounting')
    parser.add_argument('--approved-double', action='store_true',
                        help='after explicit owner approval, double requested memory and the 10-minute runtime')
    parser.add_argument('--approved-no-timeout', action='store_true',
                        help='after explicit owner approval for this build, disable only its runtime timeout')
    parser.add_argument('--wait', type=int, default=60, metavar='SECONDS')
    parser.add_argument('--admission-windows', type=int, choices=(1, 2), default=1,
                        help='bounded pre-exec admission windows; never retries a started workload')
    parser.add_argument('--exclusive-key', metavar='PATH')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check-inside', action='store_true')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    explicit_memory = args.memory is not None
    if args.tasks is not None:
        admit_tasks({'jobs': {}}, args.tasks)
    if args.status:
        registry = Registry()
        with registry.lock():
            print(json.dumps(registry.load()))
        return 0
    if args.wait < 0 or not 1 <= args.runtime <= 28800:
        parser.error('invalid wait/runtime')
    if (args.wait > 60 or args.runtime > DEFAULT_RUNTIME) and not args.goal_ticket:
        parser.error('long wait/runtime requires a broker-issued goal ticket')
    if args.elastic and (not args.ceiling or args.ceiling < (args.memory or args.need or DEFAULT_MEMORY)):
        parser.error('--elastic requires a ceiling at least as large as initial need')
    if args.ceiling and not args.elastic:
        parser.error('--ceiling requires --elastic')
    if args.approved_double:
        if not explicit_memory:
            raise GuardError('--approved-double requires an explicit --memory base; adaptive maximum cannot be doubled')
        args.memory *= 2
        args.runtime *= 2
    if args.approved_no_timeout:
        args.runtime = 'infinity'
    if args.check_inside:
        print('guarded-run: verified ' + assert_guarded())
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a native command is required after --')
    options = os.environ.get('NODE_OPTIONS', '')
    relative = current_cgroup()
    nested = any(SCOPE_RE.fullmatch(part) for part in Path(relative).parts)
    if args.inside or nested:
        if args.approved_double or args.approved_no_timeout or args.elastic or args.goal_ticket:
            raise GuardError('nested command cannot extend memory/runtime or start a second goal')
        unit = assert_guarded()
        registry = Registry()
        with registry.lock():
            nested_job = registry.load()['jobs'][unit]
            limit = nested_job.get('ceiling', nested_job['limit']) if nested_job.get('elastic') else nested_job['limit']
        if args.tasks is not None and args.tasks > nested_job.get('tasks', DEFAULT_TASKS):
            raise GuardError('nested command cannot increase its task cap')
        if (explicit_memory and args.memory > limit) or (args.need and args.need > limit):
            raise GuardError('nested command cannot increase its reservation')
        validate_node_command(command, limit)
        options = node_options(options, limit)
        if args.dry_run:
            print('guarded-run: reuse ' + unit + '; ' + shlex.join(command))
            return 0
        if args.exclusive_key:
            reserve_environment(args.exclusive_key, args.wait)
        os.environ['NODE_OPTIONS'] = options
        print('guarded-run: cgroup caps verified; ' + unit, flush=True)
        print(json.dumps(dict(event='workload_start', job_id=unit, workload_started=True)), flush=True)
        os.execvp(command[0], command)
    if args.dry_run:
        available = mem_available()
        budget, limit, high = allocate_memory({'budget': 0, 'jobs': {}}, available, args.memory, {}, need=args.need)
        validate_node_command(command, limit)
        options = node_options(options, limit)
        duration = 'infinity' if args.runtime == 'infinity' else f'{args.runtime}s'
        print(f'guarded-run: MemAvailable={available} bytes; idle budget={budget}; '
              f'maximum={limit}; soft={high}; node-heap={options.rsplit("=", 1)[1]}MiB; '
              f'runtime={duration}; max-jobs={MAX_JOBS}; admission unverified')
        print(shlex.join(scope_command('omp-heavy-job-' + uuid.uuid4().hex + '.scope', limit,
                                      command, options, args.runtime, memory_high=high,
                                      tasks=args.tasks or DEFAULT_TASKS)))
        return 0
    return execute(args, command, options)


def cli():
    try:
        raise SystemExit(main())
    except GuardError as exc:
        kind = 'deferred' if isinstance(exc, Busy) else 'refusing'
        print(f'guarded-run: {kind}: {exc}', file=sys.stderr)
        raise SystemExit(exc.code)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'guarded-run: refusing: {exc}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    cli()
