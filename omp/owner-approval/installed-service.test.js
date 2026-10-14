import { expect, test } from 'bun:test';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Explicit deployment verification only: no authentication dialog, application command or grant creation.
const deployedTest = process.env.OMP_OWNER_APPROVAL_VERIFY_INSTALLED === '1' ? test : test.skip;
const client = '/usr/local/lib/omp-owner-approval/client.py';

function call(operation, payload = {}) {
  const result = Bun.spawnSync([
    '/usr/bin/python3', '-I', client, operation, JSON.stringify(payload), '--actor-pid', String(process.pid),
  ], { timeout: 10000, stdin: 'ignore', stdout: 'pipe', stderr: 'pipe' });
  return { code: result.exitCode, stdout: result.stdout.toString(), stderr: result.stderr.toString() };
}

deployedTest('the protected system service recognizes the real owner process', () => {
  const result = call('health');
  expect(result.code).toBe(0);
  const health = JSON.parse(result.stdout);
  expect(health.ready).toBe(true);
  expect(health.owner_uid).toBe(process.getuid());
});

deployedTest('an agent-fabricated capability cannot authorize a scope', () => {
  const result = call('check', {
    id: 'not-issued-by-owner', secret: 'agent-invented-approval', session: 'forged-session', cwd: '/home/q/project',
  });
  expect(result.code).toBe(1);
  expect(result.stderr).toContain('org.omp.OwnerApproval1.Denied');
});

deployedTest('the native OMP execution backend preserves the requesting actor identity', async () => {
  const installed = join(homedir(), '.cache/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent');
  const { execCommand } = await import(pathToFileURL(join(installed, 'src/exec/exec.ts')).href);
  const result = await execCommand('/usr/bin/python3', [
    '-I', client, 'health', '{}', '--actor-pid', String(process.pid),
  ], process.cwd(), { timeout: 7000 });
  expect(result.code).toBe(0);
  const health = JSON.parse(result.stdout);
  expect(health.ready).toBe(true);
  expect(health.owner_uid).toBe(process.getuid());
});
