"""Local p2p GitLab gates. No pipeline creation, retry, merge or deletion here."""
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote

ACTIVE = {'created', 'waiting_for_resource', 'preparing', 'pending', 'running', 'scheduled'}


class Forge:
    def __init__(self, root):
        self.root = Path(root)
        self.binary = os.environ.get('GLAB_BIN', 'glab')

    def get(self, path):
        result = subprocess.run([self.binary, 'api', path], cwd=self.root, check=True,
                                text=True, stdout=subprocess.PIPE, timeout=60)
        return json.loads(result.stdout)

    def pages(self, path):
        rows = []
        separator = '&' if '?' in path else '?'
        for page in range(1, 51):
            values = self.get(f'{path}{separator}per_page=100&page={page}')
            if not isinstance(values, list):
                raise RuntimeError('forge list response is not an array')
            rows.extend(values)
            if len(values) < 100:
                return rows
        raise RuntimeError('forge pagination exceeds reviewed bound; no partial proof')

    def mr(self, iid):
        if not str(iid).isdigit():
            raise RuntimeError('MR id must be numeric')
        return self.get(f'projects/:id/merge_requests/{iid}')


def required_jobs(ci, paths):
    """Read the repository's existing literal MR changes selectors, fail closed on drift.

    This intentionally is not a general YAML interpreter. Only the reviewed
    named native test/typecheck jobs and inline changes lists are supported.
    """
    blocks = re.split(r'(?=^[^\s#][^\n]*:\s*$)', ci, flags=re.M)
    selected = set()
    found = 0
    for block in blocks:
        match = re.match(r'((?:Tests|Typecheck) · [A-Za-z]+):\s*\n', block)
        if not match:
            continue
        name = match[1]
        found += 1
        selector = re.search(r'if: [^\n]*CI_PIPELINE_SOURCE[^\n]*merge_request_event[^\n]*\n\s+changes: &[A-Za-z0-9_-]+\n((?:        - [^\n]+\n)+)', block)
        if not selector:
            raise RuntimeError('review native CI changes selector for ' + name)
        patterns = re.findall(r'^        - (\S+)\s*$', selector[1], re.M)
        if not patterns or any(char in ''.join(patterns) for char in '{}![]'):
            raise RuntimeError('unsupported native CI changes patterns for ' + name)
        if name.startswith('Typecheck') and not re.search(r'./scripts/typecheck-app.sh payscrow-[a-z]+ 0\s*$', block, re.M):
            raise RuntimeError('native CI typecheck entrypoint/zero threshold changed: ' + name)
        if any(fnmatch.fnmatchcase(path, pattern.replace('/**/*', '/*'))
               for path in paths for pattern in patterns):
            selected.add(name)
    if not found:
        raise RuntimeError('native CI test/typecheck job contract is missing')
    return selected


def check_pipeline(pipeline, jobs, sha, required):
    if pipeline.get('sha') != sha or pipeline.get('status') != 'success':
        raise RuntimeError('pipeline must succeed for the exact current MR SHA')
    if not jobs:
        raise RuntimeError('empty pipeline job set is not CI proof')
    for name in sorted(required):
        matching = [job for job in jobs if job.get('name') == name]
        if not matching or any(job.get('status') != 'success' or job.get('allow_failure') is not False for job in matching):
            raise RuntimeError('missing/unsuccessful mandatory CI job: ' + name)


def validate_mr(mr, branch, sha):
    if (mr.get('source_branch') != branch or mr.get('sha') != sha
            or mr.get('target_branch') != 'dev' or mr.get('state') != 'opened'
            or not mr.get('source_project_id')
            or mr.get('source_project_id') != mr.get('target_project_id')):
        raise RuntimeError('MR source/target/project/SHA no longer matches the approved p2p feature')
    if mr.get('draft') or mr.get('work_in_progress') or mr.get('has_conflicts'):
        raise RuntimeError('draft or conflicting MR is not mergeable')
    if mr.get('blocking_discussions_resolved') is False:
        raise RuntimeError('MR has unresolved blocking discussions')


def pipeline_jobs(forge, project, pipeline, sha, visited=None):
    visited = set() if visited is None else visited
    key = (str(project), int(pipeline['id']))
    if key in visited or len(visited) >= 100:
        raise RuntimeError('cyclic/oversized downstream CI graph')
    visited.add(key)
    prefix = f'projects/{project}/pipelines/{pipeline["id"]}'
    jobs = forge.pages(prefix + '/jobs?include_retried=false')
    bridges = forge.pages(prefix + '/bridges')
    for bridge in bridges:
        if bridge.get('allow_failure') is True:
            continue
        child = bridge.get('downstream_pipeline')
        if bridge.get('status') != 'success' or not child or child.get('status') != 'success' or child.get('sha') != sha or not child.get('project_id'):
            raise RuntimeError('mandatory downstream pipeline is missing, incomplete or for another SHA')
        jobs.extend(pipeline_jobs(forge, child['project_id'], child, sha, visited))
    return jobs


def wait_for_ci(root, iid, branch, sha, required, seconds=600):
    forge = Forge(root)
    deadline = time.monotonic() + seconds
    while True:
        mr = forge.mr(iid)
        validate_mr(mr, branch, sha)
        pipelines = forge.pages(f'projects/:id/merge_requests/{iid}/pipelines')
        matching = [row for row in pipelines if row.get('sha') == sha]
        current = max(matching, key=lambda row: int(row['id'])) if matching else None
        if current and current.get('status') == 'success':
            jobs = pipeline_jobs(forge, ':id', current, sha)
            check_pipeline(current, jobs, sha, required)
            # The caller repeats this immediately before the SHA-pinned merge.
            return {'pipeline': current, 'jobs': [{'id': j['id'], 'name': j['name'], 'status': j['status']} for j in jobs],
                    'required': sorted(required), 'sha': sha}
        if current and current.get('status') not in ACTIVE:
            raise RuntimeError(f'CI pipeline {current["id"]}: {current.get("status")}; no automatic retry')
        if time.monotonic() >= deadline:
            raise RuntimeError('CI still pending/missing at deadline; preserve branch and MR')
        print('feature-finalize: waiting for current-SHA MR CI', flush=True)
        time.sleep(min(10, max(0, deadline - time.monotonic())))


def merge_args(iid, sha):
    if not str(iid).isdigit() or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', sha):
        raise RuntimeError('invalid pinned MR id/SHA')
    return ['mr', 'merge', str(iid), '--sha=' + sha, '--auto-merge=false',
            '--remove-source-branch=false', '--yes']


def assert_ref_idle(root, branch):
    """Only explicit cleanup uses this; ordinary merges preserve the source ref."""
    forge = Forge(root)
    for pipeline in forge.pages('projects/:id/pipelines?ref=' + quote(branch, safe='')):
        if pipeline.get('status') in ACTIVE:
            raise RuntimeError('source ref still has active pipeline consumers')
        for job in pipeline_jobs(forge, ':id', pipeline, pipeline['sha']):
            if job.get('status') in ACTIVE or (job.get('status') == 'manual' and not job.get('allow_failure')):
                raise RuntimeError('source ref still has pending/manual job consumers')
