import assert from 'node:assert/strict';
import test from 'node:test';
import { boundRequest, decisionGate, emptyTask, isCurrent, markGitBatch, observeInput, redactText, restoreTask, taskView, updateTask } from '../task-context.ts';

// Same built-in Node test stack as installed vendor/jev-layer, no provider calls.
test('commit/continue do not replace the original task or erase an undelivered fix', () => {
  const task = emptyTask();
  observeInput(task, 'Signed amount: negative means withdrawal; fix mobile details too');
  updateTask(task, { acceptance: ['negative amount becomes withdrawal', 'mobile details readable'], delivery: { target: 'dev', pending: ['signed amount'], delivered: ['mobile details'] } });
  observeInput(task, '/commit & push');
  observeInput(task, 'продолжай');
  task.completionClaim = 'Mobile details delivered';
  const view = taskView(restoreTask(JSON.parse(JSON.stringify(task))));
  assert.equal(view.original_goal, 'Signed amount: negative means withdrawal; fix mobile details too');
  assert.equal(view.latest_input, 'продолжай');
  assert.deepEqual(view.delivery, { target: 'dev', pending: ['signed amount'], delivered: ['mobile details'] });
  assert.equal(view.completion_claim, 'Mobile details delivered');
});

test('explicit task boundary clears old acceptance, evidence and delivery, not an implicit goal edit', () => {
  const task = emptyTask();
  observeInput(task, 'fix amount');
  updateTask(task, { delivery: { target: 'dev', pending: ['amount'] }, verification: { status: 'passed', detail: 'unit regression' } });
  assert.throws(() => updateTask(task, { goal: 'unrelated task' }), /explicit new_task/);
  assert.equal(task.originalGoal, 'fix amount');
  updateTask(task, { new_task: true, goal: 'fix label geometry', acceptance: ['label visible inside scroll'] });
  assert.equal(task.generation, 1);
  assert.equal(task.originalGoal, 'fix label geometry');
  assert.deepEqual(task.delivery, { target: 'unknown', pending: [], delivered: [] });
  assert.equal(task.verification.status, 'unknown');
});

test('unknown and agent claims never become independently verified facts', () => {
  const task = emptyTask();
  assert.equal(taskView(task).verification.status, 'unknown');
  updateTask(task, { environment: { status: 'ready', detail: 'agent says dependencies ready' }, verification: { status: 'passed', detail: 'agent says tests pass' }, delivery: { pending: ['signed amount'] } });
  assert.equal(task.environment.status, 'claimed-ready');
  assert.equal(task.verification.status, 'claimed-passed');
  observeInput(task, 'не работает, поправь', true);
  assert.equal(task.verification.status, 'unverified');
  assert.deepEqual(task.delivery.pending, ['signed amount']);
  assert.deepEqual(task.corrections, ['не работает, поправь']);
});

test('input or explicit context revision makes a delayed advisory stale', () => {
  const task = emptyTask();
  observeInput(task, 'fix tooltip');
  const revision = task.revision;
  const inputRevision = task.inputRevision;
  assert.equal(isCurrent(task, revision, inputRevision), true);
  updateTask(task, { delivery: { target: 'dev', pending: ['tooltip'] } });
  assert.equal(isCurrent(task, revision, inputRevision), false);
  const changed = task.revision;
  observeInput(task, 'нет, tooltip должен быть возле label', true);
  assert.equal(isCurrent(task, changed, inputRevision), false);
});

test('commit/push of the same pending batch is deduplicated across resume; changed delivery is not', () => {
  const task = emptyTask();
  observeInput(task, 'fix amount and tooltip');
  updateTask(task, { delivery: { target: 'dev', pending: ['amount', 'tooltip'] } });
  assert.equal(markGitBatch(task), true);
  observeInput(task, '/push');
  const restored = restoreTask(task);
  assert.equal(markGitBatch(restored), false);
  updateTask(restored, { delivery: { target: 'dev', pending: ['amount'], delivered: ['tooltip'] } });
  assert.equal(markGitBatch(restored), true);
});

test('session cap cannot be raised and routine checkpoints leave two decisions for correction/completion', () => {
  assert.equal(decisionGate('commit_or_push', 9, 12), null);
  assert.equal(decisionGate('commit_or_push', 10, 12), 'priority_reserve');
  assert.equal(decisionGate('correction_feedback', 10, 12), null);
  assert.equal(decisionGate('done_claim', 11, 12), null);
  assert.equal(decisionGate('done_claim', 12, 12), 'session_cap');
});

test('secret redaction precedes clipping in goals, evidence, corrections and restored state', () => {
  const secret = 'local-test-password';
  const task = emptyTask();
  observeInput(task, `fix /home/q/private/file cookie=${secret} https://alice:${secret}@example.test/path?token=${secret}`);
  updateTask(task, { verification: { status: 'passed', detail: `Authorization: Bearer abcdefghijklmnop; password=${secret}; {"token":"${secret}","api_key":"${secret}"}` }, delivery: { pending: [`token=${secret}`] } });
  const serialized = JSON.stringify(taskView(restoreTask(task)));
  assert.equal(serialized.includes(secret), false);
  assert.equal(serialized.includes('abcdefghijklmnop'), false);
  assert.equal(serialized.includes('/home/q/private'), false);
  assert.match(serialized, /REDACTED/);
  assert.equal(redactText('abc😀def', 4), 'abc');
});

test('bare multiline login and password never enter observer context or restored state', () => {
  const task = emptyTask();
  const password = "fake:<DevLogin>'";
  observeInput(task, `tester@example.test\n\n${password}\n\nположи логин и пароль`);
  const serialized = JSON.stringify(taskView(restoreTask(task)));
  assert.equal(serialized.includes(password), false);
  assert.equal(serialized.includes('tester@example.test'), false);
  assert.match(serialized, /REDACTED_CREDENTIALS/);
  assert.match(serialized, /положи логин и пароль/);
});

test('UTF-8 request bounding preserves pending delivery while marking omitted lower priority context', () => {
  const task = emptyTask();
  observeInput(task, 'исправить'.repeat(70));
  updateTask(task, { acceptance: Array(6).fill('ожидаемое поведение '.repeat(15)), delivery: { target: 'dev', pending: ['signed amount'], delivered: Array(6).fill('готовая правка '.repeat(20)) } });
  const request = boundRequest({ intent: 'intent'.repeat(80), context: { task: taskView(task), session: { decisions: 3 } }, capabilities: [{ id: 'continue_current', permissions: [] }], policy: {} }, 1800);
  assert.ok(Buffer.byteLength(JSON.stringify(request)) <= 1800);
  assert.deepEqual(request.context.task.delivery.pending, ['signed amount']);
  assert.equal(request.context.task.delivery.target, 'dev');
  assert.ok(request.context.task.delivery.delivered_omitted > 0);
  assert.ok(request.context.task.acceptance_omitted > 0);
  assert.deepEqual(task.delivery.pending, ['signed amount']);
});

test('too many pending items remain explicitly incomplete after restore', () => {
  const task = emptyTask();
  updateTask(task, { delivery: { pending: Array.from({ length: 9 }, (_, i) => `fix-${i}`) } });
  const restored = restoreTask(task);
  assert.deepEqual(restored.delivery.pending, ['fix-0', 'fix-1', 'fix-2', 'fix-3', 'fix-4', '[4 more items; consult task source]']);
});
