// Глобальный теневой наблюдатель решений JEV для omp.
//
// Слой System-1: он НИЧЕГО не исполняет, не авторизует, не блокирует, не
// повторяет, не меняет инструменты/модели и не мутирует события сессии.
// В `shadow` он только пишет приватные приёмки (receipts) вне транскрипта;
// в `advisory` может показать уже готовую рекомендацию скрытым
// custom-сообщением на СЛЕДУЮЩЕМ ходу. `off` и `JEV_LAYER_ENABLED=0` —
// выключатели: env проверяется до планирования и перед выдачей совета.
//
// Три правила взяты у пульт-моста (extensions/pult.ts) и держатся буквально:
//   1. НИКОГДА не мешать сессии: каждый sync/async край ловит ошибку, горячий
//      обработчик лишь фиксирует снимок и планирует работу, а провайдер
//      зовётся из setTimeout(..., 0) — промис наружу не отдаётся.
//   2. Только человеческие сессии: print-прогоны и сабагенты не наблюдаются
//      (ctx.hasUI; глубина агента — страховка для саба без UI-режима).
//   3. Наружу (в провайдер и в приёмки) уходит только усечённый и
//      отредактированный текст: ни ключей, ни путей, ни query URL, ни писем.
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { appendFile, chmod, mkdir, readdir, readFile, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, relative, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { Type } from "@sinclair/typebox";
import { boundRequest, clip, decisionGate, emptyTask, isCurrent, markGitBatch, observeInput, redactText, restoreTask, taskView, updateTask } from "../jev/task-context.ts";
import type { TaskContext } from "../jev/task-context.ts";

const AGENT_DIR = join(homedir(), ".omp/agent");
const JEV_DIR = join(AGENT_DIR, "jev");
const CONFIG_PATH = join(JEV_DIR, "config.json");

// ---------------------------------------------------------------- конфигурация

type JevMode = "off" | "shadow" | "advisory";

interface JevConfig {
  schema_version: number;
  mode: JevMode;
  kill_switch_env: string;
  provider: string;
  model: string;
  endpoint: string;
  provider_timeout_ms: number;
  min_confidence: number;
  max_context_bytes: number;
  max_string_chars: number;
  api_key_path: string;
  upstream_entry: string;
  upstream_provider_entry: string;
  receipt_path: string;
  replay_seeds_path: string;
  cooldown_ms: number;
  max_decisions_per_session: number;
  context_budget_percent: number;
}

/** Конфиг читается синхронно и один раз за жизнь процесса (как в pult.ts).
 *  Кривой или отсутствующий конфиг — это «выключено», а не исключение наружу. */
let configCache: JevConfig | null | undefined;

function config(): JevConfig | null {
  if (configCache !== undefined) return configCache;
  configCache = null;
  try {
    const raw = asRecord(JSON.parse(readFileSync(CONFIG_PATH, "utf8")));
    if (!raw) return configCache;
    const mode = raw.mode;
    if (mode !== "off" && mode !== "shadow" && mode !== "advisory") return configCache;
    const num = (value: unknown, fallback: number) =>
      typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
    const str = (value: unknown, fallback: string) => (typeof value === "string" && value ? value : fallback);
    configCache = {
      schema_version: num(raw.schema_version, 1),
      mode,
      kill_switch_env: str(raw.kill_switch_env, "JEV_LAYER_ENABLED"),
      provider: str(raw.provider, "typesafe"),
      model: str(raw.model, "jev-latest"),
      endpoint: str(raw.endpoint, "https://api.typesafe.ai/v1/systemone"),
      provider_timeout_ms: num(raw.provider_timeout_ms, 2000),
      min_confidence: typeof raw.min_confidence === "number" ? raw.min_confidence : 0.62,
      max_context_bytes: num(raw.max_context_bytes, 6000),
      max_string_chars: num(raw.max_string_chars, 400),
      api_key_path: str(raw.api_key_path, join(AGENT_DIR, "secrets/typesafe-api-key")),
      upstream_entry: str(raw.upstream_entry, join(AGENT_DIR, "vendor/jev-layer/src/route.mjs")),
      upstream_provider_entry: str(
        raw.upstream_provider_entry,
        join(AGENT_DIR, "vendor/jev-layer/src/providers/typesafe.mjs"),
      ),
      receipt_path: str(raw.receipt_path, join(JEV_DIR, "receipts.jsonl")),
      replay_seeds_path: str(raw.replay_seeds_path, join(JEV_DIR, "replay-seeds.jsonl")),
      cooldown_ms: num(raw.cooldown_ms, 8000),
      max_decisions_per_session: num(raw.max_decisions_per_session, 12),
      context_budget_percent: num(raw.context_budget_percent, 80),
    };
  } catch {
    configCache = null; // нет конфига — слой молчит
  }
  return configCache;
}

// ------------------------------------------------------------------ кандидаты

/** Закрытый набор: только эти пять действий наблюдатель имеет право советовать.
 *  Описания — канонические labels бенчмарка, чтобы решение было сравнимо с
 *  историческим реплеем. Риск `low` — это совет, а не разрешение: слой ничего
 *  не исполняет, поэтому требует_confirmation здесь не поднимается. */
const CANDIDATES = [
  {
    id: "continue_current",
    kind: "tool",
    name: "Continue current deliverable",
    description: "Continue the same approved deliverable; the next action is bounded and evidence is sufficient for this stage.",
    permissions: [] as string[],
    risk: "low",
    available: true,
  },
  {
    id: "verify_surface_or_runtime",
    kind: "tool",
    name: "Verify surface or runtime",
    description: "Exercise the real user/runtime surface or compare against the acceptance reference before more implementation or declaring completion.",
    permissions: [] as string[],
    risk: "low",
    available: true,
  },
  {
    id: "split_scope_or_handoff",
    kind: "tool",
    name: "Split scope or hand off",
    description: "The request introduces an independent deliverable, subsystem, or layer; create a separate slice/session with a handoff.",
    permissions: [] as string[],
    risk: "low",
    available: true,
  },
  {
    id: "stop_and_refocus",
    kind: "tool",
    name: "Stop and refocus",
    description: "Stop the current path because it is off-scope, under-specified, unsafe, or directly conflicts with the user's latest instruction; re-anchor on the requested outcome.",
    permissions: [] as string[],
    risk: "low",
    available: true,
  },
  {
    id: "escalate_capability",
    kind: "tool",
    name: "Escalate capability",
    description: "Use a stronger or more appropriate model/reviewer because the task requires ambiguous architecture, security, or visual judgment beyond the current worker role.",
    permissions: [] as string[],
    risk: "low",
    available: true,
  },
] as const;

const CANDIDATE_NAME: Record<string, string> = Object.fromEntries(
  CANDIDATES.map((candidate) => [candidate.id, candidate.name]),
);

// ------------------------------------------------------------------ чекпойнты

type CheckpointKind =
  | "correction_feedback"
  | "scope_change"
  | "worker_dispatch"
  | "commit_or_push"
  | "second_compaction"
  | "budget_exceeded"
  | "done_claim";

interface Checkpoint {
  kind: CheckpointKind;
  source: "input" | "tool_call" | "session_compact" | "turn_end" | "session_stop";
  /** Прямой сигнал события или эвристика/производная от него. */
  heuristic: boolean;
  /** Усечённое отредактированное «что произошло». */
  action: string;
  /** Stable original task, not the last /commit or continuation command. */
  goal: string;
  turnPercent: number | null;
  task?: Record<string, unknown>;
  revision?: number;
  inputRevision?: number;
}

// --------------------------------------------------------------- редактирование


function digest(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

/** Граница внешних данных: единственное место, где `unknown` становится
 *  индексируемой записью (ответ вендорского routeRequest и JSON конфига). */
function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

// -------------------------------------------------------------------- сессии

interface PendingAdvisory {
  correlationId: string;
  candidateId: string;
  confidence: number;
  checkpoint: CheckpointKind;
  content: string;
  revision: number;
  inputRevision: number;
}

interface SessionState {
  decisions: number;
  compactions: number;
  budgetFlagged: boolean;
  lastCallAt: number;
  task: TaskContext;
  pendingAdvisory: PendingAdvisory | null;
}

const sessions = new Map<string, SessionState>();
const inflightSessions = new Set<string>();

function stateOf(key: string): SessionState {
  let state = sessions.get(key);
  if (!state) {
    const cfg = config();
    const historical = cfg ? restoreHistoricalBudget(cfg, key) : { decisions: 0, lastCallAt: 0 };
    state = {
      decisions: historical.decisions,
      compactions: 0,
      budgetFlagged: false,
      lastCallAt: historical.lastCallAt,
      task: emptyTask(),
      pendingAdvisory: null,
    };
    sessions.set(key, state);
  }
  return state;
}

const persistors = new Map<string, (state: SessionState) => void>();

function persistState(key: string, state: SessionState): void {
  try {
    persistors.get(key)?.(state);
  } catch {
    // Observer persistence must not block the task.
  }
}

let historicalBudget: Map<string, { decisions: number; lastCallAt: number }> | null = null;
let historicalBudgetUnknown = false;

function restoreHistoricalBudget(cfg: JevConfig, sessionId: string): { decisions: number; lastCallAt: number } {
  if (!historicalBudget) {
    historicalBudget = new Map();
    try {
      // One bounded local read per process, never the API key or session payloads.
      if (statSync(cfg.receipt_path).size > 16 * 1024 * 1024) {
        historicalBudgetUnknown = true;
      } else {
        for (const line of readFileSync(cfg.receipt_path, "utf8").split("\n")) {
          if (!line) continue;
          try {
            const receipt = asRecord(JSON.parse(line));
            if (!receipt || receipt.record !== "decision" || typeof receipt.session_id !== "string") continue;
            if (!["selected", "fallback"].includes(String(receipt.status)) && receipt.skipped_reason !== "internal_error") continue;
            const budget = historicalBudget.get(receipt.session_id) ?? { decisions: 0, lastCallAt: 0 };
            budget.decisions++;
            const timestamp = Date.parse(String(receipt.ts));
            if (Number.isFinite(timestamp)) budget.lastCallAt = Math.max(budget.lastCallAt, timestamp);
            historicalBudget.set(receipt.session_id, budget);
          } catch {
            historicalBudgetUnknown = true;
          }
        }
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") historicalBudgetUnknown = true;
    }
  }
  // Unknown previous spend must not replenish a resumed session's budget.
  return historicalBudgetUnknown ? { decisions: cfg.max_decisions_per_session, lastCallAt: 0 }
    : historicalBudget.get(sessionId) ?? { decisions: 0, lastCallAt: 0 };
}

// ------------------------------------------------------------- ограда сессий

/** id человеческой сессии, либо null (печать/сабагент/битый контекст). */
function humanSessionKey(ctx: ExtensionContext | undefined): string | null {
  try {
    if (!ctx || ctx.hasUI !== true) return null;
    if (ctx.agent && typeof ctx.agent.depth === "number" && ctx.agent.depth > 0) return null; // сабагент
    const id = ctx.sessionManager?.getSessionId?.();
    return typeof id === "string" && id ? id : null;
  } catch {
    return null;
  }
}

/** Выключатели: env проверяется до планирования и перед выдачей совета. */
function enabled(cfg: JevConfig | null): cfg is JevConfig {
  if (!cfg) return false;
  if (process.env[cfg.kill_switch_env] === "0") return false;
  return cfg.mode !== "off";
}

// ------------------------------------------------------------------- приёмки

async function appendReceipt(path: string, record: Record<string, unknown>): Promise<void> {
  try {
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await chmod(dirname(path), 0o700).catch(() => {});
    await appendFile(path, `${JSON.stringify(record)}\n`, { mode: 0o600 });
    await chmod(path, 0o600).catch(() => {});
  } catch {
    /* приёмка не важнее сессии */
  }
}

/** Приёмка ограничена по размеру: сначала теряем вероятности, потом кандидатов. */
function boundReceipt(record: Record<string, unknown>, maxBytes = 8000): Record<string, unknown> {
  const size = () => Buffer.byteLength(JSON.stringify(record), "utf8");
  if (size() <= maxBytes) return record;
  delete record.probabilities;
  if (size() <= maxBytes) return record;
  delete record.candidates;
  if (size() <= maxBytes) return record;
  return {
    record: record.record,
    ts: record.ts,
    session_id: record.session_id,
    mode: record.mode,
    status: record.status,
    skipped_reason: record.skipped_reason ?? null,
    correlation_id: record.correlation_id ?? null,
    note: "receipt truncated to fit bound",
  };
}

// ------------------------------------------------------------- отпечаток базы

let fingerprintPromise: Promise<string> | null = null;

/** Отпечаток метаданных правил/скиллов/конфига: путь + размер + mtime, без
 *  содержимого файлов. Считается один раз за процесс. */
function metadataFingerprint(): Promise<string> {
  if (!fingerprintPromise) {
    fingerprintPromise = (async () => {
      const entries: string[] = [];
      const push = async (filePath: string): Promise<void> => {
        try {
          const info = await stat(filePath);
          if (!info.isFile()) return;
          entries.push(`${relative(AGENT_DIR, filePath).split(sep).join("/")}\0${info.size}\0${Math.round(info.mtimeMs)}`);
        } catch {
          /* файл исчез — отпечаток просто без него */
        }
      };
      try {
        const rulesDir = join(AGENT_DIR, "rules");
        for (const name of await readdir(rulesDir)) {
          if (name.endsWith(".md")) await push(join(rulesDir, name));
        }
      } catch {
        /* нет каталога правил */
      }
      try {
        const walk = async (dir: string, depth: number): Promise<void> => {
          if (depth > 4 || entries.length > 2000) return;
          for (const entry of await readdir(dir, { withFileTypes: true })) {
            const child = join(dir, entry.name);
            if (entry.isDirectory()) await walk(child, depth + 1);
            else if (entry.isFile() && entry.name === "SKILL.md") await push(child);
          }
        };
        await walk(join(AGENT_DIR, "skills"), 0);
      } catch {
        /* нет каталога скиллов */
      }
      await push(join(AGENT_DIR, "config.yml"));
      entries.sort();
      return digest(entries.join("\n"));
    })().catch(() => "sha256:unavailable");
  }
  return fingerprintPromise;
}

// ------------------------------------------------------------------- upstream

interface UpstreamModule {
  routeRequest: (input: unknown, options?: Record<string, unknown>) => Promise<unknown>;
  TypeSafeProvider: new (options: Record<string, unknown>) => unknown;
}

let upstreamPromise: Promise<UpstreamModule | null> | null = null;

/** Вендорские модули грузятся лениво и один раз. Статический импорт здесь
 *  невозможен: пути выбираются во время исполнения из конфига (upstream_entry
 *  для route.mjs и upstream_provider_entry для провайдера), а отсутствие
 *  вендора обязано приводить к тихому молчанию, а не к падению загрузки
 *  расширения. `route.mjs` экспортирует `routeRequest`, провайдерский модуль —
 *  `TypeSafeProvider`: это разные файлы, и требовать оба экспорта от одного
 *  модуля нельзя. */
function loadUpstream(routeEntry: string, providerEntry: string): Promise<UpstreamModule | null> {
  if (!upstreamPromise) {
    upstreamPromise = (async () => {
      const route = (await import(pathToFileURL(routeEntry).href)) as { routeRequest?: unknown };
      const provider = (await import(pathToFileURL(providerEntry).href)) as { TypeSafeProvider?: unknown };
      return typeof route.routeRequest === "function" && typeof provider.TypeSafeProvider === "function"
        ? {
            routeRequest: route.routeRequest as UpstreamModule["routeRequest"],
            TypeSafeProvider: provider.TypeSafeProvider as UpstreamModule["TypeSafeProvider"],
          }
        : null;
    })().catch(() => null);
  }
  return upstreamPromise;
}

// ------------------------------------------------------------ запрос и прогон

interface DecisionOutcome {
  status: string;
  selected: string | null;
  confidence: number | null;
  probabilities: Record<string, number>;
  fallbackType: string | null;
  correlationId: string | null;
  requestId: string | null;
  provider: string;
  model: string | null;
  usage: ProviderUsage;
  latencyMs: number | null;
  contextBytes: number | null;
  candidates: Array<Record<string, unknown>>;
}

/** Единственные числа, которые разрешено вынести из сырого ответа провайдера. */
interface ProviderUsage {
  inputTokens: number | null;
  outputTokens: number | null;
  cost: number | null;
}

/** Закрытый запрос: всё, что уходит, описано в спеке и усечено до границ. */
function buildRequest(checkpoint: Checkpoint, state: SessionState, cfg: JevConfig): Record<string, unknown> {
  const request: Record<string, unknown> = {
    schema_version: 1,
    harness: "omp",
    intent: clip(
      `checkpoint=${checkpoint.kind}; goal=${redactText(checkpoint.goal, cfg.max_string_chars) || "unknown"}; ` +
        `action=${redactText(checkpoint.action, cfg.max_string_chars)}; mode=${cfg.mode}`,
      cfg.max_string_chars,
    ) || `checkpoint=${checkpoint.kind}`,
    context: {
      checkpoint: { kind: checkpoint.kind, source: checkpoint.source, heuristic: checkpoint.heuristic },
      session: { decisions: state.decisions, compactions: state.compactions, context_percent: checkpoint.turnPercent },
      task: checkpoint.task ?? taskView(state.task),
    },
    capabilities: CANDIDATES.map((candidate) => ({
      id: candidate.id,
      kind: candidate.kind,
      name: candidate.name,
      description: candidate.description,
      permissions: [...candidate.permissions],
      risk: candidate.risk,
      available: candidate.available,
    })),
    policy: {},
  };
  return boundRequest(request, cfg.max_context_bytes);
}

/** Ответ вендора → плоская безопасная запись. Провайдерский текст (raw_jev,
 *  reason, тела ошибок) здесь не сохраняется ни в каком виде. */
function readOutcome(decision: unknown, cfg: JevConfig): DecisionOutcome {
  const envelope = asRecord(decision) ?? {};
  const receipt = asRecord(envelope.receipt) ?? {};
  const probabilities: Record<string, number> = {};
  const rawProbabilities = asRecord(envelope.probabilities);
  if (rawProbabilities) {
    for (const [id, value] of Object.entries(rawProbabilities).slice(0, 16)) {
      if (typeof value === "number" && Number.isFinite(value)) probabilities[clip(id, 64)] = Math.round(value * 10000) / 10000;
    }
  }
  const fallback = asRecord(envelope.fallback);
  const rawCandidates = Array.isArray(envelope.candidates) ? envelope.candidates.slice(0, 16) : [];
  // Из сырого ответа провайдера берём ровно четыре скаляра: конкретное имя
  // модели и три конечных числа usage. Сам `raw_jev` (answers, reason, тела
  // ошибок) и любые его вложенные объекты наружу не выносятся.
  const rawJev = asRecord(envelope.raw_jev);
  const rawUsage = asRecord(rawJev?.usage);
  return {
    status: typeof envelope.status === "string" ? clip(envelope.status, 32) : "unknown",
    selected: typeof envelope.selected === "string" ? clip(envelope.selected, 64) : null,
    confidence:
      typeof envelope.confidence === "number" && Number.isFinite(envelope.confidence)
        ? Math.round(envelope.confidence * 10000) / 10000
        : null,
    probabilities,
    fallbackType: typeof fallback?.type === "string" ? clip(fallback.type, 64) : null,
    correlationId: typeof envelope.correlation_id === "string" ? clip(envelope.correlation_id, 128) : null,
    requestId: typeof receipt.request_id === "string" ? clip(receipt.request_id, 128) : null,
    provider: typeof receipt.provider === "string" ? clip(receipt.provider, 64) : cfg.provider,
    model: typeof rawJev?.model === "string" ? clip(rawJev.model, 128) : null,
    usage: {
      inputTokens: typeof rawUsage?.input_tokens === "number" && Number.isFinite(rawUsage.input_tokens) ? rawUsage.input_tokens : null,
      outputTokens: typeof rawUsage?.output_tokens === "number" && Number.isFinite(rawUsage.output_tokens) ? rawUsage.output_tokens : null,
      cost: typeof rawUsage?.cost === "number" && Number.isFinite(rawUsage.cost) ? rawUsage.cost : null,
    },
    latencyMs: typeof receipt.latency_ms === "number" ? receipt.latency_ms : null,
    contextBytes: typeof receipt.context_bytes === "number" ? receipt.context_bytes : null,
    candidates: rawCandidates.map((raw) => {
      const candidate = asRecord(raw) ?? {};
      return {
        id: typeof candidate.id === "string" ? clip(candidate.id, 64) : null,
        risk: typeof candidate.risk === "string" ? clip(candidate.risk, 16) : null,
        filtered: candidate.filtered === true,
        probability: typeof candidate.probability === "number" ? candidate.probability : null,
      };
    }),
  };
}

function baseRecord(checkpoint: Checkpoint, sessionId: string, cfg: JevConfig): Record<string, unknown> {
  return {
    record: "decision",
    ts: new Date().toISOString(),
    session_id: sessionId,
    mode: cfg.mode,
    kill_switch: process.env[cfg.kill_switch_env] === "0" ? "disabled" : "armed",
    checkpoint: {
      kind: checkpoint.kind,
      source: checkpoint.source,
      heuristic: checkpoint.heuristic,
      action: redactText(checkpoint.action, cfg.max_string_chars),
      digest: digest(`${checkpoint.kind}\0${checkpoint.action}`),
      context_percent: checkpoint.turnPercent,
    },
    goal_preview: redactText(checkpoint.goal, cfg.max_string_chars),
    goal_digest: digest(checkpoint.goal),
    status: "skipped",
    selected: null,
    confidence: null,
    probabilities: {},
    fallback: null,
    candidates: [],
    provider: cfg.provider,
    model: cfg.model,
    usage: { cost_usd: null, input_tokens: null, output_tokens: null, context_bytes: null },
    latency_ms: null,
    correlation_id: null,
    request_id: null,
    fingerprint: null,
    heuristic: checkpoint.heuristic,
    outcome: null,
    skipped_reason: null,
  };
}

/** Один заход наблюдателя. Всегда заканчивается записью (решение или skip) и
 *  никогда не бросает наружу: сырой таймер не должен уронить сессию. */
async function runDecision(sessionId: string, checkpoint: Checkpoint): Promise<void> {
  const cfg = config();
  if (!enabled(cfg)) return;
  const state = sessions.get(sessionId);
  if (!state) return;
  const record = baseRecord(checkpoint, sessionId, cfg);
  record.task_revision = checkpoint.revision ?? state.task.revision;
  record.task_context = checkpoint.task ?? taskView(state.task);
  const skip = async (reason: string) => {
    record.status = "skipped";
    record.skipped_reason = reason;
    await appendReceipt(cfg.receipt_path, boundReceipt(record));
  };

  if (!isCurrent(state.task, checkpoint.revision ?? state.task.revision, checkpoint.inputRevision ?? state.task.inputRevision)) {
    return void (await skip("stale_context"));
  }
  if (historicalBudgetUnknown) return void (await skip("historical_budget_unknown"));
  if (inflightSessions.has(sessionId)) return void (await skip("single_flight"));
  if (Date.now() - state.lastCallAt < cfg.cooldown_ms) return void (await skip("cooldown"));
  const gate = decisionGate(checkpoint.kind, state.decisions, cfg.max_decisions_per_session);
  if (gate) return void (await skip(gate));
  // Только TypeSafe-путь проверен: неизвестный провайдер — это пропуск, а не
  // молчаливое использование TypeSafe под чужим именем. Проверка стоит до
  // чтения ключа и до загрузки вендора.
  if (cfg.provider !== "typesafe") return void (await skip("unsupported_provider"));

  inflightSessions.add(sessionId);
  try {
    let apiKey = "";
    try {
      apiKey = (await readFile(cfg.api_key_path, "utf8")).trim();
    } catch {
      apiKey = "";
    }
    if (!apiKey) return void (await skip("no_api_key")); // содержимое ключа не читаем, не пишем, не логируем

    const upstream = await loadUpstream(cfg.upstream_entry, cfg.upstream_provider_entry);
    if (!upstream) return void (await skip("upstream_unavailable"));

    record.fingerprint = await metadataFingerprint();
    const provider = new upstream.TypeSafeProvider({
      apiKey,
      endpoint: cfg.endpoint,
      model: cfg.model,
      timeoutMs: cfg.provider_timeout_ms,
    });
    // Count attempts before the network call; crashes/resume cannot replenish spend.
    state.decisions += 1;
    state.lastCallAt = Date.now();
    persistState(sessionId, state);
    const decision = await upstream.routeRequest(buildRequest(checkpoint, state, cfg), {
      provider,
      maxContextBytes: cfg.max_context_bytes,
      policy: { min_confidence: cfg.min_confidence, max_risk: "high" },
    });


    const outcome = readOutcome(decision, cfg);
    record.status = outcome.status;
    record.selected = outcome.selected;
    record.confidence = outcome.confidence;
    record.probabilities = outcome.probabilities;
    record.fallback = outcome.fallbackType ? { type: outcome.fallbackType } : null;
    record.candidates = outcome.candidates;
    record.provider = outcome.provider;
    record.model = outcome.model ?? cfg.model;
    record.latency_ms = outcome.latencyMs;
    record.usage = {
      cost_usd: outcome.usage.cost,
      input_tokens: outcome.usage.inputTokens,
      output_tokens: outcome.usage.outputTokens,
      context_bytes: outcome.contextBytes,
    };
    record.correlation_id = outcome.correlationId;
    record.request_id = outcome.requestId;
    const current = sessions.get(sessionId) === state && isCurrent(state.task, checkpoint.revision ?? state.task.revision, checkpoint.inputRevision ?? state.task.inputRevision);
    record.outcome = current ? (cfg.mode === "advisory" ? { advisory: "pending" } : null) : { advisory: "discarded", reason: "stale_context" };
    await appendReceipt(cfg.receipt_path, boundReceipt(record));

    // Совет готовим только в advisory и только по закрытому набору: в сообщение
    // идёт наш id и наша цифра уверенности, никакого провайдерского текста.
    if (
      cfg.mode === "advisory" &&
      outcome.status === "selected" &&
      current &&
      outcome.selected && Object.hasOwn(CANDIDATE_NAME, outcome.selected) &&
      (outcome.confidence ?? 0) >= cfg.min_confidence
    ) {
      const name = CANDIDATE_NAME[outcome.selected] ?? outcome.selected;
      state.pendingAdvisory = {
        correlationId: outcome.correlationId ?? "unknown",
        candidateId: outcome.selected,
        confidence: outcome.confidence ?? 0,
        checkpoint: checkpoint.kind,
        revision: checkpoint.revision ?? state.task.revision,
        inputRevision: checkpoint.inputRevision ?? state.task.inputRevision,
        content: clip(
          `JEV advisory (non-authoritative, external decision observer): the observer recommends "${name}" (${outcome.selected}) ` +
            `with confidence ${(outcome.confidence ?? 0).toFixed(2)} for checkpoint "${checkpoint.kind}". This is advice only — it does not ` +
            `authorize, block, retry, or change tools, models, or your current work. Weigh it and continue normally.`,
          700,
        ),
      };
    }
  } catch {
    try {
      record.status = "skipped";
      record.skipped_reason = "internal_error";
      await appendReceipt(cfg.receipt_path, boundReceipt(record));
    } catch {
      /* ни при каких обстоятельствах не выходим наружу */
    }
  } finally {
    inflightSessions.delete(sessionId);
  }
}

/** Планировщик: наружу не отдаём промис и не ждём сеть в горячем обработчике. */
function schedule(sessionId: string, checkpoint: Checkpoint): void {
  try {
    if (!enabled(config())) return;
    const state = sessions.get(sessionId);
    if (!state) return;
    const snapshot = { ...checkpoint, task: taskView(state.task), revision: state.task.revision, inputRevision: state.task.inputRevision };
    setTimeout(() => {
      void runDecision(sessionId, snapshot).catch(() => {});
    }, 0);
  } catch {
    /* сессия важнее наблюдателя */
  }
}

// ------------------------------------------------------------------ эвристики

const CORRECTION_RE =
  /\b(?:wrong|incorrect|not working|doesn'?t work|broken|bug|fix this|regression)\b|(?:не работает|не так|неправильно|неверно|ошибка|исправь|поправь|сломал|сломалось|косяк|баг)/i;
const SCOPE_CHANGE_RE =
  /\b(?:also|additionally|new request|separately|as well as|one more thing)\b|(?:и ещё|и еще|новый запрос|отдельно|дополнительно|ещё нужно|еще нужно|плюс ещё|плюс еще|и ещё одно)/i;
const DONE_CLAIM_RE =
  /\b(?:done|complete|completed|finished|implemented|shipped|ready|all set|everything is (?:done|in place)|no further work)\b|(?:готово|завершен|завершён|сделано|выполнено|реализовано|доделано|всё готово|все готово)/i;
/** Только реальные строки git commit/push: начало команды или звено цепочки. */
const GIT_COMMIT_OR_PUSH_RE = /(?:^|[;&|\n])\s*git\s+(?:-[^\s;&|]{1,32}\s+)*(commit|push)\b/m;

function textOf(message: unknown): string {
  if (typeof message === "string") return message;
  const record = asRecord(message);
  if (!record) return "";
  const content = record.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  let out = "";
  for (const part of content) {
    const chunk = asRecord(part);
    if (chunk && chunk.type === "text") out += String(chunk.text ?? "");
  }
  return out;
}

function lastAssistantText(event: { last_assistant_message?: unknown; messages?: unknown }): string {
  const direct = textOf(event.last_assistant_message);
  if (direct) return direct;
  if (!Array.isArray(event.messages)) return "";
  for (let i = event.messages.length - 1; i >= 0; i--) {
    const message = asRecord(event.messages[i]);
    if (message?.role === "assistant") {
      const text = textOf(message);
      if (text) return text;
    }
  }
  return "";
}

function contextPercent(ctx: ExtensionContext | undefined): number | null {
  try {
    const usage = ctx?.getContextUsage?.();
    return usage && typeof usage.percent === "number" && Number.isFinite(usage.percent) ? usage.percent : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------- расширение

export default function jevShadow(pi: ExtensionAPI): void {
  const activate = (_event: unknown, ctx: ExtensionContext) => {
    try {
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const previous = sessions.get(sessionId);
      const cfg = config();
      const historical = cfg ? restoreHistoricalBudget(cfg, sessionId) : { decisions: 0, lastCallAt: 0 };
      const state: SessionState = { decisions: Math.max(previous?.decisions ?? 0, historical.decisions), compactions: previous?.compactions ?? 0,
        budgetFlagged: previous?.budgetFlagged ?? false, lastCallAt: Math.max(previous?.lastCallAt ?? 0, historical.lastCallAt),
        task: emptyTask(), pendingAdvisory: null };
      // Spend is session-wide; task state follows only the active branch.
      for (const entry of ctx.sessionManager.getEntries()) {
        if (entry.type !== "custom" || entry.customType !== "jev-task-state") continue;
        const saved = asRecord(entry.data);
        if (saved?.schema !== 2) continue;
        if (typeof saved.decisions === "number" && Number.isSafeInteger(saved.decisions) && saved.decisions >= 0) state.decisions = Math.max(state.decisions, saved.decisions);
        if (typeof saved.lastCallAt === "number" && Number.isSafeInteger(saved.lastCallAt) && saved.lastCallAt >= 0) state.lastCallAt = Math.max(state.lastCallAt, saved.lastCallAt);
      }
      for (const entry of ctx.sessionManager.getBranch()) {
        if (entry.type === "custom" && entry.customType === "jev-task-state") {
          const saved = asRecord(entry.data);
          if (saved?.schema !== 2) continue;
          state.task = restoreTask(saved.task);
          if (typeof saved.compactions === "number" && Number.isSafeInteger(saved.compactions) && saved.compactions >= 0) state.compactions = saved.compactions;
          state.budgetFlagged = saved.budgetFlagged === true;
        } else if (entry.type === "message" && asRecord(entry.message)?.role === "user") {
          const input = textOf(entry.message);
          if (input && redactText(input) !== state.task.latestInput) observeInput(state.task, input, CORRECTION_RE.test(input));
        }
      }
      sessions.set(sessionId, state);
      persistors.set(sessionId, (current) => {
        if (humanSessionKey(ctx) !== sessionId || sessions.get(sessionId) !== current) return;
        pi.appendEntry("jev-task-state", { schema: 2, decisions: current.decisions, compactions: current.compactions,
          budgetFlagged: current.budgetFlagged, lastCallAt: current.lastCallAt, task: current.task });
      });
    } catch {
      // Restoring an observer must not block opening a session.
    }
  };
  pi.on("session_start", activate);
  pi.on("session_switch", activate);
  pi.on("session_branch", activate);
  pi.on("session_tree", activate);

  const fact = Type.Object({
    status: Type.String({ maxLength: 40 }),
    detail: Type.Optional(Type.String({ maxLength: 2000 })),
  }, { additionalProperties: false });
  pi.registerTool({
    name: "jev_context",
    label: "JEV task context",
    description: "Update bounded redacted observer context from the existing task/todo/plan: acceptance, blocker, verification and pending delivery. Claims are not proof or authorization. Use new_task + goal only for an explicit independent task boundary, never for /commit, push or continue. No secrets, cookies, payloads or personal data.",
    approval: "write",
    parameters: Type.Object({
      new_task: Type.Optional(Type.Boolean()),
      goal: Type.Optional(Type.String({ maxLength: 2000 })),
      acceptance: Type.Optional(Type.Array(Type.String({ maxLength: 1000 }), { maxItems: 6 })),
      environment: Type.Optional(fact),
      verification: Type.Optional(fact),
      delivery: Type.Optional(Type.Object({
        target: Type.Optional(Type.String({ maxLength: 400 })),
        pending: Type.Optional(Type.Array(Type.String({ maxLength: 1000 }), { maxItems: 6 })),
        delivered: Type.Optional(Type.Array(Type.String({ maxLength: 1000 }), { maxItems: 6 })),
      }, { additionalProperties: false })),
    }, { additionalProperties: false }),
    async execute(_id, params, _signal, _update, ctx) {
      const sessionId = humanSessionKey(ctx);
      if (!sessionId || !enabled(config())) return { content: [{ type: "text", text: "JEV observer disabled or non-human session; no context update." }], details: {} };
      const state = stateOf(sessionId);
      updateTask(state.task, params);
      state.pendingAdvisory = null;
      persistState(sessionId, state);
      if (params.new_task === true) schedule(sessionId, { kind: "scope_change", source: "tool_call", heuristic: false,
        action: "explicit task boundary", goal: state.task.originalGoal, turnPercent: null });
      return { content: [{ type: "text", text: JSON.stringify(taskView(state.task)) }], details: { observer_only: true } };
    },
  });

  // input: один приоритетный чекпойнт — правка по фидбеку важнее смены скоупа.
  pi.on("input", (event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg)) return;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const text = clip(event.text ?? "", 2000);
      if (!text) return;
      const state = stateOf(sessionId);
      observeInput(state.task, text, CORRECTION_RE.test(text));
      state.pendingAdvisory = null;
      persistState(sessionId, state);

      if (CORRECTION_RE.test(text)) {
        schedule(sessionId, {
          kind: "correction_feedback",
          source: "input",
          heuristic: true,
          action: "user correction feedback",
          goal: state.task.originalGoal,
          turnPercent: null,
        });
      } else if (SCOPE_CHANGE_RE.test(text)) {
        schedule(sessionId, {
          kind: "scope_change",
          source: "input",
          heuristic: true,
          action: "user scope-change wording",
          goal: state.task.originalGoal,
          turnPercent: null,
        });
      }
    } catch {
      /* не мешаем сессии */
    }
  });

  // tool_call: `task` — прямой сигнал dispatch, `bash` — только отпечаток git.
  pi.on("tool_call", (event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg)) return;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const state = stateOf(sessionId);
      if (event.toolName === "task") {
        schedule(sessionId, {
          kind: "worker_dispatch",
          source: "tool_call",
          heuristic: false,
          action: "task tool dispatch",
          goal: state.task.originalGoal,
          turnPercent: null,
        });
        return;
      }
      if (event.toolName !== "bash") return;
      const input = asRecord(event.input);
      const command = typeof input?.command === "string" ? clip(input.command, 4000) : "";
      if (!command) return;
      const match = GIT_COMMIT_OR_PUSH_RE.exec(command);
      if (!match) return;
      if (!markGitBatch(state.task)) return;
      persistState(sessionId, state);
      // Наружу уходит только закрытый отпечаток, а не строка команды.
      schedule(sessionId, {
        kind: "commit_or_push",
        source: "tool_call",
        heuristic: true,
        action: `git ${match[1]}`,
        goal: state.task.originalGoal,
        turnPercent: null,
      });
    } catch {
      /* не мешаем сессии */
    }
  });

  // session_compact: считаем, реагируем только на вторую и последующие.
  pi.on("session_compact", (_event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg)) return;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const state = stateOf(sessionId);
      state.compactions += 1;
      persistState(sessionId, state);
      if (state.compactions >= 2) {
        schedule(sessionId, {
          kind: "second_compaction",
          source: "session_compact",
          heuristic: false,
          action: `compaction #${state.compactions}`,
          goal: state.task.originalGoal,
          turnPercent: null,
        });
      }
    } catch {
      /* не мешаем сессии */
    }
  });

  // turn_end: производный чекпойнт по порогу контекста, один раз за сессию.
  pi.on("turn_end", (_event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg)) return;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const state = stateOf(sessionId);
      if (state.budgetFlagged) return;
      const percent = contextPercent(ctx);
      if (percent === null || percent < cfg.context_budget_percent) return;
      state.budgetFlagged = true;
      persistState(sessionId, state);
      schedule(sessionId, {
        kind: "budget_exceeded",
        source: "turn_end",
        heuristic: true,
        action: `context usage ${Math.round(percent)}%`,
        goal: state.task.originalGoal,
        turnPercent: percent,
      });
    } catch {
      /* не мешаем сессии */
    }
  });

  // session_stop: только явный claim о завершении, не каждый простой.
  pi.on("session_stop", (event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg)) return;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const reply = lastAssistantText(event);
      if (!reply || reply.length > 20000 || !DONE_CLAIM_RE.test(reply)) return;
      const state = stateOf(sessionId);
      state.task.completionClaim = redactText(reply, cfg.max_string_chars);
      persistState(sessionId, state);
      schedule(sessionId, {
        kind: "done_claim",
        source: "session_stop",
        heuristic: true,
        action: "assistant completion claim",
        goal: state.task.originalGoal,
        turnPercent: null,
      });
    } catch {
      /* не мешаем сессии */
    }
  });

  // before_agent_start: единственная точка выдачи совета — и только из
  // заранее готового pending, ровно один раз. Промисов здесь нет.
  pi.on("before_agent_start", (_event, ctx) => {
    try {
      const cfg = config();
      if (!enabled(cfg) || cfg.mode !== "advisory") return undefined;
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return undefined;
      const state = sessions.get(sessionId);
      const advisory = state?.pendingAdvisory;
      if (!state || !advisory) return undefined;
      state.pendingAdvisory = null;
      if (!isCurrent(state.task, advisory.revision, advisory.inputRevision) || !Object.hasOwn(CANDIDATE_NAME, advisory.candidateId)) return undefined;
      void appendReceipt(cfg.receipt_path, {
        record: "outcome",
        ts: new Date().toISOString(),
        session_id: sessionId,
        correlation_id: advisory.correlationId,
        outcome: {
          advisory: "injected",
          candidate: advisory.candidateId,
          confidence: advisory.confidence,
          checkpoint: advisory.checkpoint,
        },
      }).catch(() => {});
      return { message: { customType: "jev-advisory", content: advisory.content, display: false } };
    } catch {
      return undefined;
    }
  });

  // session_shutdown: гасим незакрытый совет и состояние сессии.
  pi.on("session_shutdown", (_event, ctx) => {
    try {
      const sessionId = humanSessionKey(ctx);
      if (!sessionId) return;
      const state = sessions.get(sessionId);
      sessions.delete(sessionId);
      persistors.delete(sessionId);
      const cfg = config();
      const advisory = state?.pendingAdvisory;
      if (!cfg || !advisory) return;
      void appendReceipt(cfg.receipt_path, {
        record: "outcome",
        ts: new Date().toISOString(),
        session_id: sessionId,
        correlation_id: advisory.correlationId,
        outcome: { advisory: "expired", reason: "session_ended_before_next_turn" },
      }).catch(() => {});
    } catch {
      /* не мешаем shutdown */
    }
  });
}
