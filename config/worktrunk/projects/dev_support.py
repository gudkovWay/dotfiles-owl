"""One reviewed readiness/preparation boundary shared by dev and headless UI."""
import json
from pathlib import Path
import subprocess

ENVIRONMENT = Path(__file__).resolve().parent / 'project-environment'


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
    # The caller owns a guarded exclusive scope. The installed helper verifies
    # nesting/caps and reserves the same canonical environment reentrantly.
    subprocess.run([str(ENVIRONMENT), '--profile', profile, '--install', '--prepare'], check=True)
    current = status(profile)
    if current['dependencies'] != 'ready' or current['generated'] != 'ready':
        raise RuntimeError('environment not ready after preparation: ' + json.dumps(current))
    return current
