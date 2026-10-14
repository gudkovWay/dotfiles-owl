import { expect, test } from 'bun:test';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const installed = join(homedir(), '.cache/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent');
const { loadExtensions } = await import(pathToFileURL(join(installed, 'src/extensibility/extensions/loader.ts')).href);

test('the installed OMP loads the extension and denies child-issued policy exceptions', async () => {
  const path = process.env.OMP_OWNER_APPROVAL_EXTENSION ?? join(import.meta.dir, 'extension.js');
  const loaded = await loadExtensions([path], process.cwd());
  expect(loaded.errors).toEqual([]);
  const tool = loaded.extensions[0].tools.get('owner_approval_request').definition;
  const ctx = { cwd: process.cwd(), agent: { kind: 'sub' }, hasUI: false, sessionManager: { getSessionId: () => 'child-session' } };
  await expect(tool.execute('child-request', { action: 'Override owner policy', exceptions: ['Skip rules'] }, undefined, undefined, ctx)).rejects.toThrow('Only the main session');
});

test('a user-writable clone cannot serve as the authenticated context issuer', async () => {
  const loaded = await loadExtensions([join(import.meta.dir, 'extension.js')], process.cwd());
  expect(loaded.errors).toEqual([]);
  const tool = loaded.extensions[0].tools.get('owner_approval_request').definition;
  const ctx = { cwd: process.cwd(), agent: { kind: 'main' }, hasUI: false, sessionManager: { getSessionId: () => 'main-session' } };
  await expect(tool.execute('uninstalled-request', { action: 'Override owner policy', exceptions: ['Skip local checks'] }, undefined, undefined, ctx)).rejects.toThrow('Only the installed root-owned');
});
