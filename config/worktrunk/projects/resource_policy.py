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


class GuardError(RuntimeError):
    code = 1


class Busy(GuardError):
    code = 75


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
        raise Busy('job_slots: all local job slots occupied')
    usage = {} if usage is None else usage
    free = free_capacity(state, available, usage, jitter)
    if limit > free:
        raise Busy(f'ram: requested={limit}; available-for-promises={free}; host-floor={HOST_FLOOR}')
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
            raise Busy(f'ram: expected={peak}; insufficient safe buffer; free={free}')
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
    if any(e['id'] == entry['id'] for e in queue):
        return
    if len(queue) >= 128:
        raise Busy('queue_slots: pending queue is full')
    queue.append(dict(entry))


def queue_choice(state, capacity, blocked_keys, now):
    queue = [e for e in state.get('queue', []) if e['deadline'] > now]
    # Keys belonging to other environments must not cause global head-of-line blocking.
    eligible = sorted((e for e in queue if not blocked_keys.intersection(e['keys'])),
                      key=lambda e: (e['enqueued_at'], e['id']))
    if not eligible:
        return None
    first = eligible[0]
    if now-first['enqueued_at'] >= 60:
        return first['id'] if first['required'] <= capacity else None
    # Prefer another goal after the previous admission, without bypassing an
    # aged holder. All requests retain their original timestamp and identity.
    last = state.get('last_goal')
    for entry in sorted(eligible, key=lambda e: (e['goal'] == last, e['enqueued_at'])):
        if entry['required'] <= capacity:
            return entry['id']
    return None


def estimate_wait(state, request, capacity, now):
    """Median conditional residual estimate; None is unknown, never a deadline."""
    target = next((e for e in state.get('queue', []) if e['id'] == request), None)
    if target is None:
        return None
    busy_keys = {key for j in state['jobs'].values() for key in j['keys']}
    if queue_choice(state, capacity, busy_keys, now) == request:
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
            chosen = queue_choice(hypothetical, capacity, keys, now+remaining)
            if chosen is None:
                break
            if chosen == request:
                return round(remaining)
            prior = next(e for e in hypothetical['queue'] if e['id'] == chosen)
            capacity -= prior['required']
            keys.update(prior['keys'])
            hypothetical['queue'] = [e for e in hypothetical['queue'] if e['id'] != chosen]
    return None
