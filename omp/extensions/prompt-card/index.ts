// OMP prompt-card integration: lifecycle, commands, shortcut, heartbeat timer.
// Owns only orchestration; branch metadata extraction lives in ./model,
// Rendering is a single foreground-only dock surface in ./view.
import type {
	ExtensionAPI,
	ExtensionContext,
} from "@oh-my-pi/pi-coding-agent/extensibility/extensions/types";
import { getLatestTodoPhasesFromEntries } from "@oh-my-pi/pi-coding-agent/tools/todo";
import { copyToClipboard } from "@oh-my-pi/pi-coding-agent/utils/clipboard";
import type { TUI } from "@oh-my-pi/pi-tui";
import {
	MOTION_ENTRY,
	PIN_ENTRY,
	RESPONDING_ENTRY,
	readCardModel,
	readCardPlan,
	readPlanReference,
	recordFromContent,
	sectionText,
	SUBMITTED_ENTRY,
} from "./model";
import type { CardSnapshot, PromptRecord } from "./model";
import type { CardActions } from "./view";
import { ContextCard } from "./view";

const WIDGET_KEY = "q.prompt-card.panel";
const HEARTBEAT_MS = 250;

function isMainTui(ctx: ExtensionContext): boolean {
	return ctx.mode === "tui" && ctx.hasUI && ctx.agent.kind === "main";
}


export default function promptCardExtension(pi: ExtensionAPI): void {
	// Field-for-field CardSnapshot: handed out by reference so renders never
	// allocate a fresh snapshot object.
	const state: CardSnapshot = {
		model: readCardModel([]),
		busy: false,
		pending: false,
		waiting: false,
		frame: 0,
		session: { id: "", cwd: "" },
	};

	// Prompt staged by before_agent_start, confirmed against an actually
	// persisted user-attributed message before RESPONDING_ENTRY is written.
	// Synthetic deliveries reach before_agent_start too, so staging alone must
	// never persist.
	let staged: PromptRecord | undefined;
	let heartbeat: Timer | undefined;
	let heartbeatOwner: ExtensionContext | undefined;
	let card: ContextCard | undefined;
	let tui: TUI | undefined;
	let panelOwner: ExtensionContext | undefined;
	let planLeaf: string | null | undefined;

	function getSnapshot(): CardSnapshot {
		// Native todo edits (including /todo and eval) are durable branch entries.
		// Re-read only when that branch changes; rendering never polls an idle timer.
		if (panelOwner && panelOwner.sessionManager.getLeafId() !== planLeaf) {
			const branch = panelOwner.sessionManager.getBranch();
			state.model = { ...state.model, plan: readCardPlan(getLatestTodoPhasesFromEntries(branch)) };
			state.planReference = panelOwner.getPendingPlanReview()?.planFilePath ?? readPlanReference(branch);
			planLeaf = panelOwner.sessionManager.getLeafId();
		}
		return state;
	}

	function stopHeartbeat(): void {
		if (heartbeat !== undefined) {
			heartbeatOwner?.clearTimer(heartbeat);
			heartbeat = undefined;
		}
		heartbeatOwner = undefined;
	}

	function reconcile(ctx: ExtensionContext): void {
		const id = ctx.sessionManager.getSessionId();
		const name = ctx.sessionManager.getSessionName();
		const model = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined;
		const effort = pi.getThinkingLevel();
		const old = state.session;
		if (old.id !== id || old.cwd !== ctx.cwd || old.name !== name || old.model !== model || old.effort !== effort)
			state.session = { id, cwd: ctx.cwd, name, model, effort };
		state.busy = !ctx.isIdle();
		state.pending = ctx.hasPendingMessages();
		// Timer is strictly a functional progress animation: main interactive
		// TUI, busy, no approval pending, motion enabled. Static states redraw
		// at their own events and must not keep an idle queue ticking.
		const animate = isMainTui(ctx) && state.busy && !state.waiting && state.model.motion;
		if (!animate) {
			if (!state.model.motion) state.frame = 0;
			stopHeartbeat();
			return;
		}
		if (heartbeat === undefined) {
			heartbeatOwner = ctx;
			heartbeat = ctx.setInterval(() => {
				reconcile(ctx);
				if (heartbeat !== undefined) state.frame = (state.frame + 1) % 4;
				tui?.requestRender();
			}, HEARTBEAT_MS);
		}
	}

	function refreshModel(ctx: ExtensionContext): void {
		const branch = ctx.sessionManager.getBranch();
		state.model = readCardModel(branch);
		state.planReference = ctx.getPendingPlanReview()?.planFilePath ?? readPlanReference(branch);
		planLeaf = ctx.sessionManager.getLeafId();
	}

	function mountPanel(ctx: ExtensionContext): void {
		card?.dispose();
		panelOwner = ctx;
		const actions: CardActions = {
			copy: copyToClipboard,
			pin: text => {
				if (text === state.model.pin) return;
				pi.appendEntry(PIN_ENTRY, { text });
				state.model = { ...state.model, pin: text };
				tui?.requestRender();
			},
			unpin: () => {
				if (state.model.pin === undefined) return;
				pi.appendEntry(PIN_ENTRY);
				state.model = { ...state.model, pin: undefined };
				tui?.requestRender();
			},
		};
		ctx.ui.setWidget(WIDGET_KEY, tuiInstance => {
			tui = tuiInstance;
			card = new ContextCard(getSnapshot, () => tuiInstance.terminal.rows, tuiInstance, actions);
			return card;
		}, { placement: "aboveEditor" });
	}

	function restore(ctx: ExtensionContext): void {
		if (!isMainTui(ctx)) return;
		// session_start / switch / tree / branch / compact: rebuild branch-local
		// card state from persisted entries (reset_boundary is handled by the
		// model). Branch state is authoritative over any optimistic snapshot.
		refreshModel(ctx);
		state.frame = 0;
		// A staged but unconfirmed delivery belongs to the previous branch;
		// never let it confirm against a different session's user message.
		staged = undefined;
		state.waiting = false;
		reconcile(ctx);
		mountPanel(ctx);
	}

	function closeViewer(): void {
		card?.close();
	}

	function openViewer(ctx: ExtensionContext): void {
		if (!isMainTui(ctx)) return;
		refreshModel(ctx);
		reconcile(ctx);
		card?.open();
	}

	function pinFromCommand(ctx: ExtensionContext, rest: string): void {
		const text = rest.length > 0 ? rest : sectionText(state, "submitted");
		if (!text || text.length === 0) {
			ctx.ui.notify("prompt-card: nothing to pin — usage: /prompt pin [text]", "warning");
			return;
		}
		pi.appendEntry(PIN_ENTRY, { text });
		refreshModel(ctx);
		ctx.ui.notify("prompt-card: objective pinned", "info");
	}

	pi.on("session_start", (_event, ctx) => {
		restore(ctx);
	});

	pi.on("session_switch", (_event, ctx) => {
		closeViewer();
		restore(ctx);
	});

	pi.on("session_branch", (_event, ctx) => {
		closeViewer();
		restore(ctx);
	});

	pi.on("session_tree", (_event, ctx) => {
		closeViewer();
		restore(ctx);
	});

	pi.on("session_compact", (_event, ctx) => {

		if (!isMainTui(ctx)) return;
		// Same session and dock: do not reset the selected tab, scroll or collapse.
		refreshModel(ctx);
		reconcile(ctx);
		tui?.requestRender();
	});

	pi.on("session_before_switch", (_event, _ctx) => {
		closeViewer();
		stopHeartbeat();
	});

	pi.on("session_before_branch", (_event, _ctx) => {
		closeViewer();
		stopHeartbeat();
	});

	pi.on("session_before_tree", (_event, _ctx) => {
		closeViewer();
		stopHeartbeat();
	});

	pi.on("session_shutdown", (_event, _ctx) => {
		closeViewer();
		stopHeartbeat();
	});

	pi.on("input", (event, ctx) => {
		// Card data capture is main interactive TUI only: no persistence or
		// snapshot mutation from subagent/headless/RPC sessions.
		if (!isMainTui(ctx)) return;
		// Actual submitted input; interactive and rpc count, extension-injected
		// input does not. No transform: return without a result.
		if (event.source !== "interactive" && event.source !== "rpc") return;
		if (event.text.length === 0 && (event.images?.length ?? 0) === 0) return;
		const record: PromptRecord = {
			text: event.text,
			images: event.images?.length ?? 0,
			timestamp: Date.now(),
		};
		pi.appendEntry(SUBMITTED_ENTRY, record);
		state.model = { ...state.model, submitted: record };
		tui?.requestRender();
	});

	pi.on("before_agent_start", (event, ctx) => {
		if (!isMainTui(ctx)) return;
		// Delivery-prepared prompt (may aggregate queued steers). Stage only:
		// confirmation happens on a persisted user-attributed message, so
		// cancelled/aborted preparations never write RESPONDING_ENTRY and
		// synthetic developer deliveries can never pose as user prompts.
		if (event.prompt.length === 0 && (event.images?.length ?? 0) === 0) return;
		staged = { text: event.prompt, images: event.images?.length ?? 0, timestamp: Date.now() };
	});

	pi.on("message_end", (event, ctx) => {
		if (!isMainTui(ctx)) return;
		const message = event.message;
		if (message.role === "developer" && message.synthetic === true) {
			staged = undefined;
			return;
		}
		if (message.role !== "user") return;
		// Synthetic auto-continuation prompts travel as role user: their staged
		// candidate must be dropped, never confirmed, and never left behind to
		// be confirmed by a later real user aside. Queued user-only aggregates
		// are unaffected (non-synthetic).
		if (message.synthetic === true) {
			staged = undefined;
			return;
		}
		// Attribution filter: only user-initiated messages confirm the staged
		// delivery; generated developer/system notices and agent-attributed
		// messages are ignored. No assistant token rescans.
		if (message.attribution !== undefined && message.attribution !== "user") {
			staged = undefined;
			return;
		}
		const delivered = recordFromContent(message.content, message.timestamp);
		if (!state.model.submitted || delivered.timestamp > state.model.submitted.timestamp) {
			state.model = { ...state.model, submitted: delivered };
		}
		if (staged !== undefined) {
			const record = staged;
			staged = undefined;
			// Persistence may lag this hook (queued message_end persists before
			// emitting but is not awaited), so set the confirmed record directly
			// instead of scanning the possibly-stale branch; the raw input
			// submission (if newer) stays untouched, and the next branch restore
			// remains authoritative.
			if (record.text.length > 0 || record.images > 0) {
				pi.appendEntry(RESPONDING_ENTRY, record);
				state.model = { ...state.model, responding: record };
			}
		}
		reconcile(ctx);
		tui?.requestRender();
	});

	pi.on("agent_start", (_event, ctx) => {
		if (!isMainTui(ctx)) return;
		state.waiting = false;
		reconcile(ctx);
		tui?.requestRender();
	});

	pi.on("agent_end", (_event, ctx) => {
		if (!isMainTui(ctx)) return;
		// Continuations may already be scheduled (willContinue); reconcile from
		// live context so the heartbeat survives deferred follow-ups and stops
		// once genuinely idle. A terminal settle resets transient states.
		reconcile(ctx);
		refreshModel(ctx);
		if (!state.busy) {
			staged = undefined;
			state.waiting = false;
		}
		tui?.requestRender();
	});

	pi.on("tool_approval_requested", (_event, ctx) => {
		if (!isMainTui(ctx)) return;
		// Static waiting indicator: freeze the animation timer instead of
		// ticking through the wait.
		state.waiting = true;
		closeViewer();
		stopHeartbeat();
		tui?.requestRender();
	});

	pi.on("tool_approval_resolved", (_event, ctx) => {
		if (!isMainTui(ctx)) return;
		state.waiting = false;
		reconcile(ctx);
		tui?.requestRender();
	});

	pi.on("tool_result", (_event, ctx) => {
		if (!isMainTui(ctx)) return;
		// The render reads canonical persisted todo state, including eval commits.
		reconcile(ctx);
		tui?.requestRender();
	});

	pi.on("plan_review_requested", (event, ctx) => {
		if (!isMainTui(ctx)) return;
		state.planReference = event.planFilePath;
		tui?.requestRender();
	});

	pi.on("goal_updated", (event, ctx) => {
		if (!isMainTui(ctx)) return;
		// The goal event may precede the persisted mode_change entry; use the
		// event payload for the live snapshot (state.goal carries the runtime
		// goal in goal mode) and let the next branch restore re-derive it.
		const goal = event.state?.goal ?? event.goal ?? undefined;
		state.model = {
			...state.model,
			goal: goal && goal.status !== "complete" && goal.status !== "dropped"
				? { text: goal.objective, paused: goal.status === "paused" }
				: undefined,
		};
		tui?.requestRender();
	});

	pi.registerShortcut(
		"ctrl+alt+p",
		{
			description: "Open the prompt card viewer",
			handler: (ctx) => {
				if (!isMainTui(ctx)) return;
				openViewer(ctx);
			},
		},
	);

	pi.registerCommand("sid", {
		description: "Copy the full current OMP session UUID: /sid copy",
		handler: async (args, ctx) => {
			if (!isMainTui(ctx)) return;
			if (args.trim() !== "copy") {
				ctx.ui.notify("Usage: /sid copy", "warning");
				return;
			}
			const id = ctx.sessionManager.getSessionId();
			try {

				await copyToClipboard(id);
				if (ctx.sessionManager.getSessionId() === id) ctx.ui.notify("Полный ID сессии скопирован", "info");
			} catch (error) {
				if (ctx.sessionManager.getSessionId() === id)
					ctx.ui.notify(`Ошибка clipboard: ${error instanceof Error ? error.message : String(error)}`, "error");
			}
		},
	});

	pi.registerCommand("prompt", {
		description: "Prompt card: viewer, pin/unpin objective, motion on|off",
		handler: async (args, ctx) => {
			if (!isMainTui(ctx)) return;
			const trimmed = args.trim();
			if (trimmed.length === 0) {
				refreshModel(ctx);
				openViewer(ctx);
				return;
			}
			const [verb] = trimmed.split(/\s+/);
			const rest = trimmed.slice(trimmed.indexOf(verb) + verb.length).trim();
			switch (verb) {
				case "pin":
					pinFromCommand(ctx, rest);
					return;
				case "unpin":
					pi.appendEntry(PIN_ENTRY);
					refreshModel(ctx);
					ctx.ui.notify("prompt-card: pin cleared", "info");
					return;
				case "motion": {
					const value = rest.toLowerCase();
					if (value !== "on" && value !== "off") {
						ctx.ui.notify("prompt-card: usage: /prompt motion on|off", "warning");
						return;
					}
					pi.appendEntry(MOTION_ENTRY, { enabled: value === "on" });
					refreshModel(ctx);
					// Motion toggles drive the animation lifecycle directly.
					reconcile(ctx);
					tui?.requestRender();
					return;
				}
				default:
					ctx.ui.notify(
						"prompt-card: usage: /prompt | /prompt pin [text] | /prompt unpin | /prompt motion on|off",
						"warning",
					);
			}
		},
	});
}