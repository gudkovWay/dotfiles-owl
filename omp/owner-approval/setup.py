"""Unprivileged setup entrypoint: freezes the payload before system authentication."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from install import ASSETS, digest, read_regular

BOOTSTRAP = (
    'import os,sys,hashlib; p=sys.argv.pop(1); h=sys.argv.pop(1); '
    'f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); b=os.read(f,100001); os.close(f); '
    'assert len(b)<=100000 and hashlib.sha256(b).hexdigest()==h,"Installer changed after authorization"; '
    'sys.argv[0]=p; exec(compile(b,p,"exec"),{"__name__":"__main__","__file__":p})'
)


def build_payload(source, owner_uid):
    if type(owner_uid) is not int or owner_uid <= 0:
        raise ValueError('Run setup as the owner, not as root or through sudo')
    bodies = {name: read_regular(source / name) for name in ASSETS}
    manifest = {'owner_uid': owner_uid, 'files': {name: digest(body) for name, body in bodies.items()}}
    manifest_body = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    return bodies, manifest_body


def immutable(path):
    current = path
    while True:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError(f'Installed removal entrypoint is not protected: {current}')
        if current.parent == current:
            break
        current = current.parent


def run(source, *, dry_run=False, remove=False):
    if os.getuid() == 0:
        raise ValueError('Run setup as the owner; the system dialog handles authentication')
    if remove:
        installed = Path('/usr/local/lib/omp-owner-approval/install.py')
        immutable(installed)
        command = ['/usr/bin/pkexec', '--disable-internal-agent', '/usr/bin/python3', '-I',
                   '-c', BOOTSTRAP, str(installed), digest(read_regular(installed)), 'remove']
        if dry_run:
            print(json.dumps({'operation': 'remove', 'requires_authentication': True, 'root': str(installed.parent)}))
            return 0
        return subprocess.run(command, check=False).returncode
    bodies, manifest_body = build_payload(source, os.getuid())
    if dry_run:
        print(json.dumps({'operation': 'install', 'owner_uid': os.getuid(), 'requires_authentication': True,
                          'manifest_sha256': digest(manifest_body), 'destinations': [str(path) for path in ASSETS.values()]}, indent=2))
        return 0
    with tempfile.TemporaryDirectory(prefix='omp-owner-approval-install-') as directory:
        snapshot = Path(directory)
        for name, body in bodies.items():
            (snapshot / name).write_bytes(body)
        (snapshot / 'manifest.json').write_bytes(manifest_body)
        command = ['/usr/bin/pkexec', '--disable-internal-agent', '/usr/bin/python3', '-I', '-c', BOOTSTRAP,
                   str(snapshot / 'install.py'), digest(bodies['install.py']), 'install',
                   '--source', str(snapshot), '--manifest-hash', digest(manifest_body)]
        return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install/remove the scoped owner-approval service using a system password dialog')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    try:
        raise SystemExit(run(Path(__file__).resolve().parent, dry_run=args.dry_run, remove=args.remove))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
