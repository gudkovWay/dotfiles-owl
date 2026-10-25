#!/usr/bin/env python3
"""Finite owned Hyprland/kitty scenario for personal workspace routing.

Run under guarded-run; creates a private bus after remapping HOME/XDG.
"""
import argparse
import hashlib
import json
import os
import struct
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=5, **kwargs).stdout


def await_value(probe, predicate, label):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = probe()
        if predicate(value):
            return value
        time.sleep(0.1)
    raise RuntimeError('not ready: ' + label)


def inner(args):
    root, source = Path(args.output), Path(args.source)
    signature = os.environ['HYPRLAND_INSTANCE_SIGNATURE']
    parent_signature = os.environ.get('OMP_WORKSPACE_CHECK_PARENT')
    if signature == parent_signature or (not parent_signature and os.environ.get('OMP_WORKSPACE_HEADLESS') != '1'):
        raise RuntimeError('refusing the parent/live compositor')
    instance = next(item for item in json.loads(run(['hyprctl', '-j', 'instances'])) if item.get('instance') == signature)
    pid = int(instance['pid'])
    commandline = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    status = Path(f'/proc/{pid}/status').read_text().splitlines()
    parent = next(line.split()[1] for line in status if line.startswith('PPid:'))
    if str(root / 'hyprland.lua').encode() not in commandline or int(parent) != os.getppid():
        raise RuntimeError('selected compositor is not the wrapper-owned test process')
    compositor = ['hyprctl', '-i', signature]
    records = {'source': str(source), 'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}, 'signature': signature, 'scenarios': [], 'capture': 'unverified'}
    children = []
    logs = []
    guard = None
    before = json.loads(run(compositor + ['-j', 'activeworkspace']))
    before_active = run(compositor + ['-j', 'activewindow'])

    def clients():
        return json.loads(run(compositor + ['-j', 'clients']))

    def start(owner, name, agent='Main'):
        sock = Path(os.environ['VD_ROOT']) / (name + '.sock')
        log = (root / (name + '.log')).open('w')
        logs.append(log)
        child = subprocess.Popen([
            sys.executable, str(source / 'agent-app'), '--session', owner, '--agent', agent, '--',
            'kitty', '--config', 'NONE', '--session', 'none', '--single-instance=no',
            '--class', 'agent-test', '--title', name, '--listen-on', 'unix:' + str(sock),
            '-o', 'allow_remote_control=socket-only', '-o', 'confirm_os_window_close=0',
            '-e', 'sh', '-c', 'printf "ready\\n"; while IFS= read -r line; do printf "received: %s\\n" "$line"; done'
        ], stdout=log, stderr=log)
        children.append(child)
        key = hashlib.sha256((owner + '\0' + agent).encode()).hexdigest()[:24]
        expected = 'special:omp-' + key
        item = await_value(lambda: next((c for c in clients() if c.get('pid') == child.pid), None),
                           lambda c: c and c.get('workspace', {}).get('name') == expected, name + ' personal placement')
        assert child.poll() is None, name + ' exited unexpectedly'
        assert Path(f'/proc/{child.pid}/cgroup').read_text() == Path('/proc/self/cgroup').read_text(), 'launcher escaped resource scope'
        assert json.loads(run(compositor + ['-j', 'activeworkspace']))['id'] == before['id'], 'workspace followed window'
        assert run(compositor + ['-j', 'activewindow']) == before_active, 'focus changed on hidden open'
        events = (root / 'focus-events.txt').read_text() if (root / 'focus-events.txt').exists() else ''
        assert f'active:{child.pid}\n' not in events, 'hidden window transiently took focus'
        await_value(sock.exists, bool, name + ' owned kitty socket')
        return child, item, sock, expected

    try:
        a, ca, sa, wa = start('check-session-a', 'owner-a')
        b, cb, sb, wb = start('check-session-b', 'owner-b')
        a2, ca2, sa2, wa2 = start('check-session-a', 'owner-a-repeat')
        c, cc, sc, wc = start('check-session-a', 'other-agent', 'check-reviewer')
        assert wa != wb and wa == wa2 and wc not in (wa, wb)
        records['scenarios'].append('distinct sessions/agents separate; repeated identity reuses workspace; focus and cgroup unchanged')
        for sock, text in [(sa, 'input-for-a'), (sb, 'input-for-b')]:
            run(['kitten', '@', '--to', 'unix:' + str(sock), 'send-text', text + '\n'])
            await_value(lambda: run(['kitten', '@', '--to', 'unix:' + str(sock), 'get-text']),
                        lambda value: text in value and 'received: ' + text in value, 'targeted terminal input')
        a_text = run(['kitten', '@', '--to', 'unix:' + str(sa), 'get-text'])
        b_text = run(['kitten', '@', '--to', 'unix:' + str(sb), 'get-text'])
        assert 'input-for-b' not in a_text and 'input-for-a' not in b_text
        records['scenarios'].append('targeted input reaches only its owned terminal')
        guard_log = (root / 'guard.log').open('w')
        logs.append(guard_log)
        # The guard must upgrade the legacy fallback, using address rather than focus.
        run(compositor + ['dispatch', 'hl.dsp.window.move({ window = "address:%s", workspace = "special:agent-tests", follow = false })' % cb['address']])
        guard = subprocess.Popen([sys.executable, str(source / 'hypr-agent-guard')], stdout=guard_log, stderr=guard_log)
        await_value(lambda: next((c for c in clients() if c.get('pid') == b.pid), None),
                    lambda c: c and c.get('workspace', {}).get('name') == wb, 'exact-address fallback')
        assert run(compositor + ['-j', 'activewindow']) == before_active, 'guard changed focus'
        records['scenarios'].append('fallback moves only addressed legacy client without taking focus')
        for child in (a, a2):
            child.terminate()
            child.wait(timeout=5)
        assert b.poll() is None
        assert 'received: input-for-b' in run(['kitten', '@', '--to', 'unix:' + str(sb), 'get-text'])
        records['scenarios'].append('terminating owner A preserves owner B and its terminal state')
        # Showing the test workspace is allowed only inside this owned compositor.
        run(compositor + ['dispatch', 'hl.dsp.workspace.toggle_special("%s")' % wb.removeprefix('special:')])
        monitors = json.loads(run(compositor + ['-j', 'monitors']))
        output = next(m for m in monitors if m.get('width', 0) > 0 and m.get('height', 0) > 0)
        records['output'] = {k: output.get(k) for k in ('name', 'width', 'height', 'scale')}
        records['fallback'] = {
            'headless_parent': os.environ.get('OMP_WORKSPACE_HEADLESS') == '1',
            'parent_display_removed': os.environ.get('OMP_WORKSPACE_HEADLESS') == '1',
            'private_runtime': os.environ['XDG_RUNTIME_DIR'],
        }
        capture = subprocess.run(['grim', '-o', output['name'], str(root / 'workspace.png')],
                                 capture_output=True, text=True, timeout=8)
        records['capture'] = {'exit': capture.returncode, 'stderr': capture.stderr}
        if capture.returncode:
            raise RuntimeError('owned capture failed: ' + capture.stderr)
        records['scenarios'].append('captured visible test workspace inside hidden owned compositor')
        before_bytes = (root / 'workspace.png').read_bytes()
        assert struct.unpack('>II', before_bytes[16:24]) == (output['width'], output['height'])
        marker = 'fresh-frame-after-targeted-input'
        run(['kitten', '@', '--to', 'unix:' + str(sb), 'send-text', marker + '\n'])
        await_value(lambda: run(['kitten', '@', '--to', 'unix:' + str(sb), 'get-text']),
                    lambda value: 'received: ' + marker in value, 'state change before fresh capture')
        def fresh_capture():
            run(['grim', '-o', output['name'], str(root / 'workspace-after.png')])
            data = (root / 'workspace-after.png').read_bytes()
            assert struct.unpack('>II', data[16:24]) == (output['width'], output['height'])
            return data
        after_bytes = await_value(fresh_capture, lambda data: data != before_bytes, 'fresh frame after input')
        records['frames'] = {
            'before': hashlib.sha256(before_bytes).hexdigest(),
            'after': hashlib.sha256(after_bytes).hexdigest(),
            'dimensions': [output['width'], output['height']],
        }
        records['scenarios'].append('targeted input changes terminal content and the captured frame at verified dimensions')
        records['status'] = 'verified'
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError, AssertionError, StopIteration) as error:
        records['status'] = 'blocked' if isinstance(error, subprocess.TimeoutExpired) else 'failed'
        records['error'] = str(error)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if guard is not None:
            guard.terminate()
            guard.wait(timeout=5)
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        for log in logs:
            log.close()
        records['teardown'] = 'owned child processes exited'
        (root / 'result.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(records, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--inner', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='write/verify the minimal config without starting a compositor')
    parser.add_argument('--headless', action='store_true', help='use an independent headless Gamescope parent, never the live display')
    args = parser.parse_args()
    if args.inner:
        return inner(args)
    source, root = Path(args.source).resolve(), Path(args.output).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = root / 'home'
    home.mkdir(mode=0o700)
    config = root / 'hyprland.lua'
    config.write_text('''hl.monitor({ output = "", mode = "1280x800@60", position = "0x0", scale = 1 })
hl.config({ animations = { enabled = false }, input = { follow_mouse = 0 }, misc = { disable_autoreload = true, disable_hyprland_logo = true, disable_splash_rendering = true } })
package.preload["config.agent_workspace"] = function() return dofile(%s) end
local silent = dofile(%s)
silent.window_rule({ match = { class = { "agent-test", "aquamarine" } }, workspace = "special:agent-tests" })
hl.on("window.active", function(w)
    local file = assert(io.open(%s, "a"))
    file:write("active:", tostring(w and w.pid or 0), "\\n")
    file:close()
end)
''' % (json.dumps(str(source / 'agent_workspace.lua')), json.dumps(str(source / 'silent.lua')), json.dumps(str(root / 'focus-events.txt'))))
    env = dict(os.environ, HOME=str(home), VD_HYPR_CFG=str(config), KITTY_CONFIG_DIRECTORY=str(home / 'kitty'),
               OMP_WORKSPACE_CHECK_PARENT=os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', ''))
    for variable, directory in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                                ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache')]:
        target = root / directory
        target.mkdir(mode=0o700)
        env[variable] = str(target)
    if args.headless:
        # Wayland/Hyprland IPC must fit Linux's 108-byte sockaddr_un.
        runtime = Path(tempfile.mkdtemp(prefix='ow-'))
        env['XDG_RUNTIME_DIR'] = str(runtime)
        (root / 'runtime-path.txt').write_text(str(runtime)+'\n')
        env['OMP_WORKSPACE_HEADLESS'] = '1'
        for variable in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'DBUS_SESSION_BUS_ADDRESS',
                         'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE'):
            env.pop(variable, None)
    bus_config = root / 'bus.conf'
    bus_config.write_text('''<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy></busconfig>
''')
    env.pop('DISPLAY', None)
    env.pop('XAUTHORITY', None)
    verified = subprocess.run(['Hyprland', '--verify-config', '-c', str(config)], env=env)
    if verified.returncode:
        return verified.returncode
    if args.prepare_only:
        return 0
    # Parent connection is required by vd-run; none of its live config is copied from private HOME.
    command = ['/home/q/.agents/skills/desktop-sandbox/scripts/vd-run.sh', '--hypr',
               sys.executable, str(Path(__file__).resolve()), '--inner', '--source', str(source), '--output', str(root)]
    if args.headless:
        command = ['gamescope', '--backend', 'headless', '--expose-wayland',
                   '-W', '1280', '-H', '800', '-w', '1280', '-h', '800', '--', *command]
    result = subprocess.run(['dbus-run-session', '--config-file=' + str(bus_config), '--', *command], env=env)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
