"""Owned launch lifecycle: one registry, queued admission and pre-OOM growth."""
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

from resource_policy import (GIB, STEP, MAX_JOBS, DEFAULT_TASKS, admit_tasks, GuardError, Busy, allocate_memory,
    admission, free_capacity, enqueue, queue_choice, estimate_wait, pressure_action,
    jitter_margin, round_up)


def check_ticket(filename, cwd):
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise GuardError('unsafe goal ticket file')
        payload = json.load(stream)
    payload['cwd'] = str(Path(cwd).resolve())
    client = '/usr/local/lib/omp-owner-approval/client.py'
    result = subprocess.run([sys.executable, client, 'descendant_check', json.dumps(payload),
                             '--actor-pid', str(os.getpid())], text=True,
                            capture_output=True, timeout=10)
    if result.returncode:
        raise GuardError('goal authority expired/revoked/unavailable: ' + result.stderr[:200])
    return json.loads(result.stdout)


def reconcile_queue(state, backend, now):
    state['queue'] = [e for e in state.get('queue', [])
                      if e['deadline'] > now and backend.alive(e['pid'], e['start'])]


def recover_growth(state, backend, registry, base):
    """A published increase remains reserved until actual caps prove its state."""
    for unit, job in state['jobs'].items():
        if 'pending_limit' not in job:
            continue
        backend.configure_slice(state['budget'])
        base.verify_caps(backend, base.SLICE, state['budget'], False, policy_version=2)
        root = base.cgroup_root(backend.info(unit)['ControlGroup'])
        actual = int((root / 'memory.max').read_text())
        if actual not in (job['limit'], job['pending_limit']):
            raise GuardError('unknown memory growth state: ' + unit)
        if actual == job['pending_limit']:
            job['limit'] = actual
            high = job['pending_high']
            backend.command('set-property', '--runtime', unit, f'MemoryHigh={high}')
            job['memory_high'] = high
            base.verify_caps(backend, unit, actual, True, runtime=job['runtime'],
                             memory_high=high, policy_version=2, tasks=job.get('tasks', DEFAULT_TASKS))
        job.pop('pending_limit')
        job.pop('pending_high')
        registry.save(state)


def grow(state, backend, registry, base, unit, target, available, usage, jitter=0):
    job = state['jobs'][unit]
    if not job.get('elastic') or target <= job['limit']:
        return False
    target = min(round_up(target), job['ceiling']//STEP*STEP)
    delta = target-job['limit']
    if delta <= 0 or delta > free_capacity(state, available, usage, jitter):
        return False
    old_limit = job['limit']
    high = max(job['memory_high'], target-max(STEP, (target-usage[unit])//2))
    job['pending_limit'], job['pending_high'] = target, min(high, target)
    state['budget'] = max(state['budget'],
                          sum(max(j['limit'], j.get('pending_limit', 0)) for j in state['jobs'].values()))
    registry.save(state)
    # Any failure retains pending_limit. Never blindly shrink a process that
    # could already have consumed its increase.
    backend.configure_slice(state['budget'])
    base.verify_caps(backend, base.SLICE, state['budget'], False, policy_version=2)
    backend.command('set-property', '--runtime', unit, f'MemoryMax={target}')
    root = base.cgroup_root(backend.info(unit)['ControlGroup'])
    if int((root / 'memory.max').read_text()) != target:
        raise GuardError('growth MemoryMax readback failed')
    backend.command('set-property', '--runtime', unit, f'MemoryHigh={job["pending_high"]}')
    base.verify_caps(backend, unit, target, True, runtime=job['runtime'],
                     memory_high=job['pending_high'], policy_version=2, tasks=job.get('tasks', DEFAULT_TASKS))
    job['limit'], job['memory_high'] = target, job.pop('pending_high')
    job.pop('pending_limit')
    registry.save(state)
    print(json.dumps(dict(event='expanded', job_id=unit, previous=old_limit, memory=target)), flush=True)
    return True


def monitor(registry, backend, base, unit, samples):
    now = time.monotonic()
    with registry.lock():
        state = registry.load()
        recover_growth(state, backend, registry, base)
        job = state['jobs'][unit]
        root = backend.scope_root(unit)
        if root is None:
            return
        try:
            stats = dict(line.split() for line in (root / 'memory.stat').read_text().splitlines())
            used = backend.memory_usage(unit)
            if (root / 'pids.peak').exists():
                job['pids_peak'] = max(job.get('pids_peak', 0), int((root / 'pids.peak').read_text()))
            if (root / 'pids.events').exists():
                events = dict(line.split() for line in (root / 'pids.events').read_text().splitlines())
                job['pids_events'] = int(events.get('max', 0))
        except FileNotFoundError:
            if backend.scope_root(unit) is None:
                return
            raise
        available = base.mem_available()
        jitter = jitter_margin(samples, now, available)
        cache = max(0, int(stats['file'])-int(stats['shmem']))
        job['peak'] = max(job.get('peak', 0), used)
        age = now-job.get('last_reclaim', -1e9)
        action, amount = pressure_action(available, cache, age)
        if action == 'reclaim_cache':
            job['last_reclaim'] = now
            registry.save(state)
            try:
                # Owned file-cache only; swappiness=0 prevents swapping anonymous
                # application state. EAGAIN/unsupported reclaim is not retried.
                (root / 'memory.reclaim').write_text(f'{amount} swappiness=0')
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EINVAL, errno.EACCES, errno.ENOENT, errno.EPERM):
                    raise
            return
        dt = max(.1, now-job.get('last_sample', now))
        rate = max(0, used-job.get('last_usage', used))/dt
        job['last_sample'], job['last_usage'] = now, used
        if available >= GIB+jitter and job.get('elastic'):
            pressure = dict(line.split('=', 1) for line in
                            (root / 'memory.pressure').read_text().splitlines()[0].split()[1:])
            # A margin on measured growth gives the control plane time to react;
            # no guarantee is made for instantaneous allocations.
            target = round_up(used + max(STEP, int(rate*3), used*3//10))
            if used >= job['memory_high']-STEP or (float(pressure.get('avg10', 0)) > 1 and rate > 0):
                usage = {name: backend.memory_usage(name) for name in state['jobs']}
                if grow(state, backend, registry, base, unit, target, available, usage, jitter):
                    return
        registry.save(state)


def cleanup_launcher(backend, base, unit, launcher, launcher_start):
    if backend.populated(unit):
        backend.stop(unit)
    deadline = time.monotonic() + 5
    signalled = False
    while launcher:
        finished, _status = os.waitpid(launcher, os.WNOHANG)
        if finished:
            break
        if not signalled and backend.alive(launcher, launcher_start):
            os.kill(launcher, signal.SIGTERM)
            signalled = True
        if time.monotonic() >= deadline:
            if backend.alive(launcher, launcher_start):
                os.kill(launcher, signal.SIGKILL)
            raise GuardError('launcher cleanup deadline; reservation retained: ' + unit)
        time.sleep(.05)
    while backend.populated(unit):
        if time.monotonic() >= deadline:
            raise GuardError('owned scope still populated; reservation retained: ' + unit)
        time.sleep(.05)


def execute(args, command, options, base):
    registry, backend = base.Registry(), base.Systemd()
    cwd = str(Path.cwd().resolve())
    lease = check_ticket(args.goal_ticket, cwd) if args.goal_ticket else None
    authority = lease['request']['goal'] if lease else None
    if authority:
        resource = authority['resources']
        if args.elastic and not resource['elastic']:
            raise GuardError('elastic growth is outside goal authority')
        if args.gpu_key and not resource['gpu']:
            raise GuardError('GPU is outside goal authority')
        if any(value and value > resource['memory_ceiling']
               for value in (args.memory, args.need, args.ceiling)):
            raise GuardError('memory request exceeds goal authority')
        if args.runtime == 'infinity' or args.runtime > resource['runtime_seconds']:
            raise GuardError('runtime exceeds goal authority')
    start = time.monotonic()
    expires = start+lease['remaining_seconds'] if lease else float('inf')
    windows = getattr(args, 'admission_windows', 1)
    deadline = min(start + args.wait * windows, expires-(args.runtime if isinstance(args.runtime, int) else 0)-10)
    if deadline < start:
        raise GuardError('goal cannot accommodate runtime and cleanup')
    key = str(Path(args.exclusive_key).resolve(strict=True)) if args.exclusive_key else None
    keys = ([key] if key else []) + (['/gpu/host'] if args.gpu_key else [])
    identifier = args.job_id or uuid.uuid4().hex
    if not all(c in '0123456789abcdef' for c in identifier) or len(identifier) != 32:
        raise GuardError('job-id must be 32 lowercase hexadecimal characters')
    unit = 'omp-heavy-job-' + identifier + '.scope'
    digest = hashlib.sha256((cwd+'\0'+json.dumps(command)).encode()).hexdigest()
    goal = authority['goal_id'] if authority else str(os.getppid())
    signal.signal(signal.SIGTERM, base.interrupt)
    launcher, launcher_start, reserved, exit_status = None, 0, False, None
    samples, last_print, last_check = [], None, start
    tasks = args.tasks or DEFAULT_TASKS
    try:
        while True:
            now = time.monotonic()
            if now > expires-10:
                raise GuardError('goal expired before admission')
            if lease and now-last_check >= 5:
                check_ticket(args.goal_ticket, cwd)
                last_check = now
            try:
                with registry.lock() as lock_fd:
                    backend.infrastructure()
                    state = registry.load()
                    base.reconcile(state, backend)
                    reconcile_queue(state, backend, now)
                    if unit in state['jobs']:
                        raise GuardError('job-id already running; do not submit duplicate work')
                    if any(j.get('policy_version', 1) != 2 for j in state['jobs'].values()):
                        raise Busy('cutover: waiting for legacy scopes to drain without changing their caps')
                    if any('tasks' not in job for job in state['jobs'].values()):
                        raise Busy('cutover: waiting for pre-PID-accounting controllers to drain')
                    recover_growth(state, backend, registry, base)
                    available = base.mem_available()
                    jitter = jitter_margin(samples, now, available)
                    usage = {name: backend.memory_usage(name) for name in state['jobs']}
                    need = args.need
                    history = state.get('history', {}).get(digest, [])
                    if args.memory is None and history:
                        need = max(need or base.DEFAULT_MEMORY,
                                   max(h['peak'] for h in history if h['exit'] == 0) if any(h['exit'] == 0 for h in history) else 0)
                    required = args.memory or round_up(need or base.DEFAULT_MEMORY)+STEP
                    physical = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                                        if line.startswith('MemTotal:')))*1024
                    if required > physical-GIB:
                        raise GuardError('impossible_memory_request: exceeds physical safe capacity')
                    enqueue(state, dict(id=unit, pid=os.getpid(), start=base.pid_identity(os.getpid()),
                            goal=goal, enqueued_at=start, deadline=max(deadline, now+10), required=required, keys=keys, tasks=tasks))
                    state['policy_version'] = 2
                    registry.save(state)
                    free = free_capacity(state, available, usage, jitter)
                    occupied = {k for j in state['jobs'].values() for k in j['keys']}
                    chosen = queue_choice(state, free, occupied, now)
                    if chosen != unit:
                        admit_tasks(state, tasks)
                        eta = estimate_wait(state, unit, free, now)
                        raise Busy('queued: eta=' + ('unknown' if eta is None else str(eta)))
                    admit_tasks(state, tasks)
                    budget, limit, high = allocate_memory(state, available, args.memory, usage, need=need, jitter=jitter)
                    if authority and limit > authority['resources']['memory_ceiling']:
                        raise GuardError('buffered memory exceeds goal authority; lower --need or use fixed --memory')
                    if args.elastic and limit > args.ceiling:
                        raise GuardError('initial buffered maximum exceeds elastic ceiling')
                    ceiling = args.ceiling if args.elastic else limit
                    base.validate_node_command(command, ceiling)
                    admitted_options = base.node_options(options, ceiling)
                    if state['jobs']:
                        base.verify_caps(backend, base.SLICE, state['budget'], False, policy_version=2)
                    backend.configure_slice(budget)
                    state['budget'] = budget
                    state['queue'] = [e for e in state['queue'] if e['id'] != unit]
                    state['last_goal'] = goal
                    state['jobs'][unit] = dict(limit=limit, memory_high=high, pid=os.getpid(),
                        start=base.pid_identity(os.getpid()), launcher_pid=0, launcher_start=0,
                        keys=keys, runtime=args.runtime, policy_version=2, ceiling=ceiling,
                        elastic=args.elastic, started_at=now, workload=digest, goal=goal,
                        deadline=expires if lease else None, peak=0, tasks=tasks)
                    reserved = True
                    launcher = base.start_launcher(registry, lock_fd, state, unit,
                        base.scope_command(unit, limit, command, admitted_options, args.runtime,
                                           memory_high=high, tasks=tasks))
                    launcher_start = state['jobs'][unit]['launcher_start']
                print(json.dumps(dict(event='admitted', job_id=unit, memory=limit, ceiling=ceiling, tasks=tasks)), flush=True)
                break
            except Busy as exc:
                if time.monotonic() >= deadline:
                    raise
                reason = str(exc)
                if reason != last_print:
                    print(json.dumps(dict(event='queued', job_id=unit, reason=reason)), flush=True)
                    last_print = reason
                # ETA changes polling cadence, never the authority/wait deadline.
                # Keep revocation responsive even when completion time is unknown.
                delay = .5 if 'eta=' not in reason else 2
                if 'eta=' in reason:
                    try:
                        delay = max(.5, min(5, float(reason.rsplit('=', 1)[1])/8))
                    except ValueError:
                        pass
                time.sleep(min(delay, max(0, deadline-time.monotonic())))
        finish = min(expires, time.monotonic()+args.runtime+10) if isinstance(args.runtime, int) else expires
        while True:
            finished, status = os.waitpid(launcher, os.WNOHANG)
            if finished:
                exit_status = os.waitstatus_to_exitcode(status)
                break
            now = time.monotonic()
            if now >= finish:
                raise GuardError('owned goal/runtime deadline expired')
            if lease and now-last_check >= 5:
                check_ticket(args.goal_ticket, cwd)
                last_check = now
            try:
                if backend.populated(unit):
                    monitor(registry, backend, base, unit, samples)
            except Busy:
                pass  # Short admission-lock contention, not a workload retry.
            time.sleep(.5)
        launcher = None
        code = exit_status if exit_status >= 0 else 128-exit_status
        print(json.dumps(dict(event='completed', job_id=unit, exit=code,
                              admitted=True, workload_started=None)), flush=True)
        return code
    except Busy as exc:
        if not reserved and launcher is None:
            print(json.dumps(dict(event='deferred', job_id=unit, phase='admission',
                                  workload=digest, workload_started=False, admitted=False,
                                  reason=str(exc), admission_windows=windows)), flush=True)
        raise
    finally:
        if reserved:
            cleanup_launcher(backend, base, unit, launcher, launcher_start)
        end = time.monotonic()+5
        while True:
            try:
                with registry.lock():
                    state = registry.load()
                    if 'queue' in state:
                        state['queue'][:] = [e for e in state['queue'] if e['id'] != unit]
                    if reserved and not backend.populated(unit):
                        record = state['jobs'].pop(unit)
                        history = state.setdefault('history', {}).setdefault(digest, [])
                        measurement = dict(seconds=max(0, time.monotonic()-record['started_at']),
                                           peak=record.get('peak', 0), exit=exit_status)
                        measurement.update({key: record[key] for key in ('pids_peak', 'pids_events') if key in record})
                        history.append(measurement)
                        del history[:-20]
                        # Bounded metadata; no commands, credentials or payloads.
                        while len(state['history']) > 256:
                            del state['history'][next(iter(state['history']))]
                    if reserved or state.get('policy_version') == 2:
                        registry.save(state)
                break
            except Busy:
                if time.monotonic() >= end:
                    raise GuardError('cleanup lock unavailable; reservation retained')
                time.sleep(.1)
