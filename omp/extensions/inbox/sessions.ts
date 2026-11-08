import { join } from "node:path";
import { mkdir } from "node:fs/promises";
import type { AgentSession, CreateAgentSessionOptions } from "@oh-my-pi/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import type { Item } from "./model";

type Run = NonNullable<Item["runs"]>[number];
const STATE_MESSAGE = "inbox-state";
const READ_ONLY = "Inbox is read-only here. Return to main to submit a request or use /inbox apply ID | integrate ID | cancel ID.";

export function brief(text: string, length = 140): string {
  return text.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\s+/g, " ").trim().slice(0, length);
}

export function delivery(item: Pick<Item, "id" | "status" | "worktree">): string {
  if (item.status === "handed-off") return "Передано main.";
  if (item.status === "amendment" || item.status === "urgent" || item.status === "failed" && !item.worktree) return `Main ещё не получил запрос. /inbox apply ${item.id} на idle.`;
  if (item.status === "prepared") return `Main ещё не получил результат. /inbox integrate ${item.id} на idle.`;
  if (item.status === "failed") return "Main ещё не получил запрос. Сначала проверьте сохранённый worktree; /inbox main ТЕКСТ.";
  if (item.status === "answered") return "Ответ готов в Inbox; main не уведомлён.";
  if (item.status === "cancelled") return "Запрос сохранён, отменён; main не уведомлён.";
  return "Обрабатывается в Inbox; main не уведомлён.";
}

/** Router owns dispatch; the native agent view owns reading, never another turn. */
function protect(session: AgentSession): AgentSession["prompt"] {
  const dispatch = session.prompt.bind(session);
  const deny = async (): Promise<never> => { throw Error(READ_ONLY); };
  session.prompt = deny;
  session.steer = deny;
  session.followUp = deny;
  session.promptCustomMessage = deny;
  const append = session.sendCustomMessage.bind(session);
  session.sendCustomMessage = (message, options) => {
    if (session.isStreaming || options?.triggerTurn || options?.deliverAs) return deny();
    return append(message, options);
  };
  return dispatch;
}

export class InboxSessions {
  private readonly live = new Map<string, AgentSession>();
  private updates = Promise.resolve();
  private closed = false;

  private readonly artifactRoot: string;
  private readonly owner: string;
  private readonly parentFile: string | undefined;

  constructor(private pi: ExtensionAPI, private context: ExtensionContext, private save: () => void) {
    const root = context.sessionManager.getArtifactsDir();
    if (!root) throw Error("Inbox requires a persistent main session");
    this.artifactRoot = root;
    this.owner = context.sessionManager.getSessionId();
    this.parentFile = context.sessionManager.getSessionFile();
  }

  private run(item: Item, phase: Run["phase"]): Run {
    const owner = this.owner.replace(/[^a-zA-Z0-9_-]/g, "");
    const id = item.id.replace(/[^a-zA-Z0-9_-]/g, "");
    return { id: `Inbox-${owner}-${id}-${phase}-${(item.runs?.length ?? 0) + 1}`, phase };
  }

  private async open(item: Item, run: Run, options: Partial<CreateAgentSessionOptions> = {}, existing = false): Promise<AgentSession> {
    if (this.closed) throw Error("Inbox session owner closed");
    const context = this.context;
    const root = this.artifactRoot;
    await mkdir(root, { recursive: true });
    const manager = await this.pi.pi.SessionManager.open(join(root, `${run.id}.jsonl`), root, undefined, {
      initialCwd: options.cwd ?? context.cwd, parentSession: this.parentFile,
      suppressBreadcrumb: true, throwIfMissing: existing,
    });
    const registry = this.pi.pi.AgentRegistry.global();
    const ref = registry.get(run.id);
    if (ref && (ref.session || ref.status !== "parked" || ref.sessionFile !== manager.getSessionFile())) {
      await manager.close();
      throw Error(`Inbox agent ${run.id} is already owned or was killed`);
    }
    try {
      const settings = this.pi.pi.createSubagentSettings(await this.pi.pi.Settings.init());
      const { session } = await this.pi.pi.createAgentSession({
        cwd: manager.getCwd(), model: context.model, modelRegistry: context.modelRegistry,
        authStorage: context.modelRegistry.authStorage, credentialSourceSessionId: this.owner, settings,
        sessionManager: manager, agentId: run.id, parentTaskPrefix: run.id,
        agentDisplayName: `Inbox ${item.id} · ${run.phase} · ${brief(item.text, 48)}`,
        agentName: "inbox", parentAgentId: context.agent.id, taskDepth: 1, expectedAgentRef: ref ?? null,
        systemPrompt: ["Inbox transcript reader. No execution or new requests; handoffs belong to the main session."],
        toolNames: [], customTools: [], restrictToolNames: true, allowRestrictedCustomTools: true, requireYieldTool: false,
        disableExtensionDiscovery: true, preloadedCustomToolPaths: [], skills: [], rules: [], contextFiles: [],
        enableMCP: false, enableLsp: false, enableIrc: false, spawns: "", skipPythonPreflight: true,
        bindProcessState: false, cacheWarming: false, hasUI: false, autoApprove: true,
        ...options,
      });
      if (this.closed) { await session.dispose(); throw Error("Inbox session owner closed during creation"); }
      this.live.set(run.id, session);
      return session;
    } catch (error) { await manager.close(); throw error; }
  }

  async start(item: Item, phase: "triage" | "fix", options: Partial<CreateAgentSessionOptions>): Promise<{ session: AgentSession; prompt: AgentSession["prompt"] }> {
    const run = this.run(item, phase);
    const session = await this.open(item, run, options);
    const prompt = protect(session);
    item.runs ??= [];
    item.runs.push(run);
    this.save();
    return { session, prompt };
  }

  async finish(session: AgentSession): Promise<void> {
    await session.waitForIdle();
    await session.setActiveToolsByName([]);
    const registry = this.pi.pi.AgentRegistry.global();
    for (const [id, live] of this.live) if (live === session) { registry.setStatus(id, "idle", session); break; }
  }

  private async archive(item: Item): Promise<void> {
    const run = this.run(item, "notice");
    const session = await this.open(item, run);
    protect(session);
    session.sessionManager.appendMessage({ role: "user", content: [{ type: "text", text: item.text }, ...(item.images ?? [])], timestamp: Date.now() });
    item.runs = [run];
    this.save();
    await this.finish(session);
  }

  /** Main resume reconstructs tool-less readers, never the old executor contract. */
  async restore(items: Item[]): Promise<void> {
    for (const item of items) {
      if (!item.runs?.length && item.report) await this.archive(item);
      else for (const run of item.runs ?? []) {
        try {
          const session = await this.open(item, run, {}, true);
          protect(session);
          await this.finish(session);
        } catch (error) {
          this.pi.logger.error("Inbox transcript restore failed", { id: run.id, error: String(error) });
          this.context.ui.notify(brief(`Inbox ${item.id}: transcript unavailable; original state retained. ${error}`), "error");
        }
      }
      await this.update(item).catch(error => {
        this.pi.logger.error("Inbox transcript update failed", { id: item.id, error: String(error) });
      });
    }
  }

  update(item: Item): Promise<void> {
    const snapshot = { id: item.id, status: item.status, report: item.report, worktree: item.worktree, repository: item.repository, runs: item.runs?.slice() };
    this.updates = this.updates.catch(error => {
      this.pi.logger.error("Previous Inbox transcript update failed", { error: String(error) });
    }).then(async () => {
      if (this.closed || !snapshot.report) return;
      if (!snapshot.runs?.length) {
        if (!item.runs?.length) await this.archive(item);
        snapshot.runs = item.runs?.slice();
      }
      const run = snapshot.runs?.at(-1);
      if (!run) return;
      const session = this.live.get(run.id);
      if (!session) throw Error(`Inbox ${snapshot.id}: transcript unavailable; original state retained`);
      await session.waitForIdle();
      if (this.closed) return;
      const details = { status: snapshot.status, report: snapshot.report, worktree: snapshot.worktree, repository: snapshot.repository, deliveredToMain: snapshot.status === "handed-off" };
      const last = session.sessionManager.getBranch().findLast(entry => entry.type === "custom_message" && entry.customType === STATE_MESSAGE);
      if (last?.type === "custom_message" && JSON.stringify(last.details) === JSON.stringify(details)) return;
      const repeatedReport = last?.type === "custom_message" && last.details && typeof last.details === "object" && "report" in last.details && last.details.report === snapshot.report;
      await session.sendCustomMessage({
        customType: STATE_MESSAGE, display: true, attribution: "agent", details,
        content: `## Inbox ${snapshot.id} · ${snapshot.status}\n\n${delivery(snapshot)}${repeatedReport ? "" : `\n\n${snapshot.report}`}${snapshot.worktree && !repeatedReport ? `\n\nWorktree: ${snapshot.worktree}` : ""}${snapshot.repository && !repeatedReport ? `\n\nRepository: ${snapshot.repository}` : ""}\n\nRead-only view. Apply/integrate/cancel from main only.`,
      });
      await session.sessionManager.flush();
    });
    return this.updates;
  }

  async close(): Promise<void> {
    await this.updates.catch(error => this.pi.logger.error("Inbox transcript update failed", { error: String(error) }));
    this.closed = true;
    for (const [id, session] of this.live) {
      await session.dispose();
      this.pi.pi.AgentRegistry.global().unregister(id, session);
    }
    this.live.clear();
  }
}
