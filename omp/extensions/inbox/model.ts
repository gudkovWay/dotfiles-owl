import { randomUUID } from "node:crypto";
import { isAbsolute } from "node:path";
import { z } from "@oh-my-pi/pi-coding-agent";

export const decisionSchema = z.object({
  kind: z.enum(["answer", "amendment", "fix", "urgent"]),
  report: z.string().min(1),
  files: z.array(z.string()),
  contracts: z.array(z.string()),
  dependsOnMain: z.boolean(),
});
export type Decision = z.infer<typeof decisionSchema>;
const imageSchema = z.object({ type: z.literal("image"), data: z.string(), mimeType: z.string() });
const repositorySchema = z.string().min(1).refine(isAbsolute, "Repository binding must be absolute");
const itemSchema = z.object({
  id: z.string(), text: z.string(), images: z.array(imageSchema).optional(),
  status: z.enum(["queued", "triaging", "amendment", "urgent", "answered", "working", "prepared", "failed", "cancelled", "handed-off"]),
  report: z.string().optional(), decision: decisionSchema.optional(),
  worktree: z.string().optional(), base: z.string().optional(),
  repository: repositorySchema.optional(),
  runs: z.array(z.object({
    id: z.string().regex(/^Inbox-[a-zA-Z0-9_-]+$/),
    phase: z.enum(["triage", "fix", "notice"]),
  })).optional(),
});
export const stateSchema = z.object({ enabled: z.boolean(), repository: repositorySchema.optional(), items: z.array(itemSchema) });
export type Item = z.infer<typeof itemSchema>;
export type State = z.infer<typeof stateSchema>;
export interface RepositorySnapshot { cwd: string; branch: string; base?: string; head: string; dirty: string[]; writes: string[] }
export interface Snapshot { cwd: string; context: string; capturedAt: string; repo?: RepositorySnapshot; repositoryIssue?: string }
export interface Host {
  snapshot(item: Item, includeRepository?: boolean): Promise<Snapshot>;
  triage(item: Item, snapshot: Snapshot, signal: AbortSignal): Promise<Decision>;
  execute(item: Item, snapshot: Snapshot, signal: AbortSignal): Promise<string>;
  persist(state: State): void;
  notify(item?: Item): void;
  stop(): void;
  apply(item: Item, integrate: boolean): void;
  idle(): boolean;
}
export function shouldCapture(enabled: boolean, idle: boolean, kind: string, source: string, text: string): boolean {
  return enabled && !idle && kind === "main" && (source === "interactive" || source === "rpc") && !/^\s*[\/!$%]/.test(text);
}
export function safeRelative(file: string): boolean {
  return file.length > 0 && !file.startsWith("/") && !file.includes("\\") && !file.includes(":") && !file.includes("\0") &&
    !file.split("/").some(part => !part || part === ".." || part === "." || /^(\.git|\.omp|\.superpowers|node_modules|\.env(?:\..*)?)$/.test(part)) &&
    !/(^|\/)(AGENTS\.md|CLAUDE\.md|.*\.(pem|key))$/i.test(file);
}
export function independent(decision: Decision, snapshot: Snapshot, reserved: string[]): boolean {
  const repo = snapshot.repo;
  if (decision.kind !== "fix" || decision.dependsOnMain || !decision.files.length || !repo?.base || !repo.head || repo.writes.includes("*")) return false;
  if (!decision.files.every(safeRelative) || !decision.contracts.every(safeRelative)) return false;
  const touched = new Set([...repo.dirty, ...repo.writes, ...reserved]);
  return [...decision.files, ...decision.contracts].every(file => !touched.has(file));
}
export class Inbox {
  enabled: boolean;
  repository: string | undefined;
  readonly items: Item[];
  private triageTail = Promise.resolve();
  private workers = new Map<string, { controller: AbortController; task: Promise<void> }>();
  private controllers = new Map<string, AbortController>();
  private closed = false;
  constructor(private host: Host, state?: State, defaultEnabled = true) {
    this.enabled = state?.enabled ?? defaultEnabled;
    this.repository = state?.repository;
    this.items = structuredClone(state?.items ?? []);
    for (const item of this.items) if (["queued", "triaging", "working"].includes(item.status)) {
      item.status = "failed"; item.report = "Interrupted session. Original input and any worktree retained; use retry explicitly.";
    }
  }
  save(item?: Item): void {
    this.host.persist(structuredClone({ enabled: this.enabled, repository: this.repository, items: this.items }));
    this.host.notify(item);
  }
  bindRepository(repository?: string): void {
    if (this.controllers.size || this.workers.size) throw Error("Inbox requests are active; cancel or finish them before rebinding the repository.");
    if (repository !== undefined && !isAbsolute(repository)) throw Error("Repository binding must be absolute");
    this.repository = repository;
    this.save();
  }
  capture(text: string, images?: Item["images"], urgent = false): Item {
    const item: Item = { id: randomUUID().slice(0, 8), text, images, repository: this.repository, status: urgent ? "urgent" : "queued" };
    this.items.push(item);
    if (urgent) { item.report = "Explicit immediate safety stop. Apply only at an idle checkpoint."; this.mainMutation(); this.host.stop(); }
    try { this.save(item); }
    catch (error) { if (!urgent) item.status = "failed"; item.report = `Persistence failed; input retained in memory: ${error}`; throw error; }
    if (!urgent) this.schedule(item);
    return item;
  }
  private schedule(item: Item): void {
    const controller = new AbortController(); this.controllers.set(item.id, controller);
    this.triageTail = this.triageTail.then(async () => {
      if (controller.signal.aborted || this.closed) { this.controllers.delete(item.id); return; }
      try {
        item.status = "triaging"; this.save(item);
        const snapshot = await this.host.snapshot(item);
        const decision = await this.host.triage(item, snapshot, controller.signal);
        if (controller.signal.aborted || this.closed) return;
        item.decision = decision; item.report = decision.report;
        if (decision.kind === "urgent") { item.status = "urgent"; this.mainMutation(); this.host.stop(); }
        else if (decision.kind === "answer") item.status = "answered";
        else {
          const fresh = await this.host.snapshot(item, decision.kind === "fix");
          if (controller.signal.aborted || this.closed) return;
          const reserved = [...this.workers.keys()].flatMap(id => this.find(id).decision?.files ?? []);
          if (this.workers.size === 0 && snapshot.repo && fresh.repo?.cwd === snapshot.repo.cwd &&
            fresh.repo.head === snapshot.repo.head && fresh.repo.base === snapshot.repo.base && independent(decision, fresh, reserved)) {
            item.status = "working"; item.base = fresh.repo.base;
            const task = this.runWorker(item, fresh, controller).catch(error => {
              console.error(`Inbox worker ${item.id} persistence/notification failure`, error);
            });
            this.workers.set(item.id, { controller, task });
            this.save(item); return;
          }
          item.status = "amendment";
          if (decision.kind === "fix") item.report += "\nHeld for main: dependency/conflict, changing base, or another executor is active.";
        }
        this.save(item);
      } catch (error) {
        if (!this.closed && item.status !== "cancelled") {
          if (item.status !== "urgent") item.status = "failed";
          item.report = String(error); this.save(item);
        }
      } finally { if (!this.workers.has(item.id)) this.controllers.delete(item.id); }
    }).catch(error => {
      try { this.host.notify({ ...item, report: `Inbox persistence failed: ${error}` }); }
      catch (notifyError) { console.error(`Inbox ${item.id} persistence and notification failed`, notifyError); }
    });
  }
  private async runWorker(item: Item, snapshot: Snapshot, controller: AbortController): Promise<void> {
    try {
      const report = await this.host.execute(item, snapshot, controller.signal);
      if (!controller.signal.aborted && !this.closed) { item.status = "prepared"; item.report = report; }
    } catch (error) {
      if (!this.closed && item.status !== "cancelled") {
        item.status = "failed";
        item.report = controller.signal.aborted && item.report ? item.report : String(error);
      }
    } finally {
      this.workers.delete(item.id); this.controllers.delete(item.id);
      if (!this.closed) this.save(item);
    }
  }
  find(id: string): Item { const item = this.items.find(item => item.id === id); if (!item) throw Error(`Unknown inbox id: ${id}`); return item; }
  cancel(id: string): void {
    const item = this.find(id); this.controllers.get(id)?.abort();
    if (["queued", "triaging", "working"].includes(item.status)) { item.status = "cancelled"; item.report = "Cancelled; original input and partial worktree retained."; this.save(item); }
  }
  retry(id: string): void {
    const item = this.find(id);
    if (!["failed", "cancelled"].includes(item.status) || item.worktree) throw Error("Retry requires failed/cancelled input without a partial worktree. Inspect retained worktree first.");
    item.status = "queued"; this.save(item); this.schedule(item);
  }
  apply(id: string, integrate: boolean): void {
    if (!this.host.idle()) throw Error("Main must be idle at an explicit checkpoint; no live merge or plan change.");
    const item = this.find(id);
    if (integrate ? item.status !== "prepared" : !["amendment", "urgent"].includes(item.status) && !(item.status === "failed" && !item.worktree)) throw Error("Item is not ready for this handoff.");
    this.host.apply(item, integrate); item.status = "handed-off"; this.save(item);
  }
  mainMutation(paths?: string[]): void {
    for (const [id, worker] of this.workers) {
      const item = this.find(id);
      const scope = [...(item.decision?.files ?? []), ...(item.decision?.contracts ?? [])];
      if (!paths || paths.some(file => scope.includes(file))) {
        item.report = "Main write-scope conflict. Executor cancelled; inspect its retained worktree before integration.";
        worker.controller.abort();
      }
    }
  }
  async interrupt(): Promise<void> {
    for (const item of this.items) if (["queued", "triaging", "working"].includes(item.status)) {
      item.status = "failed";
      item.report = "Interrupted session transition. Original input and partial worktree retained; inspect before retry.";
    }
    for (const controller of this.controllers.values()) controller.abort();
    await this.settleTriage();
    await this.settleWorkers();
    this.save();
  }
  close(): void { this.closed = true; for (const controller of this.controllers.values()) controller.abort(); }
  settleTriage(): Promise<void> { return this.triageTail; }
  async settleWorkers(): Promise<void> { await Promise.all([...this.workers.values()].map(worker => worker.task)); }
}
