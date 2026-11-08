// Session-local observer context. Claims never grant permissions or prove execution.
export interface TaskContext {
  generation: number;
  revision: number;
  inputRevision: number;
  originalGoal: string;
  latestInput: string;
  acceptance: string[];
  corrections: string[];
  blocker: string;
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
  let text = input.slice(0, Math.max(8000, maxChars));
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
  return { generation: 0, revision: 0, inputRevision: 0, originalGoal: "", latestInput: "", acceptance: [], corrections: [], blocker: "",
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
  if (patch.blocker !== undefined) task.blocker = text(patch.blocker);
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
    blocker: task.blocker || "unknown", completion_claim: task.completionClaim || "unknown",
    provenance: "session text, todo-derived criteria, agent claims and selected tool results; scoped evidence only; never authorization" };
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
  task.blocker = text(saved.blocker);
  const env = object(saved.environment);
  task.environment = { status: ["blocked", "claimed-ready", "observed-ready"].includes(String(env.status)) ? String(env.status) : "unknown", detail: text(env.detail) };
  const verification = object(saved.verification);
  task.verification = { status: ["claimed-passed", "claimed-failed", "observed-passed", "observed-failed", "unverified"].includes(String(verification.status)) ? String(verification.status) : "unknown", detail: text(verification.detail) };
  const delivery = object(saved.delivery);
  task.delivery = { target: text(delivery.target) || "unknown", pending: list(delivery.pending), delivered: list(delivery.delivered) };
  task.completionClaim = text(saved.completionClaim);
  task.gitBatch = text(saved.gitBatch);
  return task;
}

/** Capture only known structured boundaries, not arbitrary output or completion prose. */
export function observeToolResult(task: TaskContext, value: unknown): boolean {
  const event = object(value);
  if (event.toolName !== "todo" && event.toolName !== "bash") return false;
  const input = object(event.input);
  const details = object(event.details);
  const before = JSON.stringify(taskView(task));
  if (event.toolName === "todo" && event.isError !== true && Array.isArray(details.phases)) {
    const phases = details.phases.map(object);
    const tasks = phases.flatMap(phase => Array.isArray(phase.tasks) ? phase.tasks.map(object) : []);
    if (!phases.every(phase => typeof phase.name === "string" && Array.isArray(phase.tasks)) ||
        !tasks.every(item => typeof item.content === "string" &&
          ["pending", "in_progress", "completed", "abandoned", "blocked"].includes(String(item.status)))) return false;
    // A todo is a fallback source, not permission to overwrite explicit acceptance.
    if (!task.acceptance.length) task.acceptance = list(tasks.filter(item => item.status !== "abandoned").map(item => item.content));
    const blocked = tasks.find(item => item.status === "blocked");
    if (blocked) task.blocker = text(blocked.blocker) || text(blocked.content);
    else if (["unblock", "done", "rm", "drop"].includes(String(input.op))) task.blocker = "";
  } else if (event.toolName === "bash" && typeof input.command === "string") {
    const command = input.command.slice(0, 4000);
    const content = Array.isArray(event.content) ? event.content.map(value => {
      const block = object(value);
      return block.type === "text" && typeof block.text === "string" ? block.text : "";
    }).join("\n").slice(0, 32768) : "";
    if (input.async === true || details.backgrounded || details.jobId || details.cancelled || details.timedOut ||
        /Backgrounded|background job|Command timed out/i.test(content)) return false;
    const success = event.isError !== true && (details.exitCode === undefined || details.exitCode === 0);
    const envCommand = /\bwt\s+(?:env|commit)\b|(?:^|[\s/])project-environment(?:\s|$)|\/p2p-frontend\/commit(?:\s|$)/.test(command);
    if (envCommand) {
      const records = content.split("\n").flatMap(line => {
        try { const record = object(JSON.parse(line)); return ["p2p", "ecom"].includes(String(record.repository)) ? [record] : []; }
        catch { return []; }
      });
      const record = records.at(-1);
      if (success && record) {
        const ready = (/\s--prepare\b/.test(command) && /project-environment: requested prerequisites ready/.test(content)) ||
          (record.dependencies === "ready" && record.generated === "ready");
        task.environment = { status: ready ? "observed-ready" : "blocked",
          detail: text(`Observed ${record.profile} prerequisites ${ready ? "ready" : "missing-or-stale"}`) };
        task.blocker = ready ? "" : task.environment.detail;
      } else if (!success) {
        task.environment = { status: "blocked", detail: "Environment command failed; no automatic retry" };
        task.blocker = task.environment.detail;
      }
    }
    if (!success && /eslint\.config\.mjs/.test(content) && /ERR_MODULE_NOT_FOUND|Cannot find module/.test(content)) {
      task.environment = { status: "blocked", detail: "Missing generated ESLint commit prerequisite" };
      task.blocker = task.environment.detail;
    }
    if (/\bnpm\s+run\s+test(?::[\w-]+)?\b|\bnode\s+--test\b/.test(command)) {
      const passed = /\bTests\s+(\d+)\s+passed\b|^[#ℹ]\s*pass\s+(\d+)\s*$/m.exec(content);
      const failed = /(?:\bTests[^\n]*\b[1-9]\d*\s+failed|^[#ℹ]\s*fail\s+[1-9])/m.test(content);
      const count = passed ? Number(passed[1] ?? passed[2]) : 0;
      if (!success || failed) task.verification = { status: "observed-failed", detail: "Selected test command failed; no passing claim" };
      else if (count > 0) task.verification = { status: "observed-passed",
        detail: `${count} tests passed in the selected command; runtime/UI not implied` };
    }
    // Delivery inference accepts only ordinary conjunctions, never masked exit codes,
    // shell substitutions, heredocs or arbitrary prose mentioning git.
    if (success && !/[|;`$<>\n]/.test(command)) {
      const commitCommand = /(?:^|\s--\s|\s&&\s)git\s+commit\b|\bwt\s+commit\b/.test(command);
      const commit = commitCommand ? /^\[[^\]\n]+\s([a-f0-9]{7,40})\]\s/m.exec(content) : null;
      if (commit?.[1]) task.delivery.pending = list([...new Set([...task.delivery.pending, commit[1].slice(0, 12)])]);
      const target = /\bwt\s+mr\s+--\s+create\b.*?--target-branch(?:=|\s+)([A-Za-z0-9_.\/-]+)/.exec(command);
      if (target) {
        if (task.delivery.target !== "unknown" && task.delivery.target !== target[1]) {
          task.delivery.pending = list([...new Set([...task.delivery.pending, ...task.delivery.delivered])]);
          task.delivery.delivered = [];
        }
        task.delivery.target = text(target[1]);
      }
      for (const segment of command.split(/\s*&&\s*/)) {
        const ancestor = /^git\s+merge-base\s+--is-ancestor\s+([a-f0-9]{7,40})\s+origin\/([A-Za-z0-9_.\/-]+)\s*$/.exec(segment.trim());
        if (!ancestor?.[1] || ancestor[2] !== task.delivery.target) continue;
        const sha = ancestor[1];
        const delivered = task.delivery.pending.filter(item => /^[a-f0-9]{7,12}$/.test(item) && sha.startsWith(item));
        task.delivery.pending = task.delivery.pending.filter(item => !delivered.includes(item));
        task.delivery.delivered = list([...new Set([...task.delivery.delivered, ...delivered])]);
      }
    }
  }
  if (before === JSON.stringify(taskView(task))) return false;
  task.revision++;
  return true;
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
  if (size() > maximum && typeof task.blocker === "string") task.blocker = clip(task.blocker, 120);
  for (const field of ["environment", "verification"]) {
    const fact = object(task[field]);
    if (size() > maximum && typeof fact.detail === "string") fact.detail = clip(fact.detail, 120);
  }
  if (size() > maximum) throw new Error("bounded JEV request cannot fit without losing delivery context");
  return request;
}
