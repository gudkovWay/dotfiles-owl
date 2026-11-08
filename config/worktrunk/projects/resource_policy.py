"""Deterministic resource decisions. No signals, host mutations or model calls."""
import math
import os
import statistics

GIB = 1024 ** 3
STEP = 256 * 1024 ** 2
DEFAULT_MEMORY = 2 * GIB
MAX_JOBS = 8
HOST_FLOOR = GIB
CPU_COUNT = max(1, (os.cpu_count() or 2) - 2)
PARENT_PIDS = MAX_JOBS * 256
DEFAULT_TASKS = 256
UI_TASKS = 512


def admit_tasks(state, requested):
    if type(requested) is not int or not 1 <= requested <= PARENT_PIDS:
        raise GuardError('invalid task cap; must be within parent PID budget')
    promised = sum(job.get('tasks', DEFAULT_TASKS) for job in state['jobs'].values())
    if promised + requested > PARENT_PIDS:
        raise Busy(f'pid_budget: requested={requested}; promised={promised}; parent={PARENT_PIDS}',
                   reason_code='pid_budget', requested_tasks=requested,
                   promised_tasks=promised, parent_tasks=PARENT_PIDS)


class GuardError(RuntimeError):
    code = 1


class Busy(GuardError):
    code = 75

    def __init__(self, message, *, reason_code='resource_busy', **details):
        super().__init__(message)
        self.details = dict(reason_code=reason_code, **details)


def round_up(value):
    return math.ceil(value / STEP) * STEP


def available_budget(available, jitter=0):
    if type(available) is not int or available < 0 or jitter < 0:
        raise GuardError('invalid MemAvailable accounting')
    return max(0, available - HOST_FLOOR - jitter) // STEP * STEP


def reservation_headroom(state, usage):
    jobs = state['jobs']
    if set(usage) != set(jobs) or any(type(v) is not int or v < 0 for v in usage.values()):
        raise GuardError('missing/invalid live memory accounting')
    return sum(max(0, max(j['limit'], j.get('pending_limit', 0)) - usage[name])
               for name, j in jobs.items())


def free_capacity(state, available, usage, jitter=0):
    return max(0, available_budget(available, jitter) - reservation_headroom(state, usage))


def admission(state, available, limit, usage=None, jitter=0):
    if type(limit) is not int or limit <= 0:
        raise GuardError('memory limit must be positive')
    if len(state['jobs']) >= MAX_JOBS:
        raise Busy('job_slots: all local job slots occupied', reason_code='job_slots')
    usage = {} if usage is None else usage
    free = free_capacity(state, available, usage, jitter)
    if limit > free:
        raise Busy(f'ram: requested={limit}; available-for-promises={free}; host-floor={HOST_FLOOR}',
                   reason_code='ram', required_bytes=limit, free_capacity_bytes=free)
    committed = sum(max(j['limit'], j.get('pending_limit', 0)) for j in state['jobs'].values())
    # Retain existing parent caps under foreign pressure; fresh admission still
    # checks every unused promise. An old low epoch is not a permanent ceiling.
    return max(state['budget'], round_up(committed + limit),
               (sum(usage.values()) + available_budget(available, jitter)) // STEP * STEP)


def allocate_memory(state, available, requested, usage, *, need=None, jitter=0):
    if requested is not None:
        limit = requested
        high = limit * 2 // 3
    else:
        peak = DEFAULT_MEMORY if need is None else need
        if type(peak) is not int or peak <= 0:
            raise GuardError('expected memory must be positive')
        free = free_capacity(state, available, usage, jitter)
        waiting = len(state.get('queue', []))
        desired = max(STEP, round_up(peak * 3 / 10))
        room = max(0, free - round_up(peak)) // (1 + waiting)
        buffer = min(desired, room // STEP * STEP)
        if buffer < STEP:
            raise Busy(f'ram: expected={peak}; insufficient safe buffer; free={free}',
                       reason_code='ram', required_bytes=round_up(peak) + STEP,
                       free_capacity_bytes=free)
        limit = round_up(peak) + buffer
        high = round_up(peak) + buffer // 2
    return admission(state, available, limit, usage, jitter), limit, high


def pressure_action(available, reclaimable, seconds_since_attempt):
    """Only file-cache reclaim or wait. Zero age denotes no previous attempt."""
    if available >= HOST_FLOOR or reclaimable <= 0:
        return 'wait', 0
    if seconds_since_attempt != 0 and seconds_since_attempt < 30:
        return 'wait', 0
    return 'reclaim_cache', min(STEP, reclaimable, HOST_FLOOR - available)


def jitter_margin(samples, now, available):
    """Largest recent observed drop, with bounded observation history, not RAM cap."""
    samples[:] = [(t, a) for t, a in samples if 0 <= now-t <= 10]
    drop = max([0] + [a-available for _, a in samples])
    samples.append((now, available))
    del samples[:-40]
    return round_up(drop)


def enqueue(state, entry):
    queue = state.setdefault('queue', [])
    previous = next((e for e in queue if e['id'] == entry['id']), None)
    if previous is not None:
        if any(previous[key] != entry[key] for key in ('pid', 'start', 'goal')):
            raise GuardError('queued job identity changed')
        previous.update(required=entry['required'], keys=list(entry['keys']),
                        tasks=entry.get('tasks', DEFAULT_TASKS),
                        deadline=min(previous['deadline'], entry['deadline']))
        return
    if len(queue) >= 128:
        raise Busy('queue_slots: pending queue is full', reason_code='queue_slots')
    queue.append(dict(entry))


def queue_choice(state, capacity, blocked_keys, now, request=None):
    queue = [e for e in state.get('queue', []) if e['deadline'] > now]
    target = next((e for e in queue if e['id'] == request), None)
    jobs = state['jobs']
    promised = sum(job.get('tasks', DEFAULT_TASKS) for job in jobs.values())
    pid_free = PARENT_PIDS - promised
    result = dict(selected=None, reason_code='queue_empty',
                  free_capacity_bytes=capacity,
                  required_bytes=target['required'] if target else None,
                  promised_tasks=promised, parent_tasks=PARENT_PIDS)
    if len(jobs) >= MAX_JOBS:
        return dict(result, reason_code='job_slots')
    eligible = sorted((e for e in queue if not blocked_keys.intersection(e['keys'])
                       and e.get('tasks', DEFAULT_TASKS) <= pid_free),
                      key=lambda e: (e['enqueued_at'], e['id']))
    selected, draining = None, None
    if eligible:
        first = eligible[0]
        age = now - first['enqueued_at']
        if age >= 60 and first['required'] <= capacity:
            selected = first['id']
        elif (60 <= age < 120 and jobs and
              capacity < first['required'] <= capacity + sum(
                  max(job['limit'], job.get('pending_limit', 0)) for job in jobs.values())):
            # Drain existing promises briefly; external RAM never holds an idle queue.
            draining = first['id']
        else:
            last = state.get('last_goal')
            selected = next((e['id'] for e in sorted(
                eligible, key=lambda e: (e['goal'] == last, e['enqueued_at'], e['id']))
                if e['required'] <= capacity), None)
    result['selected'] = selected
    if request is not None and target is None:
        return dict(result, reason_code='queue_expired')
    if target:
        blocked = sorted(blocked_keys.intersection(target['keys']))
        if blocked:
            blocker = next((name for name, job in jobs.items()
                            if set(job['keys']).intersection(blocked)), None)
            return dict(result, reason_code='gpu_busy' if '/gpu/host' in blocked else 'environment_busy',
                        blocked_keys=blocked, blocking_job_id=blocker)
        if target.get('tasks', DEFAULT_TASKS) > pid_free:
            return dict(result, reason_code='pid_budget',
                        requested_tasks=target.get('tasks', DEFAULT_TASKS))
        if target['required'] > capacity:
            return dict(result, reason_code='ram')
    if draining:
        return dict(result, reason_code='queue_head_drain', blocking_job_id=draining)
    if selected:
        return dict(result, reason_code='admitted' if request in (None, selected) else 'queue_turn',
                    blocking_job_id=selected if request not in (None, selected) else None)
    return dict(result, reason_code='ram' if eligible else 'queue_empty')


def estimate_wait(state, request, capacity, now):
    """Median conditional residual estimate; None is unknown, never a deadline."""
    target = next((e for e in state.get('queue', []) if e['id'] == request), None)
    if target is None:
        return None
    busy_keys = {key for j in state['jobs'].values() for key in j['keys']}
    if queue_choice(state, capacity, busy_keys, now)['selected'] == request:
        return 0
    releases = []
    for job in state['jobs'].values():
        history = state.get('history', {}).get(job.get('workload'), [])
        age = max(0, now-job.get('started_at', now))
        residuals = [r['seconds']-age for r in history
                     if r.get('exit') == 0 and r['seconds'] > age]
        if not residuals:
            return None
        releases.append((statistics.median(residuals), job))
    hypothetical = dict(state, jobs=dict(state['jobs']))
    for remaining, job in sorted(releases, key=lambda item: item[0]):
        unit = next(k for k, value in hypothetical['jobs'].items() if value is job)
        del hypothetical['jobs'][unit]
        capacity += job['limit']
        keys = {key for j in hypothetical['jobs'].values() for key in j['keys']}
        while True:
            chosen = queue_choice(hypothetical, capacity, keys, now+remaining)['selected']
            if chosen is None:
                break
            if chosen == request:
                return round(remaining)
            prior = next(e for e in hypothetical['queue'] if e['id'] == chosen)
            capacity -= prior['required']
            keys.update(prior['keys'])
            hypothetical['queue'] = [e for e in hypothetical['queue'] if e['id'] != chosen]
    return None
