// Session-local observer context. Claims never grant permissions or prove execution.
export interface TaskContext {
  generation: number;
  revision: number;
  inputRevision: number;
  originalGoal: string;
  latestInput: string;
  acceptance: string[];
  corrections: string[];
  environment: { status: string; detail: string };
  verification: { status: string; detail: string };
  delivery: { target: string; pending: string[]; delivered: string[] };
  completionClaim: string;
  gitBatch: string;
}

export function clip(text: string, maxChars: number): string {
  if (maxChars <= 0) return "";
  if (text.length <= maxChars) return text;
  const cut = text.slice(0, maxChars);
  const last = cut.charCodeAt(maxChars - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}

export function redactText(input: string, maxChars = 400): string {
  let text = input.slice(0, 8000);
  // A standalone email followed by a bare password line is a credential pair,
  // even without password= syntax. Redact before masking the email alone.
  text = text.replace(/(^|\n)[^\s@]+@[^\s@]+\.[^\s@]+[ \t]*\n(?:[ \t]*\n)*[ \t]*\S{6,}[ \t]*(?=\n|$)/g, "$1[REDACTED_CREDENTIALS]");
  text = text.replace(/-----BEGIN[^-]{0,40}PRIVATE KEY-----[\s\S]*?-----END[^-]{0,40}PRIVATE KEY-----/g, "[REDACTED_PRIVATE_KEY]");
  text = text.replace(/\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=-]{8,}/gi, "$1 [REDACTED]");
  text = text.replace(/\b(?:sk|pk|rk|ak|api|tok|ghp|gho|ghu|github_pat_|xox)[-_][A-Za-z0-9_-]{8,}\b/gi, "[REDACTED_KEY]");
  text = text.replace(/\b(authorization|cookie|set-cookie|password|passwd|api[_-]?key|apikey|secret|token|credential|access[_-]?key)\b(["']?)(\s*[:=]\s*)("[^"]{0,200}"|'[^']{0,200}'|[^\s,;]{3,200})/gi, "$1$2$3[REDACTED]");
  text = text.replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, "$1[REDACTED_CREDENTIALS]@");
  text = text.replace(/(https?:\/\/[^\s"'<>?#]{1,200})[?#][^\s"'<>]{0,200}/gi, "$1[REDACTED_QUERY]");
  text = text.replace(/\/(?:home|Users|root|tmp|var|etc|opt|mnt|srv|usr|private|proc|sys)(?:\/[^\s"'`)\]},;]{0,200})?/g, "[PATH]");
  text = text.replace(/[A-Za-z]:\\[^\s"'`)\]},;]{0,200}/g, "[PATH]");
  text = text.replace(/\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,64}\.[A-Za-z]{2,12}\b/g, "[EMAIL]");
  text = text.replace(/\b(?=[A-Za-z0-9_-]{32,200}\b)(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[a-z])[A-Za-z0-9_-]{32,200}\b/g, "[REDACTED_SECRET]");
  return clip(text, maxChars);
}

const text = (value: unknown) => typeof value === "string" ? redactText(value) : "";
const list = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  const limit = value.length > 6 ? 5 : 6;
  const values = value.slice(0, limit).map(v => typeof v === "string" ? redactText(v, 180) : "").filter(Boolean);
  if (value.length > 6) values.push(`[${value.length - limit} more items; consult task source]`);
  return values;
};
const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const integer = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;

export function emptyTask(): TaskContext {
  return { generation: 0, revision: 0, inputRevision: 0, originalGoal: "", latestInput: "", acceptance: [], corrections: [],
    environment: { status: "unknown", detail: "" }, verification: { status: "unknown", detail: "" },
    delivery: { target: "unknown", pending: [], delivered: [] }, completionClaim: "", gitBatch: "" };
}

export function observeInput(task: TaskContext, input: string, correction = false): void {
  task.latestInput = text(input);
  if (!task.originalGoal) task.originalGoal = task.latestInput;
  task.inputRevision++;
  task.revision++;
  task.completionClaim = "";
  if (correction) {
    task.corrections = [...task.corrections, redactText(input, 180)].slice(-6);
    task.gitBatch = "";
    // A correction invalidates earlier success claims, not pending delivery.
    task.verification = { status: "unverified", detail: "user correction after previous context" };
  }
}

export function updateTask(task: TaskContext, value: unknown): void {
  const patch = object(value);
  if (Object.keys(patch).length === 0) return;
  if (patch.new_task === true) {
    const goal = text(patch.goal);
    if (!goal) throw new Error("new_task requires a nonempty goal");
    const generation = task.generation + 1;
    const revision = task.revision;
    const inputRevision = task.inputRevision;
    Object.assign(task, emptyTask(), { generation, revision, inputRevision, originalGoal: goal });
  } else if (patch.goal !== undefined) {
    throw new Error("goal changes require an explicit new_task boundary");
  }
  if (patch.acceptance !== undefined) task.acceptance = list(patch.acceptance);
  if (patch.environment !== undefined) {
    const fact = object(patch.environment);
    task.environment = { status: fact.status === "blocked" ? "blocked" : fact.status === "ready" ? "claimed-ready" : "unknown", detail: text(fact.detail) };
  }
  if (patch.verification !== undefined) {
    const fact = object(patch.verification);
    task.verification = { status: fact.status === "passed" ? "claimed-passed" : fact.status === "failed" ? "claimed-failed" : fact.status === "unverified" ? "unverified" : "unknown", detail: text(fact.detail) };
  }
  if (patch.delivery !== undefined) {
    const fact = object(patch.delivery);
    task.delivery = { target: text(fact.target) || "unknown", pending: list(fact.pending), delivered: list(fact.delivered) };
  }
  task.revision++;
}

export function taskView(task: TaskContext): Record<string, unknown> {
  return { generation: task.generation, revision: task.revision, input_revision: task.inputRevision,
    original_goal: task.originalGoal || "unknown", latest_input: task.latestInput || "unknown", acceptance: [...task.acceptance], corrections: [...task.corrections],
    environment: { ...task.environment }, verification: { ...task.verification }, delivery: { ...task.delivery, pending: [...task.delivery.pending], delivered: [...task.delivery.delivered] },
    completion_claim: task.completionClaim || "unknown", provenance: "session text and agent-reported context; not independently verified; never authorization" };
}

export function restoreTask(value: unknown): TaskContext {
  const saved = object(value);
  const task = emptyTask();
  task.generation = integer(saved.generation);
  task.revision = integer(saved.revision);
  task.inputRevision = integer(saved.inputRevision);
  task.originalGoal = text(saved.originalGoal);
  task.latestInput = text(saved.latestInput);
  task.acceptance = list(saved.acceptance);
  task.corrections = list(saved.corrections);
  const env = object(saved.environment);
  task.environment = { status: ["blocked", "claimed-ready"].includes(String(env.status)) ? String(env.status) : "unknown", detail: text(env.detail) };
  const verification = object(saved.verification);
  task.verification = { status: ["claimed-passed", "claimed-failed", "unverified"].includes(String(verification.status)) ? String(verification.status) : "unknown", detail: text(verification.detail) };
  const delivery = object(saved.delivery);
  task.delivery = { target: text(delivery.target) || "unknown", pending: list(delivery.pending), delivered: list(delivery.delivered) };
  task.completionClaim = text(saved.completionClaim);
  task.gitBatch = text(saved.gitBatch);
  return task;
}

export function markGitBatch(task: TaskContext): boolean {
  const fingerprint = JSON.stringify([task.generation, task.delivery.target, task.delivery.pending]);
  if (task.gitBatch === fingerprint) return false;
  task.gitBatch = fingerprint;
  return true;
}

export function isCurrent(task: TaskContext, revision: number, inputRevision: number): boolean {
  return task.revision === revision && task.inputRevision === inputRevision;
}

export function decisionGate(kind: string, decisions: number, maximum: number): string | null {
  if (decisions >= maximum) return "session_cap";
  // Reserve up to two remaining decisions for correction/completion, without increasing the cap.
  if (!["correction_feedback", "done_claim"].includes(kind) && decisions >= Math.max(0, maximum - Math.min(2, maximum))) return "priority_reserve";
  return null;
}

export function boundRequest(request: Record<string, unknown>, maximum: number): Record<string, unknown> {
  const size = () => Buffer.byteLength(JSON.stringify(request), "utf8");
  const context = object(request.context);
  const task = object(context.task);
  if (size() > maximum) delete context.session;
  const delivery = object(task.delivery);
  const delivered = delivery.delivered;
  if (Array.isArray(delivered)) while (size() > maximum && delivered.length) {
    delivered.pop();
    delivery.delivered_omitted = Number(delivery.delivered_omitted ?? 0) + 1;
  }
  for (const field of ["corrections", "acceptance"]) {
    const values = task[field];
    if (Array.isArray(values)) while (size() > maximum && values.length) {
      values.pop();
      task[field + "_omitted"] = Number(task[field + "_omitted"] ?? 0) + 1;
    }
  }
  if (size() > maximum) request.intent = clip(String(request.intent), 120);
  for (const field of ["latest_input", "completion_claim", "original_goal"]) {
    if (size() > maximum && typeof task[field] === "string") task[field] = clip(task[field] as string, 120);
  }
  for (const field of ["environment", "verification"]) {
    const fact = object(task[field]);
    if (size() > maximum && typeof fact.detail === "string") fact.detail = clip(fact.detail, 120);
  }
  if (size() > maximum) throw new Error("bounded JEV request cannot fit without losing delivery context");
  return request;
}
