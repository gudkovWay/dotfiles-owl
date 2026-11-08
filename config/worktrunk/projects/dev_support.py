"""One reviewed readiness/preparation boundary shared by dev and headless UI."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time
import urllib.request
from resource_policy import Busy

ENVIRONMENT = Path(__file__).resolve().parent / 'project-environment'
P2P_LOCALHOST_PORTS = (3000, 3001, 3002)
WARM_GUARD_MEMORY = ('--need', '3G', '--elastic', '--ceiling', '8G')


def resource_snapshot():
    relative = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
    directory = Path('/sys/fs/cgroup') / relative.lstrip('/')
    names = ('pids.current', 'pids.max', 'pids.peak', 'pids.events',
             'memory.current', 'memory.peak', 'memory.events', 'memory.max',
             'memory.high', 'memory.swap.max', 'cpu.max')
    return {name: (directory / name).read_text().strip()
            for name in names if (directory / name).is_file()}


def port_available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def nuxt_dev_command(app, port, repository):
    command = ['npm', 'run', 'dev', '-w', app, '--',
               '--host', '127.0.0.1', '--port', str(port)]
    if repository == 'p2p':
        if port not in P2P_LOCALHOST_PORTS:
            raise RuntimeError('p2p localhost requires port 3000, 3001, 3002')
        command += ['--strictPort', '--no-takeover']
    return command


@contextmanager
def localhost_port(repository, preferred, *, runtime=None):
    if repository != 'p2p':
        if not port_available(preferred):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                preferred = sock.getsockname()[1]
        yield preferred
        return
    if preferred not in P2P_LOCALHOST_PORTS:
        raise RuntimeError('p2p localhost requires port 3000, 3001, 3002')
    directory = (Path(runtime) if runtime is not None else
                 Path('/run/user') / str(os.getuid())) / 'omp-p2p-localhost'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError('localhost lease directory must be owned and mode 0700')
    ports = (preferred, *(port for port in P2P_LOCALHOST_PORTS if port != preferred))
    for port in ports:
        fd = os.open(directory / f'{port}.lock',
                     os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise RuntimeError('localhost lease file must be owned and mode 0600')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            if not port_available(port):
                continue
            yield port
            return
        finally:
            os.close(fd)
    raise Busy('localhost ports 3000, 3001, 3002 are occupied; no server started')


def profile_for(app):
    if app not in {'payscrow-admin', 'payscrow-merchant', 'payscrow-provider'}:
        raise RuntimeError('no reviewed dev profile for application: ' + app)
    return app.removeprefix('payscrow-') + '-ui'


def status(profile):
    return json.loads(subprocess.check_output([str(ENVIRONMENT), '--profile', profile], text=True))


def ensure_environment(profile, prepare=True):
    current = status(profile)
    if not prepare or (current['dependencies'] == 'ready' and current['generated'] == 'ready'):
        return current
    # The helper admits cold preparation separately, or reuses its verified scope.
    subprocess.run([str(ENVIRONMENT), '--profile', profile, '--install', '--prepare'], check=True)
    current = status(profile)
    if current['dependencies'] != 'ready' or current['generated'] != 'ready':
        raise RuntimeError('environment not ready after preparation: ' + json.dumps(current))
    return current


def nuxt_environment(environment, repository):
    result = dict(environment)
    if repository == 'p2p':
        for key in ('RAYON_NUM_THREADS', 'UV_THREADPOOL_SIZE', 'GOMAXPROCS', 'TOKIO_WORKER_THREADS'):
            result.setdefault(key, '4')
    return result


def owned_listener(port, leader):
    output = subprocess.check_output(['ss', '-H', '-lptn', f'sport = :{port}'], text=True)
    if not output.strip():
        return False
    expected = Path('/proc/self/cgroup').read_text()
    for row in output.splitlines():
        if f'127.0.0.1:{port}' not in row:
            raise RuntimeError('listener is not restricted to the selected loopback origin')
        pids = re.findall(r'pid=(\d+)', row)
        if not pids:
            raise RuntimeError('cannot prove listener ownership')
        for value in pids:
            pid = int(value)
            if Path(f'/proc/{pid}/cgroup').read_text() != expected:
                raise RuntimeError('port belongs to a foreign cgroup')
            seen = set()
            while pid != leader and pid > 1 and pid not in seen:
                seen.add(pid)
                pid = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
            if pid != leader:
                raise RuntimeError('port is not owned by the launched server tree')
    return True


def loopback_response(url):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1)


def wait_ready(process, port, deadline, root, app, mode):
    url = f'http://localhost:{port}'
    readiness_deadline = time.monotonic() + 60
    if deadline is not None:
        readiness_deadline = min(deadline, readiness_deadline)
    while time.monotonic() < readiness_deadline:
        code = process.poll()
        if code is not None:
            raise subprocess.CalledProcessError(code or 1, 'owned Nuxt startup')
        if owned_listener(port, process.pid):
            try:
                with loopback_response(url) as response:
                    if response.status == 200 and owned_listener(port, process.pid):
                        remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
                        record = {
                            'event': 'ready', 'url': url, 'root': str(root), 'app': app,
                            'branch': subprocess.check_output(['git', '-C', str(root), 'branch', '--show-current'], text=True).strip(),
                            'head': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
                            'server_pid': process.pid, 'cgroup': Path('/proc/self/cgroup').read_text().strip(),
                            'mode': mode, 'remaining_seconds': round(remaining, 2) if remaining is not None else None,
                            'expires_at': time.time() + remaining if remaining is not None else None,
                            'verification': 'owned HTTP readiness only; protected screen not verified',
                        }
                        print(json.dumps(record), flush=True)
                        return record
            except OSError:
                pass
        time.sleep(.2)
    raise RuntimeError('owned server readiness deadline exceeded; no automatic retry')


def wait_finite(process, deadline):
    if deadline is None:
        code = process.wait()
        print(json.dumps({'event': 'stopping', 'reason': 'server-exited', 'exit_code': code}), flush=True)
        return code
    remaining = max(0, deadline - time.monotonic())
    if remaining > 60:
        try:
            code = process.wait(timeout=remaining - 60)
            print(json.dumps({'event': 'stopping', 'reason': 'server-exited', 'exit_code': code}), flush=True)
            return code
        except subprocess.TimeoutExpired:
            print(json.dumps({'event': 'preview-expiring', 'remaining_seconds': 60}), flush=True)
    try:
        code = process.wait(timeout=max(0, deadline - time.monotonic()))
        print(json.dumps({'event': 'stopping', 'reason': 'server-exited', 'exit_code': code}), flush=True)
        return code
    except subprocess.TimeoutExpired:
        print(json.dumps({'event': 'stopping', 'reason': 'finite-session-complete'}), flush=True)
        return 0
