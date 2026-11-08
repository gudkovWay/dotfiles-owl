/** One dock surface. Only an explicitly focused card handles local keys.
 * Foreground-only copper joinery leaves Kitty's background and outer frame intact.
 */
import {
	decodePrintableKey, isKeyRelease, isKeyRepeat, matchesKey, padding, ScrollView,
	truncateToWidth, visibleWidth, wrapTextWithAnsi, replaceTabs,
} from "@oh-my-pi/pi-tui";
import type { Component, TUI } from "@oh-my-pi/pi-tui";
import { sanitizeText } from "@oh-my-pi/pi-utils";
import type { CardSection, CardSnapshot } from "./model";
import { sectionText } from "./model";

export interface CardActions {
	copy(text: string): Promise<void>;
	pin(text: string): void;
	unpin(): void;
}

export const PROMPT_CARD_WIDTH = 60;
export const PROMPT_CARD_MAX_ROWS = 6;
const SECTIONS: readonly CardSection[] = ["submitted", "objective", "plan", "session"];
const LABELS: Record<CardSection, string> = {
	submitted: "Запрос", objective: "Цель", plan: "План", session: "Сессия",
};
const RU: Record<string, string> = { h: "р", j: "о", k: "л", l: "д", y: "н", c: "с", p: "з", u: "г", z: "я" };
const SGR = {
	text: "38;2;231;215;188", muted: "38;2;181;163;143", copper: "38;2;194;140;89",
	blue: "38;2;137;201;229", blueSoft: "38;2;143;176;194", error: "38;2;255;180;171",
	selected: "4;58;2;194;140;89;38;2;137;201;229",
} as const;
const EMPTY: readonly string[] = [];
const NAVIGATION = ["escape", "tab", "shift+tab", "up", "down", "shift+up", "shift+down", "pageUp", "pageDown", "home", "end", "1", "2", "3", "4"] as const;
const LOCAL_KEYS = ["h", "j", "k", "l", "y", "c", "p", "u", "z"] as const;

function paint(role: keyof typeof SGR, text: string): string {
	const start = `\x1b[${SGR[role]}m`;
	return `${start}${text.replaceAll("\x1b[0m", `\x1b[0m${start}`)}\x1b[0m`;
}

function fit(text: string, width: number): string {
	const clipped = truncateToWidth(text, Math.max(0, width));
	return clipped + padding(Math.max(0, width - visibleWidth(clipped)));
}

function key(data: string, latin: keyof typeof RU): boolean {
	return matchesKey(data, latin) || data === RU[latin] || decodePrintableKey(data) === RU[latin];
}

/** Shared cell geometry: open doubled TL joint and matching stepped BR foot.
 * The selected tab's underline uses copper independently of its blue text.
 */
function frame(lines: readonly string[], width: number): readonly string[] {
	if (width < 12 || lines.length < 3) return lines.map(line => fit(line, width));
	const rows: string[] = [];
	for (let i = 0; i < lines.length; i++) {
		const left = i === 0 ? "╔══ " : i === 1 ? "║┌─ " : "    ";
		const right = i === lines.length - 1 ? "══╝" : i === lines.length - 2 ? "─┘║" : "   ";
		rows.push(`${paint("copper", left)}${fit(lines[i], width - 7)}${paint("copper", right)}`);
	}
	return rows;
}

/** Reserve space for the native composer before bounding the card's viewport. */
export function promptCardHeight(rows: number): number {
	const safe = Number.isFinite(rows) ? Math.max(1, Math.trunc(rows)) : 1;
	return Math.max(1, Math.min(PROMPT_CARD_MAX_ROWS, Math.floor(safe / 3)));
}

interface ContentCache {
	width: number;
	capacity: number;
	section: CardSection;
	model: CardSnapshot["model"];
	session: CardSnapshot["session"];
	reference: string | undefined;
	lines: readonly string[];
}

export class ContextCard implements Component {
	readonly #getSnapshot: () => CardSnapshot;
	readonly #getRows: () => number;
	readonly #tui: TUI;
	readonly #actions: CardActions;
	readonly #editor: Component | null;
	readonly #scroll = new ScrollView(EMPTY, {
		height: 0, theme: { track: text => paint("muted", text), thumb: text => paint("copper", text) },
	});
	#focused = false;
	#collapsed = false;
	#section: CardSection | undefined;
	#content: ContentCache | undefined;
	#status: { text: string; error: boolean } | undefined;
	#copying = false;
	#generation = 0;
	#disposed = false;

	constructor(getSnapshot: () => CardSnapshot, getRows: () => number, tui: TUI, actions: CardActions) {
		this.#getSnapshot = getSnapshot;
		this.#getRows = getRows;
		this.#tui = tui;
		this.#actions = actions;
		this.#editor = tui.getFocused();
	}

	get focused(): boolean { return this.#focused; }
	set focused(value: boolean) {
		if (this.#focused === value) return;
		this.#focused = value;
		if (!value) { this.#generation++; this.#status = undefined; }
	}

	open(): boolean {
		if (this.#disposed || this.#getSnapshot().waiting) return false;
		if (this.#focused) return true;
		// Host dialogs own focus; a card opener must never displace one.
		if (!this.#editor || this.#tui.getFocused() !== this.#editor || this.#tui.hasOverlay()) return false;
		this.#section ??= this.#getSnapshot().model.plan.total > 0 ? "plan" : "submitted";
		this.#tui.setFocus(this);
		this.#tui.requestRender();
		return this.#focused;
	}

	close(): void {
		if (this.#tui.getFocused() === this) this.#tui.setFocus(this.#editor);
		this.focused = false;
		this.#tui.requestRender();
	}

	render(paneWidth: number): readonly string[] {
		if (this.#disposed || paneWidth <= 0) return EMPTY;
		const width = Math.min(PROMPT_CARD_WIDTH, Math.max(1, Math.trunc(paneWidth) - (paneWidth > 1 ? 1 : 0)));
		const snapshot = this.#getSnapshot();
		const empty = !snapshot.model.submitted && !snapshot.model.responding && !snapshot.model.pin && !snapshot.model.goal && snapshot.model.plan.total === 0;
		const capacity = promptCardHeight(this.#getRows());
		const compact = this.#getRows() < 30 || paneWidth < PROMPT_CARD_WIDTH;
		const total = this.#focused ? capacity : this.#collapsed || empty ? 1 : compact ? Math.min(2, capacity) : capacity;
		const state = snapshot.waiting ? "ждёт подтверждения" : snapshot.busy ? "работает" : "готов";
		const stateLabel = snapshot.pending ? `${state} · очередь` : state;
		const id = sanitizeText(snapshot.session.id.slice(0, 8));
		const header = paint("copper", `Карточка · ${this.#focused ? "УПРАВЛЕНИЕ" : stateLabel} · ${id}…`);
		let lines: string[];
		if (total === 1) {
			lines = [paint("copper", `${id}…`) + paint("muted", ` · ${stateLabel} · Ctrl+Alt+P` )];
		} else if (!this.#focused) {
			const current = snapshot.model.plan.current;
			const mark = current?.status === "blocked" ? "!" : current?.status === "in_progress" ? "▶" : "□";
			const plan = current
				? `${mark} ${current.content}${current.blocker ? ` · ${current.blocker}` : ""}`
				: snapshot.model.plan.total > 0 ? `План: ${snapshot.model.plan.completed}/${snapshot.model.plan.total} · снято ${snapshot.model.plan.abandoned}` : "План: нет задач";
			const request = snapshot.model.submitted ?? snapshot.model.responding;
			const preview = request?.text || (request?.images ? `${request.images} изображений · без текста` : "Запрос: нет");
			const objective = [snapshot.model.goal ? `Цель OMP: ${snapshot.model.goal.text}` : "", snapshot.model.pin ? `Закреп: ${snapshot.model.pin}` : ""].filter(Boolean).join(" · ");
			const summary = paint(current?.status === "in_progress" ? (snapshot.frame % 2 ? "blue" : "blueSoft") : "text", sanitizeText(plan.slice(0, 2000)).replace(/\s+/g, " "));
			lines = total === 2
				? [paint("copper", `${id}… · ${stateLabel} · Ctrl+Alt+P`), summary]
				: [header, this.#tabs(false, width - 7), summary,
					paint("text", sanitizeText(preview.slice(0, 2000)).replace(/\s+/g, " ")),
					paint("muted", sanitizeText(objective.slice(0, 2000)).replace(/\s+/g, " ")),
					paint("muted", "Ctrl+Alt+P → управление")];
			// A tiny terminal may have only 3–5 rows even outside compact policy.
			if (lines.length > total) lines = [...lines.slice(0, total - 1), paint("muted", "Ctrl+Alt+P → управление")];
		} else {
			const bodyWidth = Math.max(1, width - (width >= 12 && total >= 3 ? 7 : 0));
			const showTabs = total >= 4;
			const bodyRows = Math.max(0, total - 2 - Number(showTabs));
			lines = [header];
			if (showTabs) lines.push(this.#tabs(true, bodyWidth));
			this.#scroll.setHeight(bodyRows);
			this.#updateContent(snapshot, bodyWidth, bodyRows);
			lines.push(...this.#scroll.render(bodyWidth));
			while (lines.length < total - 1) lines.push("");
			lines.push(this.#footer(snapshot, bodyWidth));
		}
		const left = padding(Math.max(0, Math.trunc(paneWidth) - width - (paneWidth > 1 ? 1 : 0)));
		return frame(lines, width).map(line => left + line);
	}

	#tabs(focused: boolean, width: number): string {
		const short = width < 46;
		return SECTIONS.map((section, index) => {

			const label = short ? `${index + 1}${LABELS[section].slice(0, 1)}` : `${index + 1} ${LABELS[section]}`;
			return paint(focused && section === this.#section ? "selected" : "text", label);
		}).join(" ");
	}

	#updateContent(snapshot: CardSnapshot, width: number, capacity: number): void {
		const section = this.#section ?? "submitted";
		const cached = this.#content;
		if (cached && cached.width === width && cached.capacity === capacity && cached.section === section
			&& cached.model === snapshot.model && cached.session === snapshot.session && cached.reference === snapshot.planReference) return;
		let source: string;
		if (section === "plan") {
			const plan = snapshot.model.plan;
			source = plan.total > 0 ? plan.display : "Нет native Todo-плана";
			if (plan.total > 0) source += `\nВыполнено ${plan.completed}/${plan.total} · блок ${plan.blocked} · снято ${plan.abandoned}`;
			if (snapshot.planReference) source += `\nReference runtime: ${snapshot.planReference}\nНаличие/approval файла не проверены`;
		} else if (section === "session") {
			const session = snapshot.session;
			source = `ID: ${session.id}\n${session.name ? `Имя: ${session.name}\n` : ""}CWD: ${session.cwd}\nМодель: ${session.model ?? "неизвестна"}\nEffort: ${session.effort ?? "неизвестен"}`;
		} else if (section === "objective") {
			source = [snapshot.model.goal ? `Цель OMP${snapshot.model.goal.paused ? " · пауза" : ""}: ${snapshot.model.goal.text}` : "Цель OMP: нет",
				snapshot.model.pin !== undefined ? `Локальный закреп: ${snapshot.model.pin}` : "Локальный закреп: нет"].join("\n");
		} else {
			const record = snapshot.model.submitted ?? snapshot.model.responding;
			source = record?.text || (record?.images ? `${record.images} изображений · без текста` : "В этой ветке нет запроса");
			const prepared = snapshot.model.responding;
			if (record && prepared && (prepared.text !== record.text || prepared.images !== record.images)) {
				const text = prepared.text || (prepared.images ? `${prepared.images} изображений · без текста` : "Без текста");
				source += `\n\nЗапрос запуска OMP:\n${text}`;
			}
		}
		const clean = replaceTabs(sanitizeText(source));
		const narrow = wrapTextWithAnsi(clean, Math.max(1, width - 1));
		const lines = narrow.length > capacity ? narrow : wrapTextWithAnsi(clean, width);
		this.#content = { width, capacity, section, model: snapshot.model, session: snapshot.session, reference: snapshot.planReference, lines };
		this.#scroll.setLines(lines.map(line => paint(line.trimStart().startsWith("▶") ? "blue" : "text", line)));
	}

	#footer(snapshot: CardSnapshot, width: number): string {
		if (this.#status) return paint(this.#status.error ? "error" : "copper", sanitizeText(this.#status.text).replace(/\s+/g, " "));
		const pin = this.#section === "submitted";
		if (width < 38) return paint("muted", "h/l j/k · y ID · c · Esc");
		return paint("muted", `h/l · j/k · y ID · c${pin ? " · p" : snapshot.model.pin !== undefined ? " · u" : ""} · z · Esc`);
	}

	capturesInput(data: string): boolean {
		return this.#focused && !this.#disposed && (NAVIGATION.some(name => matchesKey(data, name)) || LOCAL_KEYS.some(name => key(data, name)));
	}

	handleInput(data: string): void {
		if (!this.#focused || this.#disposed || isKeyRelease(data)) return;
		if (matchesKey(data, "escape")) { this.close(); return; }
		const repeat = isKeyRepeat(data);
		const index = SECTIONS.indexOf(this.#section ?? "submitted");
		if (key(data, "h") || matchesKey(data, "shift+tab")) this.#select(SECTIONS[(index + SECTIONS.length - 1) % SECTIONS.length]);
		else if (key(data, "l") || matchesKey(data, "tab")) this.#select(SECTIONS[(index + 1) % SECTIONS.length]);
		else if (key(data, "j")) this.#scroll.scroll(1);
		else if (key(data, "k")) this.#scroll.scroll(-1);
		else if (this.#scroll.handleScrollKey(data)) { /* handled by the native viewport */ }
		else {
			const selected = SECTIONS.findIndex((_section, i) => matchesKey(data, `${i + 1}`));
			if (selected >= 0) this.#select(SECTIONS[selected]);
			else if (!repeat && (key(data, "y") || key(data, "c"))) this.#copy(key(data, "y"));
			else if (!repeat && key(data, "p")) {
				if (this.#section !== "submitted") return;
				const original = sectionText(this.#getSnapshot(), this.#section);
				if (original && original !== this.#getSnapshot().model.pin) {
					try { this.#actions.pin(original); this.#status = { text: "Локальный закреп сохранён", error: false }; }
					catch (error) { this.#error(error); }
				}
			} else if (!repeat && key(data, "u")) {
				if (this.#getSnapshot().model.pin !== undefined) {
					try { this.#actions.unpin(); this.#status = { text: "Локальный закреп снят", error: false }; }
					catch (error) { this.#error(error); }
				}
			} else if (!repeat && key(data, "z")) { this.#collapsed = true; this.close(); return; }
		}
		this.#tui.requestRender();
	}

	#select(section: CardSection): void {
		if (section === this.#section) return;
		this.#section = section;
		this.#status = undefined;
		this.#scroll.scrollToTop();
	}

	#copy(sessionId: boolean): void {
		if (this.#copying) return;
		const snapshot = this.#getSnapshot();
		const original = sessionId ? snapshot.session.id : sectionText(snapshot, this.#section ?? "submitted");
		if (!original) { this.#status = { text: "В разделе нечего копировать", error: true }; return; }
		const id = snapshot.session.id;
		const generation = this.#generation;
		const section = this.#section;
		this.#copying = true;
		this.#status = { text: "Копирование…", error: false };
		void (async () => {
			try {
				await this.#actions.copy(original);
				if (this.#focused && !this.#disposed && generation === this.#generation && id === this.#getSnapshot().session.id && section === this.#section)
					this.#status = { text: sessionId || section === "session" ? "Полный ID скопирован" : "Текст скопирован", error: false };
			} catch (error) {
				if (this.#focused && !this.#disposed && generation === this.#generation && id === this.#getSnapshot().session.id && section === this.#section) this.#error(error);
			} finally {
				this.#copying = false;
				if (!this.#disposed) this.#tui.requestRender();
			}
		})();
	}

	#error(error: unknown): void {
		this.#status = { text: `Ошибка: ${error instanceof Error ? error.message : String(error)}`, error: true };
	}

	invalidate(): void { this.#content = undefined; this.#scroll.invalidate(); }
	dispose(): void {
		if (this.#disposed) return;
		this.close();
		this.#disposed = true;
		this.#content = undefined;
		this.#scroll.dispose();
	}
}