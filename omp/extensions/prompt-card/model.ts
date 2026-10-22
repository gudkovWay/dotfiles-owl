/**
 * Prompt card — branch metadata model.
 *
 * Pure, allocation-conscious reconstruction of the card's per-branch state from
 * persisted session entries. Nothing here renders, schedules or touches the
 * terminal: `view.ts` owns presentation, `index.ts` owns lifecycle.
 *
 * Sources of truth (upstream, read-only):
 * - entry shapes: `@oh-my-pi/pi-coding-agent/session/session-entries`
 * - goal-mode payload: `goalFromModeData` in `@oh-my-pi/pi-coding-agent/goals/state`
 *   (a `mode_change` entry carries `{ goal }` in `data`; `mode` is `"goal"` /
 *   `"goal_paused"` while a goal is tracked and `"none"` on goal-mode exit)
 * - user message shape (`role` / `content` / `attribution` / `timestamp`):
 *   `@oh-my-pi/pi-ai` `UserMessage`. Upstream attributes a synthetic or
 *   agent-originated prompt as `"agent"` (`agent-session.ts`:
 *   `options?.attribution ?? (options?.synthetic ? "agent" : "user")`), so
 *   `"user"`/absent attribution is real input.
 *
 * Every reader below round-trips the exact original bytes: display-time
 * sanitising is the view's job, never the model's.
 */

import { goalFromModeData } from "@oh-my-pi/pi-coding-agent/goals/state";
import type { SessionEntry } from "@oh-my-pi/pi-coding-agent/session/session-entries";

/** One captured prompt. */
export interface PromptRecord {
	/** Exact user text as submitted — never rewritten, labelled, trimmed or truncated. */
	text: string;
	/** Number of image attachments submitted alongside the text. */
	images: number;
	/**
	 * Wall-clock submission time in milliseconds (the user message's own
	 * `timestamp`), not the time a queued prompt was delivered. Ordering by this
	 * value is what keeps a late delivery of an older queued prompt from
	 * displacing a newer submission.
	 */
	timestamp: number;
}

/** Native goal-mode objective, shown on the objective tab when no pin exists. */
export interface CardGoal {
	text: string;
	paused: boolean;
}

export interface CardModel {
	submitted?: PromptRecord;
	responding?: PromptRecord;
	/** Local objective pinned by the user. Metadata only — never enables goal mode. */
	pin?: string;
	/** Objective of the session's real goal mode, when one is active. */
	goal?: CardGoal;
	/** Circle-progress motion; branch-local preference. */
	motion: boolean;
}

export interface CardSnapshot {
	model: CardModel;
	busy: boolean;
	pending: boolean;
	waiting: boolean;
	frame: number;
}

export type CardSection = "submitted" | "responding" | "objective";

/** Custom entry type: last user-submitted prompt. */
export const SUBMITTED_ENTRY = "q.prompt-card.submitted";
/** Custom entry type: prompt the agent is answering. */
export const RESPONDING_ENTRY = "q.prompt-card.responding";
/** Custom entry type: pinned local objective. */
export const PIN_ENTRY = "q.prompt-card.pin";
/** Custom entry type: motion preference. */
export const MOTION_ENTRY = "q.prompt-card.motion";

/** Motion default when the branch carries no MOTION_ENTRY. */
export const DEFAULT_MOTION = true;

/** Data payload of a PIN_ENTRY. Absent data (or empty text) clears the pin. */
export interface CardPinData {
	text: string;
}

/** Data payload of a MOTION_ENTRY. */
export interface CardMotionData {
	enabled: boolean;
}

/** Modes that mean the session is tracking a goal. */
const GOAL_MODES: Record<string, true> = { goal: true, goal_paused: true };

/** Goal statuses that are no longer an objective worth showing. */
const TERMINAL_GOAL_STATUSES: Record<string, true> = { complete: true, dropped: true };

/**
 * Reconstruct the card model from a branch, ordered root → leaf
 * (`SessionManager.getBranch()`).
 *
 * - `reset_boundary` (`/clear`) drops the card's own content: submitted,
 *   responding and pin. Motion and goal-mode tracking survive, because
 *   `resetSessionContext()` drops the transcript only — it never exits goal or
 *   plan mode, so a surviving goal is still the objective being pursued.
 * - Custom metadata from this extension wins; user-attributed persisted
 *   messages are a fallback so older sessions (or a branch without extension
 *   entries) still show a prompt. Generated notices never qualify: developer
 *   roles, synthetic prompts and `attribution: "agent"` are skipped.
 * - `submitted` is the newest *submission* by `PromptRecord.timestamp`, so a
 *   queued older prompt delivered after a newer one cannot displace it.
 * - `responding` follows admission/branch order instead: a delayed older
 *   follow-up accepted after a newer steer is the prompt actually being
 *   answered. Explicit RESPONDING_ENTRY metadata stays authoritative;
 *   message-derived responding (also last-in-branch wins) is used only when no
 *   valid entry follows the last reset boundary.
 * - The native goal is read from `mode_change` entries alone and is cleared
 *   only by an actual goal-mode exit (`mode: "none"` while a goal mode was
 *   live), never by an unrelated mode change such as plan or vibe toggling.
 */
export function readCardModel(entries: readonly SessionEntry[]): CardModel {
	let submitted: PromptRecord | undefined;
	let responding: PromptRecord | undefined;
	let respondingFromMetadata = false;
	let messageResponding: PromptRecord | undefined;
	let pin: string | undefined;
	let goal: CardGoal | undefined;
	let goalModeActive = false;
	let motion = DEFAULT_MOTION;

	for (const entry of entries) {
		if (entry.type === "reset_boundary") {
			submitted = undefined;
			responding = undefined;
			respondingFromMetadata = false;
			messageResponding = undefined;
			pin = undefined;
			continue;
		}

		if (entry.type === "custom") {
			switch (entry.customType) {
				case SUBMITTED_ENTRY: {
					const record = readPromptRecord(entry.data);
					if (record && (record.text.length > 0 || record.images > 0)) {
						if (!submitted || record.timestamp >= submitted.timestamp) submitted = record;
					}
					break;
				}
				case RESPONDING_ENTRY: {
					const record = readPromptRecord(entry.data);
					if (record && (record.text.length > 0 || record.images > 0)) {
						// Admission/branch order decides the current prompt: a later
						// accepted prompt wins even when its submission time is older.
						responding = record;
						respondingFromMetadata = true;
					}
					break;
				}
				case PIN_ENTRY: {
					const text = readPinData(entry.data);
					if (text !== undefined) pin = text.trim().length > 0 ? text : undefined;
					break;
				}
				case MOTION_ENTRY: {
					const enabled = readMotionData(entry.data);
					if (enabled !== undefined) motion = enabled;
					break;
				}
			}
			continue;
		}

		if (entry.type === "mode_change") {
			if (GOAL_MODES[entry.mode] === true) {
				goalModeActive = true;
				const native = goalFromModeData(entry.data);
				const objective = native?.objective.trim();
				// A finished goal is no longer an objective; the exit record that
				// follows re-affirms the cleared state.
				goal =
					native && objective && TERMINAL_GOAL_STATUSES[native.status] !== true
						? { text: native.objective, paused: entry.mode === "goal_paused" || native.status === "paused" }
						: undefined;
			} else if (entry.mode === "none" && goalModeActive) {
				goalModeActive = false;
				goal = undefined;
			}
			continue;
		}

		if (entry.type === "message" && entry.message.role === "user") {
			const message = entry.message;
			// Generated notices are synthetic and/or agent-attributed; only a real
			// typed or RPC submission is a user prompt.
			if (message.attribution === "agent" || message.synthetic === true) continue;
			const record = recordFromContent(message.content, message.timestamp);
			if (record.text.length === 0 && record.images === 0) continue;
			// Strictly newer only: a delivered message sharing the explicit
			// SUBMITTED_ENTRY's millisecond must not replace the raw submitted text
			// with the transformed delivered content.
			if (!submitted || record.timestamp > submitted.timestamp) submitted = record;
			// Admission order decides the current prompt: the last qualifying user
			// message on the branch is the one being answered.
			messageResponding = record;
		}
	}

	if (!respondingFromMetadata && messageResponding) responding = messageResponding;

	const model: CardModel = { motion };
	if (submitted) model.submitted = submitted;
	if (responding) model.responding = responding;
	if (pin !== undefined) model.pin = pin;
	if (goal) model.goal = goal;
	return model;
}

/**
 * Build a {@link PromptRecord} from persisted or live content.
 *
 * Accepts a plain string or the typed `(TextContent | ImageContent)[]` shape.
 * Text blocks are concatenated with no separator — the upstream convention
 * (`parts.join("")`) — so single-block content round-trips byte-for-byte; no
 * synthetic labels are ever injected into `text`. Non-text, non-image blocks
 * are ignored.
 */
export function recordFromContent(content: unknown, timestamp: number): PromptRecord {
	const submittedAt = Number.isFinite(timestamp) ? timestamp : 0;
	if (typeof content === "string") return { text: content, images: 0, timestamp: submittedAt };
	if (!Array.isArray(content)) return { text: "", images: 0, timestamp: submittedAt };

	const blocks: unknown[] = content;
	let text = "";
	let textBlocks = 0;
	let images = 0;
	for (const block of blocks) {
		if (typeof block !== "object" || block === null) continue;
		if (!("type" in block)) continue;
		if (block.type === "text") {
			if ("text" in block && typeof block.text === "string") {
				// A single text block (the common case) keeps the original string
				// reference: no join allocation, and consumers can key derived rows
				// on string identity. Multiple blocks concatenate, matching
				// `parts.join("")`.
				text = textBlocks === 0 ? block.text : text + block.text;
				textBlocks++;
			}
		} else if (block.type === "image") {
			images++;
		}
	}
	return { text, images, timestamp: submittedAt };
}

/**
 * The exact original text of a section, for clipboard and pinning.
 *
 * `objective` prefers the explicit local pin and falls back to the real goal
 * objective. Returns `undefined` when the section holds no copyable text (an
 * image-only prompt has no text to copy).
 */
export function sectionText(snapshot: CardSnapshot, section: CardSection): string | undefined {
	const { model } = snapshot;
	let candidate: string | undefined;
	if (section === "submitted") candidate = model.submitted?.text;
	else if (section === "responding") candidate = model.responding?.text;
	else if (section === "objective") candidate = model.pin ?? model.goal?.text;
	return candidate !== undefined && candidate.trim().length > 0 ? candidate : undefined;
}

/** Validate persisted SUBMITTED_ENTRY / RESPONDING_ENTRY data. */
export function readPromptRecord(value: unknown): PromptRecord | undefined {
	if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
	if (!("text" in value) || typeof value.text !== "string") return undefined;
	if (!("timestamp" in value) || typeof value.timestamp !== "number" || !Number.isFinite(value.timestamp)) {
		return undefined;
	}
	const text = value.text;
	const timestamp = value.timestamp;
	let images = 0;
	if ("images" in value) {
		const raw = value.images;
		if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) images = Math.floor(raw);
	}
	return { text, images, timestamp };
}

/**
 * Read persisted PIN_ENTRY data. Returns the pinned text (empty when the entry
 * carries no payload, which means "cleared"), or `undefined` when the payload
 * is not a valid pin record and must be ignored.
 */
export function readPinData(value: unknown): string | undefined {
	if (value === undefined || value === null) return "";
	if (typeof value !== "object" || Array.isArray(value)) return undefined;
	if (!("text" in value) || typeof value.text !== "string") return undefined;
	return value.text;
}

/** Read persisted MOTION_ENTRY data; `undefined` when the payload is invalid. */
export function readMotionData(value: unknown): boolean | undefined {
	if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
	if (!("enabled" in value) || typeof value.enabled !== "boolean") return undefined;
	return value.enabled;
}
