import { createAgentSession, SessionManager } from '/home/q/.cache/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/src/index.ts';

const [root, phase, output, ...inputs] = process.argv.slice(2);
if (!root || !['plan', 'source', 'inspect', 'discover'].includes(phase) || !output) {
  throw new Error('Expected owned root, plan|source|inspect|discover, output and input files');
}
const readOnly = phase !== 'source';
const tools = readOnly ? ['read', 'glob', 'grep', 'lsp'] : ['read', 'glob', 'grep', 'lsp', 'edit', 'write', 'bash', 'todo', 'eval'];
function assertModel(model) {
  if (model?.provider !== 'openai-codex' || model.id !== 'gpt-6.1-sol') throw new Error('Unapproved finalizer model');
}
const { session } = await createAgentSession({
  cwd: root,
  modelPattern: 'openai-codex/gpt-6.1-sol',
  modelPatternDefaultFallbackChain: [],
  thinkingLevel: 'high',
  thinkingLevelCeiling: 'high',
  resolveServiceTierByFamily: () => ({ openai: 'priority' }),
  disableModelFallback: true,
  disableServerSideFallback: true,
  assertDispatchModel: assertModel,
  cacheWarming: false,
  toolNames: tools,
  restrictToolNames: true,
  enableLsp: true,
  lspReadOnly: readOnly,
  enableMCP: false,
  enableIrc: false,
  requireYieldTool: false,
  autoApprove: true,
  skipPythonPreflight: true,
  disableExtensionDiscovery: true,
  extensions: [],
  sessionManager: SessionManager.create(root, output + '.sessions'),
});
try {
  assertModel(session.model);
  const actual = session.getAllToolInfos().map(tool => tool.name).sort();
  if (JSON.stringify(actual) !== JSON.stringify([...tools].sort())) throw new Error('Unexpected finalizer tools');
  console.log(JSON.stringify({ type: 'finalizer_capabilities', tools: actual, lsp_read_only: readOnly, mcp: false,
    model: session.model.provider + '/' + session.model.id, thinking: session.thinkingLevel,
    service_tier: session.serviceTierByFamily }));
  if (phase === 'inspect' || phase === 'discover') {
    const lsp = session.state.tools.find(tool => tool.name === 'lsp');
    for (const action of ['rename', 'rename_file', 'code_actions', 'request', 'reload']) {
      let rejected = false;
      try { await lsp.execute('verify-read-only-' + action, { action }); }
      catch (error) { rejected = String(error).includes('disabled in this read-only session'); }
      if (!rejected) throw new Error('Mutable LSP action was not rejected: ' + action);
    }
    console.log(JSON.stringify({ type: 'read_only_lsp_verified', rejected_actions: ['rename', 'rename_file', 'code_actions', 'request', 'reload'] }));
    if (phase === 'discover') {
      const prompt = session.systemPrompt.join('\n');
      const commands = [];
      for (const name of ['commit', 'refactor', 'docs', 'rn']) {
        const body = (await Bun.file(root + '/.agents/commands/' + name + '.md').text()).replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '').trim();
        const command = session.slashCommands.find(item => item.name === name && item.content.trim() === body && item._source?.level === 'project');
        if (command) commands.push(command);
      }
      const skill = session.skills.find(item => item.name === 'ui-ux-pro-max' && item.filePath.startsWith(root + '/.agents/'));
      if (!prompt.includes('P2P frontend agent entrypoint') || !prompt.includes('p2p-code') || commands.length !== 4 || !skill || session.slashCommands.some(command => command.name === 'docs-sync' && command._source?.level === 'project')) {
        throw new Error(JSON.stringify({ error: 'Incomplete .agents discovery', entrypoint: prompt.includes('P2P frontend agent entrypoint'), rule: prompt.includes('p2p-code'), commands: commands.map(command => command.name), skill: skill?.filePath }));
      }
      console.log(JSON.stringify({ type: 'agents_discovered', commands: commands.map(command => command.name).sort(), skill: skill.filePath, entrypoint: true, code_rule: true }));
    }
  } else {
    session.subscribe(event => {
      if (event.type === 'agent_end') console.log(JSON.stringify(event));
    });
    const parts = [];
    for (const path of inputs) parts.push('INPUT FILE: ' + path + '\n' + await Bun.file(path).text());
    await session.prompt(parts.join('\n\n'));
  }
} finally {
  let timer;
  try {
    await Promise.race([session.dispose(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Finalizer SDK cleanup exceeded five seconds')), 5_000);
    })]);
  } finally { clearTimeout(timer); }
}
process.exit(0);
