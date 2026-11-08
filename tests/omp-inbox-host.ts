import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, writeFile, readFile, rm, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Type } from "@oh-my-pi/omptype/typebox";
import { loadExtensions } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/loader";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import type { CreateAgentSessionOptions, CreateAgentSessionResult } from "@oh-my-pi/pi-coding-agent/sdk";
import { AgentRegistry, SessionManager } from "@oh-my-pi/pi-coding-agent";
import { createAgentHubRuntime } from "@oh-my-pi/pi-coding-agent/modes/agent-hub-runtime";
import { SessionFocusController } from "@oh-my-pi/pi-coding-agent/modes/controllers/session-focus-controller";
import type { InteractiveModeContext } from "@oh-my-pi/pi-coding-agent/modes/types";
import { AgentHubOverlayComponent } from "@oh-my-pi/pi-tui/overlays/agent-hub";
import { SessionObserverRegistry } from "@oh-my-pi/pi-tui/overlays/session-observer-registry";
import { ChatTranscriptBuilder } from "@oh-my-pi/pi-tui/chat/chat-transcript-builder";
import { ensureThemeSync } from "@oh-my-pi/pi-tui/theme/theme";
import type { TUI } from "@oh-my-pi/pi-tui/tui";
import extension from "../omp/extensions/inbox/index";
import { stateSchema, type State, type Decision } from "../omp/extensions/inbox/model";

const root = await mkdtemp(join(tmpdir(), "omp-inbox-host-"));
const notes = await mkdtemp(join(tmpdir(), "omp-inbox-notes-"));
const boundRoot = await mkdtemp(join(tmpdir(), "omp-inbox-bound-"));
const configHome = await mkdtemp(join(tmpdir(), "omp-inbox-home-"));
const previousHome = process.env.HOME;
const configPath = join(configHome, ".omp/agent/inbox.config.json");
let state: State = { enabled: false, items: [] }, idle = false, stopped = 0, prompts = 0, workerPath = "";
let sessionId = "fixture-session";
let scenario: "answer" | "amendment" | "fix" | "status" | "failure" = "answer";
let expectedSource = "old";
interface TriagePause { promise: Promise<void>; resolve(): void }
type DeliveredContent = string | ({ type: "text"; text: string } | { type: "image"; data: string; mimeType: string })[];
let pauseTriage: TriagePause | undefined;
let pauseBinding: TriagePause | undefined;
let bindingStarted: TriagePause | undefined;
const delivered: DeliveredContent[] = [];
const diagnostics: { message: string; details: unknown }[] = [];
const entries: unknown[] = [];
const handlers: Record<string, (event: unknown, context: ExtensionContext) => unknown> = {};
let command: ((args: string, context: ExtensionContext) => Promise<void>) | undefined;
const signals: { status: string; resolve: () => void; reject: (error: Error) => void }[] = [];
const notifications: string[] = [];
const widgets: unknown[] = [];
const longReport = "Baseline explanation\n" + "Detailed repository evidence ".repeat(500);
let childTurns = 0;
let failNextDisplay = false;
const childOptions: CreateAgentSessionOptions[] = [];
const registry = AgentRegistry.global();
function nextStatus(status: string): Promise<void> {
  const { promise, resolve, reject } = Promise.withResolvers<void>();
  signals.push({ status, resolve, reject }); return promise;
}
const fixtureContext = {
  cwd: root, mode: "rpc", hasUI: false, agent: { kind: "main", id: "FixtureMain" },
  model: { provider: "fixture", id: "fixture" }, modelRegistry: { authStorage: {} },
  isIdle: () => idle, abort: () => { stopped++; },
  getSystemPrompt: () => { throw Error("Full main contract requires tools unavailable to inbox"); },
  sessionManager: { getSessionId: () => sessionId, getSessionFile: () => join(root, "artifacts.jsonl"), getArtifactsDir: () => join(root, "artifacts"), getBranch: () => entries },
  ui: {
    setStatus: () => {}, setWidget: (_key: string, value: unknown) => { widgets.push(value); }, setEditorText: () => {},
    notify: (text: string) => {
      notifications.push(text);
      for (const signal of [...signals]) {
        if (text.includes("[failed]") && signal.status !== "failed") { signals.splice(signals.indexOf(signal), 1); signal.reject(new Error(text)); }
        else if (text.includes(`[${signal.status}]`)) { signals.splice(signals.indexOf(signal), 1); signal.resolve(); }
      }
    },
  },
};
// Test host substitutes the provider/session boundary, not router decisions, file tools or Worktrunk.
const context = fixtureContext as unknown as ExtensionContext;
const hostApi = {
  on: (name: string, handler: (event: unknown, context: ExtensionContext) => unknown) => { handlers[name] = handler; },
  registerCommand: (_name: string, definition: { handler: typeof command }) => { command = definition.handler; },
  appendEntry: (_type: string, data: unknown) => { state = stateSchema.parse(data); entries.push({ type: "custom", customType: "omp-inbox-v1", data: structuredClone(state) }); },
  sendUserMessage: (content: DeliveredContent) => { prompts++; delivered.push(content); }, typebox: { Type },
  logger: {
    error: (message: string, details: unknown) => { diagnostics.push({ message, details }); },
    info: (message: string, details: unknown) => { diagnostics.push({ message, details }); },
  },
  exec: async (binary: string, args: string[], options: { cwd?: string }) => {
    if (scenario === "status") throw Error("Status questions must not run Git or repository commands");
    if (pauseBinding && args[0] === "rev-parse" && args.includes("--show-toplevel")) {
      bindingStarted?.resolve();
      await pauseBinding.promise;
    }
    try { return { code: 0, killed: false, stdout: execFileSync(binary, args, { cwd: options.cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }), stderr: "" }; }
    catch (error) {
      if (!(error instanceof Error && "status" in error && "stdout" in error && "stderr" in error)) throw error;
      return { code: error.status, killed: false, stdout: String(error.stdout), stderr: String(error.stderr) };
    }
  },
  pi: {
    Settings: { init: async () => ({}) }, createSubagentSettings: (settings: unknown) => settings,
    SessionManager, AgentRegistry,
    createAgentSession: async (options: CreateAgentSessionOptions) => {
      childOptions.push(options);
      assert.equal(options.restrictToolNames, true);
      assert.equal(options.enableMCP, false);
      assert.equal(options.bindProcessState, false);
      assert.equal(options.disableExtensionDiscovery, true);
      assert.equal(options.taskDepth, 1);
      let text = "";
      const worker = options.toolNames?.includes("inbox_change");
      const inspect = options.customTools?.find(tool => tool.name === "inbox_inspect");
      const change = options.customTools?.find(tool => tool.name === "inbox_change");
      const manager = options.sessionManager!;
      const sessionFixture = {
        sessionManager: manager, isStreaming: false,
        prompt: async (prompt: string, input: { images?: unknown[] }) => {
          childTurns++;
          assert.equal(input.images?.length, 1, "images must reach both triage and executor");
          manager.appendMessage({ role: "user", content: [{ type: "text", text: prompt }, ...(input.images ?? [])], timestamp: Date.now() } as Parameters<SessionManager["appendMessage"]>[0]);
          const read = inspect as ToolDefinition;
          if (pauseTriage) await pauseTriage.promise;
          if (scenario !== "status") {
            const readResult = await read.execute("read", { action: "read", path: "other.txt", query: "" }, undefined, undefined, context);
            assert.match(JSON.stringify(readResult.content), new RegExp(expectedSource));
          }
          if (scenario === "failure") throw Error("Fixture provider unavailable");
          if (scenario === "fix" && !worker) {
            try { await read.execute("base", { action: "baseline", path: "other.txt", query: "" }, undefined, undefined, context); }
            catch (error) { assert.match(String(error), /baseline/i); }
          }
          let result: Decision | { completed: boolean; report: string };
          if (worker) {
            workerPath = options.cwd!;
            assert.notEqual(workerPath, root);
            const edit = change as ToolDefinition;
            await assert.rejects(edit.execute("denied", { action: "replace", path: "main.txt", before: "main", after: "bad" }, undefined, undefined, context), /scope/);
            await edit.execute("edit", { action: "replace", path: "other.txt", before: "old", after: "fixed" }, undefined, undefined, context);
            result = { completed: true, report: "Fixed other.txt independently; main feature untouched" };
          } else result = { kind: scenario === "status" ? "answer" : scenario, report: scenario === "answer" || scenario === "status" ? longReport : "Scoped independent source correction", files: scenario === "fix" ? ["other.txt"] : [], contracts: [], dependsOnMain: scenario === "amendment" };
          const submit = options.customTools!.find(tool => tool.name === "inbox_result") as ToolDefinition;
          await submit.execute("result", result, undefined, undefined, context);
          await assert.rejects(submit.execute("duplicate", result, undefined, undefined, context), /already submitted/);
          await assert.rejects(read.execute("late-read", { action: "read", path: "other.txt", query: "" }, undefined, undefined, context), /already submitted/);
          if (worker) await assert.rejects((change as ToolDefinition).execute("late-edit", { action: "replace", path: "other.txt", before: "fixed", after: "bad" }, undefined, undefined, context), /already submitted/);
          text = "Report submitted.";
          manager.appendCustomMessageEntry("fixture-readable-reply", text, true);
        },
        waitForIdle: async () => {}, getLastAssistantText: () => text, abort: async () => {},
        subscribe: () => () => {}, settleInFlightMessagePersistence: async () => {},
        agent: { state: { streamMessage: undefined } }, activeToolExecutionUpdates: () => [],
        steer: async () => { childTurns++; }, followUp: async () => { childTurns++; },
        promptCustomMessage: async () => { childTurns++; return true; },
        setActiveToolsByName: async () => {},
        sendCustomMessage: async (message: { customType: string; content: string; display: boolean; details?: unknown }) => {
          if (failNextDisplay) { failNextDisplay = false; throw Error("Fixture display append failed"); }
          manager.appendCustomMessageEntry(message.customType, message.content, message.display, message.details);
          return false;
        },
        dispose: async () => { registry.unregister(options.agentId!, sessionFixture as unknown as CreateAgentSessionResult["session"]); await manager.close(); },
      };
      const expected = options.expectedAgentRef;
      const ref = expected ? registry.get(options.agentId!)! : registry.register({ id: options.agentId!, displayName: options.agentDisplayName!, kind: "sub", parentId: options.parentAgentId, session: null, sessionFile: manager.getSessionFile()! });
      registry.attachSession(options.agentId!, sessionFixture as unknown as CreateAgentSessionResult["session"], manager.getSessionFile()!, ref);
      // Minimal deterministic provider session fixture; real SDK provider/TUI run remains unverified.
      return { session: sessionFixture as unknown as CreateAgentSessionResult["session"] };
    },
  },
};
// Only the methods actually used by this extension are implemented by the fixture host.
const api = hostApi as unknown as ExtensionAPI;
const images = [{ type: "image", data: "fixture-image", mimeType: "image/png" }];
try {
  process.env.HOME = configHome;
  await mkdir(join(configHome, ".omp/agent"), { recursive: true });
  execFileSync("git", ["init", "-b", "main", root], { stdio: "ignore" });
  execFileSync("git", ["config", "user.name", "Inbox fixture"], { cwd: root });
  execFileSync("git", ["config", "user.email", "inbox@example.invalid"], { cwd: root });
  execFileSync("git", ["config", "worktrunk.default-branch", "main"], { cwd: root });
  await writeFile(join(root, "main.txt"), "main\n"); await writeFile(join(root, "other.txt"), "old\n");
  execFileSync("git", ["add", "main.txt", "other.txt"], { cwd: root });
  execFileSync("git", ["commit", "-m", "Fixture baseline"], { cwd: root, stdio: "ignore" });
  await writeFile(join(root, "main.txt"), "main feature in progress\n");
  assert.ok(process.env.OMP_INBOX_EXTENSION, "test launcher must provide the actual source extension path");
  const loaded = await loadExtensions([process.env.OMP_INBOX_EXTENSION], root);
  assert.deepEqual(loaded.errors, [], "real OMP extension discovery must load the installed module");
  extension(api); await handlers.session_start({}, context);
  assert.equal(state.enabled, true, "missing config must retain the existing ON default");
  await writeFile(configPath, JSON.stringify({ defaultEnabled: false }));
  entries.length = 0;
  await handlers.session_start({}, context);
  assert.equal(state.enabled, false, "configured fresh session must start OFF");
  for (const source of ["rpc", "interactive"]) {
    assert.equal(handlers.input({ text: "normal busy input", source, images }, context), undefined, "default OFF must preserve normal input");
  }
  assert.equal(childTurns, 0, "default OFF must not create a triage request");
  assert.deepEqual(state.items, []);
  await command!("on", context);
  assert.equal(state.enabled, true);
  const startupAnswer = nextStatus("answered");
  assert.deepEqual(handlers.input({ text: "capture after explicit on", source: "rpc", images }, context), { handled: true });
  await startupAnswer;
  assert.equal(state.items[0].text, "capture after explicit on");
  assert.equal(prompts, 0, "enabling Inbox must not wake main");
  await handlers.session_start({}, context);
  assert.equal(state.enabled, true, "saved ON must survive activation with a configured OFF default");
  assert.equal(state.items[0].text, "capture after explicit on", "startup default must not erase saved requests");
  await command!("off", context);
  assert.equal(state.enabled, false);
  const turnsAfterStartup = childTurns;
  assert.equal(handlers.input({ text: "normal input after off", source: "rpc", images }, context), undefined, "manual OFF must restore pass-through");
  assert.equal(childTurns, turnsAfterStartup);
  await writeFile(configPath, JSON.stringify({ defaultEnabled: true }));
  await handlers.session_start({}, context);
  assert.equal(state.enabled, false, "saved OFF must survive activation with a configured ON default");
  assert.equal(state.items[0].text, "capture after explicit on");
  await writeFile(configPath, "{}");
  entries.length = 0;
  await handlers.session_start({}, context);
  assert.equal(state.enabled, true, "a config without defaultEnabled must retain the existing default");
  for (const invalid of ["{", JSON.stringify({ defaultEnabled: "false" }), "[]", "null"]) {
    await writeFile(configPath, invalid);
    entries.length = 0;
    const beforeDiagnostics = notifications.length;
    await handlers.session_start({}, context);
    assert.equal(state.enabled, true, "invalid config must safely use the existing default, not unload Inbox");
    assert.ok(notifications.slice(beforeDiagnostics).some(text => /Inbox config.*default ON/i.test(text)), `invalid config ${invalid} must provide an understandable diagnostic; observed ${JSON.stringify(notifications.slice(beforeDiagnostics))}`);
    await command!("off", context);
    assert.equal(state.enabled, false, "commands must remain usable after invalid config");
    assert.equal(handlers.input({ text: "invalid config still allows off", source: "rpc", images }, context), undefined);
    await command!("on", context);
    assert.equal(state.enabled, true, "invalid config must not disable the extension");
  }
  await rm(configPath);
  entries.length = 0;
  await handlers.session_start({}, context);
  fixtureContext.cwd = notes;
  scenario = "status";
  const nonGitStatus = nextStatus("answered");
  handlers.input({ text: "че там долго ещё?", source: "rpc", images }, context); await nonGitStatus;
  assert.equal(state.items[0].status, "answered", "a conversation question must work outside Git");
  assert.equal(prompts, 0);
  await handlers.session_before_switch({}, context);
  entries.length = 0;
  fixtureContext.cwd = root;
  scenario = "answer";
  await handlers.session_switch({}, context);
  assert.equal(handlers.input({ text: "/commit", source: "rpc" }, context), undefined);
  const answered = nextStatus("answered");
  assert.deepEqual(handlers.input({ text: "explain baseline", source: "rpc", images }, context), { handled: true });
  await answered;
  assert.equal(prompts, 0, "background answer must not steer or wake main");
  assert.equal(state.items[0].report, longReport);
  assert.ok(widgets.every(widget => widget === undefined), "main must never reserve Inbox report space");
  assert.ok(notifications.every(text => !text.includes("Detailed repository evidence") && !text.includes("\n") && text.length <= 180), "main notifications must stay bounded even for long reports");
  await command!(`show ${state.items[0].id}`, context);
  assert.ok(!notifications.at(-1)!.includes("Detailed repository evidence"), "show must point to the Hub, not print a report into main");
  const firstRun = state.items[0].runs!.at(-1)!;
  const firstRef = registry.get(firstRun.id)!;
  assert.ok(firstRef.session, "finished Inbox must remain selectable in the native registry");
  const turnsBeforeReading = childTurns;
  await assert.rejects(firstRef.session!.prompt("change main now"), /read-only/i);
  await assert.rejects(firstRef.session!.prompt(".", { synthetic: true }), /read-only/i);
  await assert.rejects(firstRef.session!.steer("inject while busy"), /read-only/i);
  await assert.rejects(firstRef.session!.followUp("start another turn"), /read-only/i);
  assert.equal(childTurns, turnsBeforeReading);
  assert.equal(prompts, 0);
  assert.match(JSON.stringify(firstRef.session!.sessionManager.getBranch()), /Baseline explanation/);
  ensureThemeSync();
  // Native Hub + focus controller + renderer, with a headless host instead of a terminal window.
  const ui = { requestRender: () => {}, requestComponentRender: () => {} } as unknown as TUI;
  const transcript = new ChatTranscriptBuilder({ ui, cwd: root, tableCharts: false, requestRender: () => {} });
  const mainManager = await SessionManager.open(fixtureContext.sessionManager.getSessionFile(), undefined, undefined, { initialCwd: root, suppressBreadcrumb: true });
  mainManager.appendMessage({ role: "user", content: [{ type: "text", text: "Main conversation stays separate" }], timestamp: Date.now() });
  const mainSession = {
    sessionManager: mainManager, isStreaming: false, subscribe: () => () => {},
    settleInFlightMessagePersistence: async () => {}, agent: { state: { streamMessage: undefined } },
    activeToolExecutionUpdates: () => [],
  } as unknown as CreateAgentSessionResult["session"];
  let focus: SessionFocusController;
  const focusContext = {
    session: mainSession, ui, clearTransientSessionUi: () => {},
    keybindings: { getKeys: () => ["escape"] }, showStatus: () => {},
    eventController: { resetTranscriptAnchors: () => {}, restorePendingToolResults: () => {}, handleEvent: async () => {} },
    statusLine: { setSession: () => {} }, reloadTodos: async () => {},
    updatePendingMessagesDisplay: () => {}, updateEditorBorderColor: () => {},
    renderInitialMessages: async () => {
      const session = focus.target ?? mainSession;
      transcript.rebuild(session.sessionManager.getBranch().filter(entry => entry.type === "message" || entry.type === "custom_message"));
    },
  } as unknown as InteractiveModeContext;
  focus = new SessionFocusController(focusContext, registry);
  const focused = Promise.withResolvers<void>();
  let hubClosed = 0;
  const hub = new AgentHubOverlayComponent({
    ...createAgentHubRuntime({ registry, sessionFile: fixtureContext.sessionManager.getSessionFile() }),
    observers: new SessionObserverRegistry(), hubKeys: ["alt+a"], cwd: root, manageActivityLive: false,
    onDone: () => { hubClosed++; focused.resolve(); }, requestRender: () => {},
    focusAgent: id => focus.focusAgent(id),
    sessionFile: fixtureContext.sessionManager.getSessionFile(),
  });
  try {
    await hub.persistedSubagentsReady;
    assert.match(hub.render(120).join("\n"), new RegExp(`Inbox ${state.items[0].id}`), "native Hub must list the finished Inbox");
    hub.handleInput("\r");
    await focused.promise;
    assert.equal(focus.focusedAgentId, firstRun.id, "native Enter must attach the retained session");
    assert.equal(focus.target, firstRef.session);
    assert.equal(hubClosed, 1);
    const rendered = transcript.container.render(100).join("\n");
    assert.match(rendered, /Baseline explanation/, "native focused transcript must paint the full report");
    assert.match(rendered, /Detailed repository evidence/);
    assert.match(rendered, /Read-only view/);
    assert.ok(!rendered.includes("Main conversation stays separate"));
    hub.handleInput("\x1ba");
    assert.equal(hubClosed, 2, "native Alt+a must close the Hub");
    await focus.unfocus();
    const mainRendered = transcript.container.render(100).join("\n");
    assert.match(mainRendered, /Main conversation stays separate/);
    assert.ok(!mainRendered.includes("Detailed repository evidence"), "returning to main must restore only main's transcript");
  } finally { hub.dispose(); focus.dispose(); transcript.dispose(); await mainManager.close(); }
  assert.equal(childTurns, turnsBeforeReading, "native Hub navigation/rendering must not rerun the provider");
  scenario = "amendment";
  const amendment = nextStatus("amendment");
  handlers.input({ text: "amend feature", source: "rpc", images }, context); await amendment;
  const amendmentId = state.items.at(-1)!.id;
  await command!(`show ${amendmentId}`, context);
  const amendmentSession = registry.get(state.items.at(-1)!.runs!.at(-1)!.id)!.session!;
  const pendingState = amendmentSession.sessionManager.getBranch().findLast(entry => entry.type === "custom_message" && entry.customType === "inbox-state");
  assert.ok(pendingState?.type === "custom_message" && pendingState.details && typeof pendingState.details === "object" && "deliveredToMain" in pendingState.details);
  assert.equal(pendingState.details.deliveredToMain, false, "a ready report is not a main handoff");
  await command!(`apply ${amendmentId}`, context); assert.equal(prompts, 0);
  idle = true; await command!(`apply ${amendmentId}`, context); assert.equal(prompts, 1); idle = false;
  idle = true;
  await command!(`apply ${amendmentId}`, context);
  assert.equal(prompts, 1, "the same amendment must not be handed off twice");
  const handoff = delivered.at(-1)!;
  assert.ok(Array.isArray(handoff));
  assert.ok(handoff[0].type === "text");
  assert.match(handoff[0].text, /amend feature/);
  assert.deepEqual(handoff.slice(1), images, "handoff must retain the original images");
  idle = false;
  await command!(`show ${amendmentId}`, context);
  const sentState = amendmentSession.sessionManager.getBranch().findLast(entry => entry.type === "custom_message" && entry.customType === "inbox-state");
  assert.ok(sentState?.type === "custom_message" && sentState.details && typeof sentState.details === "object" && "deliveredToMain" in sentState.details);
  assert.equal(sentState.details.deliveredToMain, true, "history must expose the completed handoff");
  scenario = "fix";
  const prepared = nextStatus("prepared");
  handlers.input({ text: "independent typo", source: "rpc", images }, context); await prepared;
  assert.equal(await readFile(join(workerPath, "other.txt"), "utf8"), "fixed\n");
  assert.equal(await readFile(join(root, "other.txt"), "utf8"), "old\n");
  assert.equal(await readFile(join(root, "main.txt"), "utf8"), "main feature in progress\n");
  const fixId = state.items.at(-1)!.id;
  assert.match(state.items.at(-1)!.report!, /Tests\/runtime: unverified/);
  await command!(`integrate ${fixId}`, context); assert.equal(prompts, 1);
  idle = true; await command!(`integrate ${fixId}`, context); assert.equal(prompts, 2); idle = false;
  const urgent = handlers.input({ text: "не пушь, не та ветка", source: "rpc", images }, context);
  assert.deepEqual(urgent, { handled: true }); assert.equal(stopped, 1); assert.equal(state.items.at(-1)!.status, "urgent");
  assert.match(JSON.stringify(handlers.tool_call({ toolName: "bash", toolCallId: "push", input: { command: "git push" } }, context)), /"block":true/);
  assert.equal(handlers.tool_call({ toolName: "read", toolCallId: "inspect", input: { path: "main.txt" } }, context), undefined);
  const urgentId = state.items.at(-1)!.id;
  idle = true; await command!(`apply ${urgentId}`, context); idle = false;
  assert.equal(handlers.tool_call({ toolName: "write", toolCallId: "resume", input: { path: "main.txt" } }, context), undefined);
  await command!("stop", context);
  assert.equal(state.items.at(-1)!.status, "urgent", "stop without a reason must remain latched");
  await handlers.session_before_switch({}, context);
  await handlers.session_switch({}, context);
  assert.match(JSON.stringify(handlers.tool_call({ toolName: "bash", toolCallId: "still-stopped", input: {} }, context)), /"block":true/);
  handlers.tool_approval_requested({}, context);
  assert.equal(handlers.input({ text: "approve", source: "rpc" }, context), undefined);
  handlers.tool_approval_resolved({}, context);
  await command!("off", context);
  assert.equal(handlers.input({ text: "ordinary steer", source: "rpc" }, context), undefined);
  await handlers.session_start({}, context);
  assert.equal(handlers.input({ text: "off after resuming same session", source: "rpc", images }, context), undefined);
  entries.length = 0;
  sessionId = "new-fixture-session";
  await handlers.session_start({}, context);
  scenario = "answer";
  failNextDisplay = true;
  const defaultAnswer = nextStatus("answered");
  assert.deepEqual(handlers.input({ text: "new session routes without inbox on", source: "rpc", images }, context), { handled: true });
  await defaultAnswer;
  assert.equal(state.items.at(-1)!.report, longReport);
  await command!(`show ${state.items.at(-1)!.id}`, context);
  assert.match(JSON.stringify(registry.get(state.items.at(-1)!.runs!.at(-1)!.id)!.session!.sessionManager.getBranch()), /Baseline explanation/, "a failed display append must not poison later history updates");
  execFileSync("git", ["init", "-b", "main", boundRoot], { stdio: "ignore" });
  execFileSync("git", ["config", "user.name", "Inbox fixture"], { cwd: boundRoot });
  execFileSync("git", ["config", "user.email", "inbox@example.invalid"], { cwd: boundRoot });
  await writeFile(join(boundRoot, "other.txt"), "bound source\n");
  execFileSync("git", ["add", "other.txt"], { cwd: boundRoot });
  execFileSync("git", ["commit", "-m", "Bound baseline"], { cwd: boundRoot, stdio: "ignore" });
  await mkdir(join(boundRoot, "nested directory"));
  fixtureContext.cwd = notes;
  await command!(`repo ${join(boundRoot, "nested directory")}`, context);
  assert.equal(state.repository, boundRoot, "binding must normalize to the canonical worktree root");
  expectedSource = "bound source";
  const boundAnswer = nextStatus("answered");
  handlers.input({ text: "read current code in main worktree", source: "rpc", images }, context); await boundAnswer;
  assert.equal(state.items.at(-1)!.repository, boundRoot);
  await command!(`repo ${notes}`, context);
  assert.equal(state.repository, boundRoot, "invalid binding must not erase the valid root");
  const beforeHeld = childTurns;
  pauseTriage = Promise.withResolvers<void>();
  const heldAnswer = nextStatus("answered");
  handlers.input({ text: "held repository analysis", source: "rpc", images }, context);
  await command!(`repo ${root}`, context);
  assert.equal(state.repository, boundRoot, "rebinding during active triage must be rejected");
  pauseTriage.resolve(); pauseTriage = undefined; await heldAnswer;
  assert.equal(childTurns, beforeHeld + 1);
  scenario = "fix";
  const noBaseline = nextStatus("amendment");
  handlers.input({ text: "fix without a configured stable baseline", source: "rpc", images }, context); await noBaseline;
  assert.equal(state.items.at(-1)!.worktree, undefined, "missing baseline must never start a worker");
  assert.equal(await readFile(join(boundRoot, "other.txt"), "utf8"), "bound source\n");
  scenario = "failure";
  const retainedFailure = nextStatus("failed");
  handlers.input({ text: "retain this failed request", source: "rpc", images }, context); await retainedFailure;
  const failedId = state.items.at(-1)!.id;
  assert.equal(state.items.at(-1)!.text, "retain this failed request");
  idle = true; await command!(`apply ${failedId}`, context);
  const afterFailureHandoff = prompts;
  await command!(`apply ${failedId}`, context); idle = false;
  assert.equal(prompts, afterFailureHandoff);
  assert.equal(state.items.at(-1)!.status, "handed-off");
  const failedDiagnostic = diagnostics.find(entry => {
    const details = entry.details;
    return details && typeof details === "object" && "id" in details && details.id === failedId && "status" in details && details.status === "failed";
  })?.details;
  assert.ok(failedDiagnostic && typeof failedDiagnostic === "object" && "repository" in failedDiagnostic && "error" in failedDiagnostic && "phase" in failedDiagnostic);
  assert.equal(failedDiagnostic.repository, boundRoot);
  assert.match(String(failedDiagnostic.error), /Fixture provider unavailable/);
  scenario = "answer";
  await command!(`repo ${workerPath}`, context);
  expectedSource = "fixed";
  const linkedAnswer = nextStatus("answered");
  handlers.input({ text: "read selected linked worktree, not launch checkout", source: "rpc", images }, context); await linkedAnswer;
  assert.equal(state.items.at(-1)!.repository, workerPath);
  assert.equal(await readFile(join(root, "other.txt"), "utf8"), "old\n");
  await command!(`repo ${boundRoot}`, context); expectedSource = "bound source";
  const savedRunIds = state.items.flatMap(item => item.runs?.map(run => run.id) ?? []);
  let turnsBeforeResume = childTurns;
  await handlers.session_before_switch({}, context);
  assert.ok(savedRunIds.every(id => !registry.get(id)), "main transition must release only its owned child sessions");
  await handlers.session_switch({}, context);
  assert.equal(childTurns, turnsBeforeResume, "resuming main must never replay triage or fix prompts");
  assert.equal(state.repository, boundRoot, "main resume must retain the selected worktree");
  assert.ok(savedRunIds.every(id => registry.get(id)?.session), "resumed Inbox transcripts must remain selectable");
  for (const options of childOptions.slice(-savedRunIds.length)) assert.deepEqual(options.toolNames, [], "restored readers must have no executor rights");
  const resumeAnswer = nextStatus("answered");
  handlers.input({ text: "read bound repository after resume", source: "rpc", images }, context); await resumeAnswer;
  assert.equal(state.items.at(-1)!.repository, boundRoot);
  turnsBeforeResume = childTurns;
  entries.push({ type: "custom", customType: "omp-inbox-v1", data: {
    enabled: false, items: [
      { id: "missing", text: "Missing transcript", status: "answered", report: "Original missing report", runs: [{ id: "Inbox-not-here", phase: "triage" }] },
      { id: "legacy", text: "Legacy question", images, status: "answered", report: longReport },
    ],
  } });
  await handlers.session_start({}, context);
  assert.equal(childTurns, turnsBeforeResume, "migration must not run a provider");
  assert.equal(state.items[0].report, "Original missing report", "an unavailable transcript must not erase saved reports or block other readers");
  assert.ok(notifications.some(text => text.includes("Inbox missing: transcript unavailable")));
  const legacyRun = state.items[1].runs!.at(-1)!;
  const legacySession = registry.get(legacyRun.id)!.session!;
  const legacyRequest = legacySession.sessionManager.getBranch().find(entry => entry.type === "message" && entry.message.role === "user");
  assert.ok(legacyRequest?.type === "message" && legacyRequest.message.role === "user");
  assert.deepEqual(legacyRequest.message.content, [{ type: "text", text: "Legacy question" }, ...images]);
  assert.match(JSON.stringify(legacySession.sessionManager.getBranch()), /Baseline explanation/);
  await handlers.session_start({}, context);
  assert.deepEqual(state.items[1].runs, [legacyRun], "resume must not create duplicate legacy reader sessions");
  assert.equal(childTurns, turnsBeforeResume);
  await assert.rejects(registry.get(legacyRun.id)!.session!.prompt("execute from history"), /read-only/i);
  pauseBinding = Promise.withResolvers<void>();
  bindingStarted = Promise.withResolvers<void>();
  const staleBinding = command!(`repo ${root}`, context);
  await bindingStarted.promise;
  await handlers.session_before_switch({}, context);
  entries.length = 0; sessionId = "next-owner-session";
  await handlers.session_switch({}, context);
  pauseBinding.resolve(); pauseBinding = undefined;
  await staleBinding;
  assert.equal(state.repository, undefined, "a binding started in the previous main must not mutate the next session");
  entries.push({ type: "custom", customType: "omp-inbox-v1", data: { enabled: "corrupt", items: [] } });
  await handlers.session_start({}, context);
  assert.equal(handlers.input({ text: "invalid saved state must fail closed", source: "rpc", images }, context), undefined);
  await handlers.session_shutdown({}, context);
  console.log("omp-inbox extension-host and real Worktrunk isolation scenario passed; live provider/TUI unverified");
} finally {
  // The fixture repository owns these temporary linked worktrees, never the user's repository.
  if (workerPath) {
    execFileSync("wt", ["remove", workerPath, "--force", "--no-hooks", "--yes", "--foreground"], { cwd: root, stdio: "ignore" });
  }
  await rm(root, { recursive: true, force: true });
  await rm(notes, { recursive: true, force: true });
  await rm(boundRoot, { recursive: true, force: true });
  if (previousHome === undefined) delete process.env.HOME;
  else process.env.HOME = previousHome;
  await rm(configHome, { recursive: true, force: true });
}
