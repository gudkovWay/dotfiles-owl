import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createRequire, registerHooks } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { emptyTask, observeInput } from '../task-context.ts';

const ownerHome = process.env.HOME;
const temporary = mkdtempSync(join(tmpdir(), 'jev-extension-test-'));
const directory = join(temporary, '.omp/agent/jev');
mkdirSync(directory, { recursive: true });
writeFileSync(join(directory, 'config.json'), JSON.stringify({ mode: 'shadow', provider: 'typesafe', kill_switch_env: 'JEV_TEST_ENABLED', api_key_path: join(temporary, 'absent-key'), receipt_path: join(directory, 'receipts.jsonl'), max_decisions_per_session: 12, cooldown_ms: 8000 }));
writeFileSync(join(directory, 'receipts.jsonl'), ['legacy-budget', 'legacy-before-start'].flatMap(
  session_id => Array.from({ length: 12 }, () => JSON.stringify({
    record: 'decision', session_id, status: 'fallback', ts: '2026-01-01T00:00:00Z',
  }))).join('\n') + '\n');
process.env.HOME = temporary;
process.env.JEV_TEST_ENABLED = '1';
// OMP's installed legacy-pi-compat maps @sinclair/typebox to its omptype facade.
// Resolve that same host schema implementation in Node's existing native runner.
const host = createRequire(join(ownerHome, '.cache/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/package.json'));
const schemaURL = pathToFileURL(host.resolve('@oh-my-pi/omptype/typebox')).href;
const hooks = registerHooks({ resolve(specifier, context, next) {
  return specifier === '@sinclair/typebox' ? { url: schemaURL, shortCircuit: true } : next(specifier, context);
} });
const { default: jevShadow } = await import('../../extensions/jev-shadow.ts');
after(() => {
  hooks.deregister();
  process.env.HOME = ownerHome;
  delete process.env.JEV_TEST_ENABLED;
  rmSync(temporary, { recursive: true, force: true });
});

function session(id, initial = []) {
  const all = structuredClone(initial);
  let branch = all.slice();
  const handlers = new Map();
  let contextTool;
  jevShadow({ on(name, handler) { handlers.set(name, handler); }, registerTool(tool) { contextTool = tool; }, appendEntry(customType, data) {
    const entry = { type: 'custom', customType, data: structuredClone(data) };
    all.push(entry);
    branch.push(entry);
  } });
  const ctx = { hasUI: true, agent: { depth: 0 }, sessionManager: { getSessionId: () => id, getEntries: () => all, getBranch: () => branch }, getContextUsage: () => null };
  return { all, ctx, tool: () => contextTool, event: (name, event = {}) => handlers.get(name)?.(event, ctx),
    selectBranch(entries) { branch = entries; } };
}

const settled = () => new Promise(resolve => setTimeout(resolve, 30));
const receipts = () => {
  try { return readFileSync(join(directory, 'receipts.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse); }
  catch { return []; }
};

test('actual extension preserves the original task and pending signed amount through commit, continuation and resume', async () => {
  const runtime = session('delivery-resume');
  runtime.event('session_start');
  runtime.event('input', { text: 'signed amount and mobile details' });
  const response = await runtime.tool().execute('context', { delivery: { target: 'dev', pending: ['signed amount'], delivered: ['mobile details'] } }, undefined, undefined, runtime.ctx);
  assert.deepEqual(JSON.parse(response.content[0].text).delivery.pending, ['signed amount']);
  runtime.event('input', { text: '/commit & push' });
  runtime.event('input', { text: 'продолжай' });
  runtime.event('session_shutdown');
  runtime.event('session_start');
  const resumed = await runtime.tool().execute('context', {}, undefined, undefined, runtime.ctx);
  const view = JSON.parse(resumed.content[0].text);
  assert.equal(view.original_goal, 'signed amount and mobile details');
  assert.equal(view.latest_input, 'продолжай');
  assert.deepEqual(view.delivery, { target: 'dev', pending: ['signed amount'], delivered: ['mobile details'] });
});

test('branch restoration cannot replenish the session-wide decision budget or trigger a provider call', async () => {
  const task = emptyTask();
  observeInput(task, 'first task');
  const high = { type: 'custom', customType: 'jev-task-state', data: { schema: 2, decisions: 12, lastCallAt: 0, compactions: 0, task } };
  const lowTask = emptyTask();
  observeInput(lowTask, 'older branch task');
  const low = { type: 'custom', customType: 'jev-task-state', data: { schema: 2, decisions: 0, lastCallAt: 0, compactions: 0, task: lowTask } };
  const runtime = session('budget-across-branches', [low, high]);
  runtime.selectBranch([low]);
  runtime.event('session_tree');
  runtime.event('session_stop', { last_assistant_message: 'done' });
  await settled();
  const decision = receipts().find(r => r.session_id === 'budget-across-branches');
  assert.equal(decision.skipped_reason, 'session_cap');
  assert.equal(decision.goal_preview, 'older branch task');
  assert.equal(decision.task_context.verification.status, 'unknown');
  assert.equal(decision.task_context.completion_claim, 'done');
});

test('scheduled correction is discarded when a later input changes the task revision', async () => {
  const runtime = session('stale-input');
  runtime.event('session_start');
  runtime.event('input', { text: 'fix tooltip' });
  runtime.event('input', { text: 'неправильно, tooltip возле label' });
  runtime.event('input', { text: 'продолжай' });
  await settled();
  const decision = receipts().find(r => r.session_id === 'stale-input');
  assert.equal(decision.skipped_reason, 'stale_context');
  assert.equal(decision.task_context.latest_input, 'неправильно, tooltip возле label');
  assert.equal(decision.task_context.original_goal, 'fix tooltip');
  assert.equal(runtime.event('before_agent_start'), undefined);
});

test('actual shadow observer deduplicates commit and push without injecting advice', async () => {
  const task = emptyTask();
  observeInput(task, 'fix tooltip');
  const runtime = session('git-batch', [{ type: 'custom', customType: 'jev-task-state', data: { schema: 2, decisions: 12, lastCallAt: 0, task } }]);
  runtime.event('session_start');
  runtime.event('tool_call', { toolName: 'bash', input: { command: 'git commit -m "fix"' } });
  runtime.event('tool_call', { toolName: 'bash', input: { command: 'git push origin task-branch' } });
  await settled();
  assert.equal(receipts().filter(r => r.session_id === 'git-batch').length, 1);
  assert.equal(runtime.event('before_agent_start'), undefined);
});

test('legacy receipts preserve spend when resuming a session without new state entries', async () => {
  const runtime = session('legacy-budget');
  runtime.event('session_start');
  runtime.event('input', { text: 'continue original work' });
  runtime.event('session_stop', { last_assistant_message: 'done' });
  await settled();
  const decision = receipts().findLast(r => r.session_id === 'legacy-budget');
  assert.equal(decision.skipped_reason, 'session_cap');
  assert.equal(decision.task_context.original_goal, 'continue original work');
});

test('input before lifecycle activation cannot replenish legacy spend', async () => {
  const runtime = session('legacy-before-start');
  runtime.event('input', { text: 'continue work' });
  runtime.event('session_stop', { last_assistant_message: 'done' });
  await settled();
  const decision = receipts().findLast(r => r.session_id === 'legacy-before-start');
  assert.equal(decision.skipped_reason, 'session_cap');
  assert.equal(decision.task_context.original_goal, 'continue work');
});
