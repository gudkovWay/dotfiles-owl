#!/usr/bin/env node
// Offline context replay only. Does not evaluate provider accuracy or call an API.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { emptyTask, observeInput, redactText, taskView, updateTask } from '../task-context.ts';

const { values } = parseArgs({ options: {
  session: { type: 'string' }, annotations: { type: 'string' }, output: { type: 'string' },
} });
if (!values.session || !values.annotations || !values.output) {
  throw new Error('Use --session <saved JSONL> --annotations <audit annotations JSON> --output <ignored report JSON>');
}
const raw = readFileSync(values.session, 'utf8');
const annotations = JSON.parse(readFileSync(values.annotations, 'utf8'));
const task = emptyTask();
const snapshots = [];
const correction = /wrong|incorrect|не работает|неправильно|неверно|исправь|поправь|сломал|косяк|баг/i;
const lines = raw.trimEnd().split('\n');
for (let index = 0; index < lines.length; index++) {
  const line = index + 1;
  const entry = JSON.parse(lines[index]);
  const message = entry.type === 'message' ? entry.message : null;
  const content = message?.content;
  const text = typeof content === 'string' ? content : Array.isArray(content) ? content.filter(p => p.type === 'text').map(p => p.text ?? '').join('') : '';
  if (message?.role === 'user' && text) observeInput(task, text, correction.test(text));
  const annotation = annotations.events?.[String(line)];
  if (annotation?.patch) updateTask(task, annotation.patch);
  if (annotation?.completion_claim) task.completionClaim = redactText(text);
  if (annotation?.checkpoint) snapshots.push({ source_line: line, checkpoint: annotation.checkpoint, context: taskView(task) });
  if (line >= annotations.through_line) break;
}
const report = {
  mode: 'offline-context-replay', provider_calls: 0,
  evaluation: 'Context preservation only; annotations are audit/agent-reported claims, not live verification. No measurement of JEV advice accuracy.',
  source_sha256: createHash('sha256').update(raw).digest('hex'),
  annotation_provenance: annotations.provenance,
  snapshots,
};
writeFileSync(values.output, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
console.log(JSON.stringify({ mode: report.mode, provider_calls: 0, snapshots: snapshots.map(s => ({ line: s.source_line, checkpoint: s.checkpoint, original_goal: s.context.original_goal, latest_input: s.context.latest_input, delivery: s.context.delivery, verification: s.context.verification })) }));
