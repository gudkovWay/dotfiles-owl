/**
 * OMP prompt card — terminal surface.
 *
 * `PromptCardPanel` is the permanent compact card above the composer;
 * `PromptCardViewer` is the read-only overlay opened by `/prompt` (or
 * Ctrl+Alt+P). State arrives only through the snapshot getter and the viewer
 * reports user intent only through `CardActions`, so the card never writes the
 * composer, dispatches a prompt, or replays a message: Escape closes the
 * overlay and the core editor is left exactly as it was.
 *
 * The panel is drawn on every frame without a command: a rounded bordered card,
 * right-aligned inside the actual pane width, carrying the last submitted
 * request, an optional supplementary goal row, and the real path to the
 * viewer's actions. It defines no `handleInput`, so the editor keeps the
 * keyboard and the panel can never take focus.
 *
 * The viewer draws a compact rounded panel: a title in the top border, section
 * tabs, a subdued divider, the scrollable original text, keyboard-action
 * capsules for the existing handlers, and a short close/navigation help line.
 * Every row is budgeted before the body is sized, so the panel degrades from
 * the edges in on tiny terminals instead of slicing its own footer.
 *
 * Styling is deliberately limited to the terminal default foreground, the
 * sixteen indexed colours, and the bold/dim attributes. The palette belongs to
 * the terminal (Kitty) and decoration belongs to the compositor, so the card
 * owns neither: no truecolor, no background fill, no glyph art, no copied
 * frame. Prompt text is sanitized (`sanitizeText`) before it is displayed, so
 * user bytes can never open SGR/OSC state, while the untouched original stays
 * the only thing copied or pinned.
 */
import {
	Key,
	ScrollView,
	type Component,
	matchesKey,
	padding,
	replaceTabs,
	truncateToWidth,
	visibleWidth,
	wrapTextWithAnsi,
} from "@oh-my-pi/pi-tui";
import { sanitizeText } from "@oh-my-pi/pi-utils";
import { type CardSection, type CardSnapshot, sectionText } from "./model";

/** Selection and mutation surface the viewer exposes to the integration. */
export interface CardActions {
	close(): void;
	copy(text: string): Promise<void>;
	pin(text: string): void;
	unpin(): void;
}

/** Preferred overlay geometry: a compact panel bottom-right, above the composer. */
export const PROMPT_CARD_WIDTH = 76;
export const PROMPT_CARD_MAX_ROWS = 18;
export const PROMPT_CARD_MARGIN = { top: 1, right: 1, bottom: 4, left: 1 } as const;

/**
 * Total terminal rows the card may occupy on a terminal `rows` high. The
 * overlay margins above and below are reserved first, then the panel is capped
 * at {@link PROMPT_CARD_MAX_ROWS}; a tiny pane still yields at least one row so
 * the renderer can degrade gracefully rather than emit nothing. Pure and
 * allocation-free: the integration calls it directly from `getRows`.
 */
export function promptCardHeight(rows: number): number {
	const safe = Number.isFinite(rows) ? Math.max(1, Math.trunc(rows)) : 1;
	const available = safe - PROMPT_CARD_MARGIN.top - PROMPT_CARD_MARGIN.bottom;
	return Math.max(1, Math.min(PROMPT_CARD_MAX_ROWS, available));
}

const SECTIONS: readonly CardSection[] = ["submitted", "responding", "objective"];

/** Russian section names; `responding` is re-labelled live by {@link sectionTitle}. */
const SECTION_LABELS: Record<CardSection, string> = {
	submitted: "Запрос",
	responding: "Принят",
	objective: "Цель",
};

/**
 * Title-side name of a section. The `responding` record is the last prompt the
 * agent accepted, so it claims live answering only while the agent is actually
 * running; idle it is named for what it holds. The tab row keeps the stable
 * section ids that the plan's key map selects.
 */
function sectionTitle(section: CardSection, snapshot: CardSnapshot): string {
	if (section !== "responding") return SECTION_LABELS[section];
	return snapshot.busy ? "В работе" : "Принят";
}

/** Shown where a section has no original — never copyable and never pinnable. */
const PLACEHOLDERS: Record<CardSection, string> = {
	submitted: "(в этой ветке нет отправленного запроса)",
	responding: "(в этой ветке нет принятого запроса)",
	objective: "(нет закрепа и нет цели в этой ветке)",
};

const HELP = "esc закрыть · tab разделы · 1/2/3 выбор · ↑↓ pgup/pgdn home/end прокрутка";

const TAB_GAP = "  ";

/** Rounded thin border vocabulary; only the terminal default background shows through. */
const BORDER = { tl: "╭", tr: "╮", bl: "╰", br: "╯", h: "─", v: "│" } as const;

/** Busy frames advance only while the agent streams; every other state is static. */
const BUSY_FRAMES = ["◐", "◓", "◑", "◒"] as const;
const IDLE_MARK = "·";
const QUEUED_MARK = "◦";
const WAITING_MARK = "◌";

/**
 * Display cap for the permanent panel's preview. Wrapping a multi-megabyte
 * original would allocate thousands of rows on every width change, so the
 * panel sanitizes the text, caps it for display only, and marks the cut with a
 * visible ellipsis. The cap never reaches the clipboard or the pin: those keep
 * the untouched original, exactly as the viewer does.
 */
const PREVIEW_LIMIT = 2000;

/** One column of right inset keeps the card off the pane edge inside a split. */
const PANEL_RIGHT_INSET = 1;

/** The permanent card is a card, not a viewer: it never grows past this. */
const PANEL_MAX_ROWS = 9;

const EMPTY_ROWS: readonly string[] = [];

/**
 * The card's complete styling vocabulary: intensity and two indexed colours,
 * always on the terminal default foreground. `paint` is the single place any
 * SGR byte is emitted, which is what keeps truecolor, background fills, and
 * palette copies out of the card.
 */
const SGR = {
	bold: "1",
	dim: "2",
	accent: "36",
	accentStrong: "1;36",
	danger: "31",
} as const;

function paint(code: (typeof SGR)[keyof typeof SGR], text: string): string {
	return `\x1b[${code}m${text}\x1b[0m`;
}

/** One physical row: whitespace runs collapse into single spaces. */
function collapseLine(text: string): string {
	return text.replace(/\s+/g, " ").trim();
}

/** Clip a row to the card width and blank the cells it does not cover. */
function fit(line: string, width: number): string {
	const clipped = truncateToWidth(line, width);
	const rest = width - visibleWidth(clipped);
	return rest > 0 ? `${clipped}${padding(rest)}` : clipped;
}

/** One bordered content row: interior padding on both sides, body fitted inside. */
function frameRow(outerWidth: number, pad: number, inner: string): string {
	const contentWidth = Math.max(0, outerWidth - 2 - pad * 2);
	const body = fit(inner, contentWidth);
	const inset = pad === 1 ? " " : "";
	return fit(`${BORDER.v}${inset}${body}${inset}${BORDER.v}`, outerWidth);
}

/** Top border with the title embedded between a leading dash and a trailing gap. */
function borderTop(outerWidth: number, title: string): string {
	if (outerWidth <= 0) return "";
	if (outerWidth === 1) return BORDER.tl;
	const inner = outerWidth - 2;
	const lead = `${BORDER.h} `;
	const leadWidth = visibleWidth(lead);
	const trailWidth = 1;
	const avail = inner - leadWidth - trailWidth;
	if (avail <= 0) return fit(`${BORDER.tl}${BORDER.h.repeat(inner)}${BORDER.tr}`, outerWidth);
	const shown = truncateToWidth(title, avail);
	const used = visibleWidth(shown);
	const dashes = Math.max(0, inner - leadWidth - used - trailWidth);
	return fit(`${BORDER.tl}${lead}${shown} ${BORDER.h.repeat(dashes)}${BORDER.tr}`, outerWidth);
}

/** Plain bottom border. */
function borderBottom(outerWidth: number): string {
	if (outerWidth <= 0) return "";
	if (outerWidth === 1) return BORDER.bl;
	return fit(`${BORDER.bl}${BORDER.h.repeat(Math.max(0, outerWidth - 2))}${BORDER.br}`, outerWidth);
}

/** One keyboard-affordance capsule: the key is accented, the label stays plain. */
function capsule(key: string, label: string): string {
	return `${paint(SGR.accentStrong, `[${key}]`)} ${label}`;
}

/** The image count as a fact about the prompt — never a claim it was painted. */
function imageNote(count: number): string {
	const images = Number.isFinite(count) ? Math.max(0, Math.trunc(count)) : 0;
	if (images === 0) return "";
	return `${images} изобр. · не показано`;
}

/** Local `HH:MM:SS`, or empty when the record carries no usable timestamp. */
function formatTime(timestamp: number): string {
	if (!Number.isFinite(timestamp) || timestamp <= 0) return "";
	const date = new Date(timestamp);
	if (Number.isNaN(date.getTime())) return "";
	const pad = (value: number) => String(value).padStart(2, "0");
	return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/**
 * The live state of the card: a mark that animates only while busy, plus its
 * word. An approval request arrives while the agent is still busy, so waiting
 * must win over busy — otherwise the promised static approval state is
 * unreachable and the circle keeps turning behind a request for input. Queued
 * input is appended to whatever the state already is, so it is never hidden.
 */
function stateMark(snapshot: CardSnapshot): { glyph: string; label: string } {
	let glyph: string;
	let base: string;
	if (snapshot.waiting) {
		glyph = paint(SGR.dim, WAITING_MARK);
		base = "ожидает подтверждения";
	} else if (snapshot.busy) {
		const frame = Number.isFinite(snapshot.frame)
			? Math.abs(Math.trunc(snapshot.frame)) % BUSY_FRAMES.length
			: 0;
		glyph = paint(SGR.accent, BUSY_FRAMES[frame] ?? BUSY_FRAMES[0]);
		base = "работает";
	} else if (snapshot.pending) {
		glyph = paint(SGR.dim, QUEUED_MARK);
		base = "в очереди";
	} else {
		glyph = paint(SGR.dim, IDLE_MARK);
		base = "";
	}
	const label =
		snapshot.pending && base !== "в очереди" ? (base === "" ? "в очереди" : `${base} · в очереди`) : base;
	return { glyph, label };
}

/** A readable single line for a failure reason, safe to place on the grid. */
function errorText(error: unknown): string {
	const raw = error instanceof Error ? error.message : String(error);
	const flat = collapseLine(sanitizeText(raw));
	return flat === "" ? "неизвестная ошибка" : flat;
}

/**
 * Terminal rows the permanent panel occupies on a terminal `rows` high: a
 * third of the pane, clamped to one row minimum for a degenerate pane and to
 * {@link PANEL_MAX_ROWS} so the card stays a card on a tall terminal. Pure and
 * allocation-free: the integration's `getRows` calls it once per render.
 */
function panelHeight(rows: number): number {
	const safe = Number.isFinite(rows) ? Math.max(1, Math.trunc(rows)) : 1;
	return Math.min(PANEL_MAX_ROWS, Math.max(1, Math.floor(safe / 3)));
}

/**
 * Finished body rows for one (width, capacity, source) combination. The cached
 * value is already clamped to the row budget, so a progress frame returns it
 * unchanged instead of re-slicing the wrapped preview.
 */
interface PanelBodyCache {
	readonly width: number;
	readonly rows: number;
	/** Identity of the original text: an unchanged reference reuses `lines`. */
	readonly text: string | undefined;
	readonly images: number;
	readonly lines: readonly string[];
}

/**
 * Permanent prompt card above the composer.
 *
 * It renders a bordered panel on every frame — no command opens it — and
 * defines no `handleInput`, so the editor keeps the keyboard and the card can
 * never take focus, draw a focus ring, or grab a key. The card shows the last
 * submitted request (so a newer queued prompt is not hidden by an older
 * accepted one), a supplementary `Цель` row for the pin or the native goal, and
 * the real path to the viewer's copy/pin keys. Geometry follows the actual
 * render width, so the card stays inside a Herdr split, and its height follows
 * the terminal rows. The mark animates only while the agent is busy (the
 * integration advances `frame` then); idle, queued, and waiting states are
 * static.
 */
export class PromptCardPanel implements Component {
	readonly #getSnapshot: () => CardSnapshot;
	readonly #getRows: () => number;
	#body: PanelBodyCache | undefined;
	#goalSource: string | undefined;
	#goalText = "";

	constructor(getSnapshot: () => CardSnapshot, getRows: () => number) {
		this.#getSnapshot = getSnapshot;
		this.#getRows = getRows;
	}

	render(width: number): readonly string[] {
		const available = Number.isFinite(width) ? Math.max(0, Math.trunc(width)) : 0;
		if (available === 0) return EMPTY_ROWS;
		const snapshot = this.#getSnapshot();
		// Width comes from the actual render call, not the physical terminal, so
		// the card right-aligns inside a Herdr split: preferred 76 columns, one
		// column of inset on the right, the rest is the left inset.
		const cardWidth = Math.max(1, Math.min(PROMPT_CARD_WIDTH, available - PANEL_RIGHT_INSET));
		const leftInset = Math.max(0, available - cardWidth - PANEL_RIGHT_INSET);
		const lead = padding(leftInset);
		const innerInset = cardWidth >= 6 ? 1 : 0;
		const contentWidth = Math.max(0, cardWidth - 2 - innerInset * 2);
		const total = panelHeight(this.#getRows());

		const rows: string[] = [`${lead}${borderTop(cardWidth, this.#titleSegment(snapshot))}`];
		if (total >= 2) {
			if (total > 2) {
				// Chrome is budgeted before the body: the borders come first, then
				// the optional goal and footer rows claim a row only while a body
				// row remains, so the preview is never dropped by them.
				const content = total - 2;
				let remaining = content;
				const hasGoal = snapshot.model.pin !== undefined || snapshot.model.goal !== undefined;
				const showGoal = hasGoal && remaining >= 2;
				if (showGoal) remaining -= 1;
				const showFooter = remaining >= 2;
				if (showFooter) remaining -= 1;
				const bodyRows = Math.max(1, remaining);
				for (const line of this.#bodyLines(snapshot, contentWidth, bodyRows)) {
					rows.push(`${lead}${frameRow(cardWidth, innerInset, line)}`);
				}
				if (showGoal) {
					const goal = this.#goalRow(snapshot, contentWidth);
					if (goal !== undefined) rows.push(`${lead}${frameRow(cardWidth, innerInset, goal)}`);
				}
				if (showFooter) rows.push(`${lead}${frameRow(cardWidth, innerInset, this.#footerRow(contentWidth))}`);
			}
			rows.push(`${lead}${borderBottom(cardWidth)}`);
		}
		return rows;
	}

	invalidate(): void {
		this.#body = undefined;
		this.#goalSource = undefined;
		this.#goalText = "";
	}

	/** Title embedded in the top border: the card's name and the live state. */
	#titleSegment(snapshot: CardSnapshot): string {
		const { glyph, label } = stateMark(snapshot);
		let line = `${glyph} ${paint(SGR.bold, "Последний запрос")}`;
		if (label !== "") line += `${paint(SGR.dim, " · ")}${paint(SGR.dim, label)}`;
		return line;
	}

	/**
	 * The supplementary goal row: the local pin when one exists, otherwise the
	 * native goal-mode objective (marked `пауза` while paused). It never
	 * replaces the preview — the last request keeps its own rows above it.
	 */
	#goalRow(snapshot: CardSnapshot, width: number): string | undefined {
		const pin = snapshot.model.pin;
		if (pin !== undefined) return this.#goalLine(this.#flatCapped(pin), "", width);
		const goal = snapshot.model.goal;
		if (goal === undefined) return undefined;
		const paused = goal.paused ? `${paint(SGR.dim, " · ")}${paint(SGR.dim, "пауза")}` : "";
		return this.#goalLine(this.#flatCapped(goal.text), paused, width);
	}

	#goalLine(text: string, suffix: string, width: number): string {
		const shown = text === "" ? paint(SGR.dim, "(пустая цель)") : text;
		let line = `${paint(SGR.bold, "Цель")}${paint(SGR.dim, ": ")}${shown}${suffix}`;
		if (visibleWidth(line) > width) {
			line = `${truncateToWidth(line, Math.max(0, width - 1))}${paint(SGR.dim, "…")}`;
		}
		return line;
	}

	/**
	 * The real route to the viewer's actions. The keys named here are handled by
	 * {@link PromptCardViewer} while it owns the focus; the permanent card
	 * itself defines no input, so on a narrow pane the row degrades to the
	 * compact opener instead of promising keys it cannot receive.
	 */
	#footerRow(width: number): string {
		const full = `${paint(SGR.dim, "Ctrl+Alt+P")} ${paint(SGR.dim, "→")} ${capsule(
			"c",
			"Копировать",
		)}${paint(SGR.dim, TAB_GAP)}${capsule("p", "Закрепить")}`;
		if (visibleWidth(full) <= width) return full;
		return paint(SGR.dim, "Ctrl+Alt+P /prompt · действия");
	}

	/**
	 * Line, collapsed, sanitized, and capped for display only. The flat result
	 * is cached against the source string's identity, so a pinned multi-kilobyte
	 * prompt is not re-sanitized on every heartbeat frame.
	 */
	#flatCapped(source: string): string {
		if (source !== this.#goalSource) {
			this.#goalSource = source;
			const flat = collapseLine(sanitizeText(source));
			this.#goalText = flat.length > PREVIEW_LIMIT ? `${flat.slice(0, PREVIEW_LIMIT)}…` : flat;
		}
		return this.#goalText;
	}

	/**
	 * Body rows for the current budget: the last submitted request (falling back
	 * to the accepted one when nothing was submitted on this branch), multi-line
	 * preserved, always exactly `rows` rows tall. The wrap, the display cap, the
	 * row clamp, and the truncation ellipsis are all cached against the original
	 * string's identity, the content width, and the row budget, so progress
	 * frames return the same rows and never re-wrap a large prompt.
	 */
	#bodyLines(snapshot: CardSnapshot, width: number, rows: number): readonly string[] {
		const record = snapshot.model.submitted ?? snapshot.model.responding;
		const text = record?.text;
		const images = record?.images ?? 0;
		const cached = this.#body;
		if (
			cached !== undefined &&
			cached.width === width &&
			cached.rows === rows &&
			cached.text === text &&
			cached.images === images
		) {
			return cached.lines;
		}
		let wrapped: readonly string[];
		if (record === undefined) {
			wrapped = [paint(SGR.dim, "(нет запроса)")];
		} else {
			const sanitized = sanitizeText(record.text);
			if (sanitized.trim() === "") {
				const note = imageNote(record.images);
				wrapped = [paint(SGR.dim, note === "" ? "(пустой запрос)" : `(${note})`)];
			} else {
				const capped = sanitized.length > PREVIEW_LIMIT ? `${sanitized.slice(0, PREVIEW_LIMIT)}…` : sanitized;
				const lines = wrapTextWithAnsi(replaceTabs(capped), Math.max(1, width));
				wrapped = lines.length === 0 ? [paint(SGR.dim, "(пустой запрос)")] : lines;
			}
		}
		const lines = this.#fitRows(wrapped, width, rows);
		this.#body = { width, rows, text, images, lines };
		return lines;
	}

	/** Exactly `rows` rows: overflow ends in an ellipsis, shortfall pads blank. */
	#fitRows(wrapped: readonly string[], width: number, rows: number): string[] {
		const shown: string[] = [];
		const visible = Math.min(wrapped.length, rows);
		for (let index = 0; index < visible; index += 1) {
			const line = wrapped[index] ?? "";
			shown.push(
				index === rows - 1 && wrapped.length > rows
					? `${truncateToWidth(line, Math.max(0, width - 1))}${paint(SGR.dim, "…")}`
					: line,
			);
		}
		while (shown.length < rows) shown.push("");
		return shown;
	}
}

type StatusKind = "info" | "error";

interface ViewerStatus {
	readonly text: string;
	readonly kind: StatusKind;
}

/** Wrapped rows for one (width, viewport, section, source) combination. */
interface ContentCache {
	readonly width: number;
	readonly capacity: number;
	readonly section: CardSection;
	/** Identity of the original: an unchanged reference reuses `lines`. */
	readonly source: string | undefined;
	readonly lines: readonly string[];
}

/**
 * Read-only card overlay.
 *
 * The viewer owns selection, scrolling, and the copy/pin gestures; the
 * integration owns the model, the clipboard, and the lifecycle. Input is
 * matched against exactly the documented keys and nothing else is done with
 * it, so no keystroke can edit or replay a prompt.
 */
export class PromptCardViewer implements Component {
	readonly #getSnapshot: () => CardSnapshot;
	readonly #getRows: () => number;
	readonly #requestRender: () => void;
	readonly #actions: CardActions;
	readonly #scroll: ScrollView;

	#section: CardSection = "submitted";
	#status: ViewerStatus | undefined;
	#content: ContentCache | undefined;
	#disposed = false;

	constructor(
		getSnapshot: () => CardSnapshot,
		getRows: () => number,
		requestRender: () => void,
		actions: CardActions,
	) {
		this.#getSnapshot = getSnapshot;
		this.#getRows = getRows;
		this.#requestRender = requestRender;
		this.#actions = actions;
		this.#scroll = new ScrollView(EMPTY_ROWS, {
			height: 0,
			theme: { track: text => paint(SGR.dim, text), thumb: text => paint(SGR.accent, text) },
		});
	}

	render(width: number): readonly string[] {
		if (this.#disposed) return EMPTY_ROWS;
		const snapshot = this.#getSnapshot();
		const outerWidth = Number.isFinite(width) ? Math.max(0, Math.trunc(width)) : 0;
		const total = this.#terminalRows();
		if (total <= 1) return [borderTop(outerWidth, this.#titleSegment(snapshot))];

		// Budget every chrome row before the body gets a row: tabs, divider,
		// actions, and help are all optional, so tiny panes drop them from the
		// edges in while the body stays visible and scrollable.
		const showTabs = total >= 4;
		const showActions = total >= 5;
		const showDivider = total >= 6;
		const showHelp = total >= 7;
		const chrome =
			2 + (showTabs ? 1 : 0) + (showActions ? 1 : 0) + (showDivider ? 1 : 0) + (showHelp ? 1 : 0);
		const bodyRows = Math.max(0, total - chrome);

		const inset = outerWidth >= 6 ? 1 : 0;
		const contentWidth = Math.max(0, outerWidth - 2 - inset * 2);

		const rows: string[] = [borderTop(outerWidth, this.#titleSegment(snapshot))];
		if (showTabs) rows.push(frameRow(outerWidth, inset, this.#tabRow(snapshot)));
		if (showDivider) rows.push(frameRow(outerWidth, inset, paint(SGR.dim, BORDER.h.repeat(contentWidth))));

		if (bodyRows > 0) {
			this.#scroll.setHeight(bodyRows);
			// Progress frames never reach this cache, so a busy card does not
			// re-wrap a huge prompt on every tick.
			this.#contentLines(contentWidth, bodyRows, sectionText(snapshot, this.#section));
			for (const line of this.#scroll.render(contentWidth)) rows.push(frameRow(outerWidth, inset, line));
		} else {
			this.#scroll.setHeight(0);
		}

		if (showActions) rows.push(frameRow(outerWidth, inset, this.#actionRow(snapshot)));
		if (showHelp) rows.push(frameRow(outerWidth, inset, this.#helpRow()));
		rows.push(borderBottom(outerWidth));

		// The budget above already produces exactly `total` rows.
		return rows;
	}

	invalidate(): void {
		this.#content = undefined;
		this.#scroll.invalidate();
	}

	handleInput(data: string): void {
		if (this.#disposed) return;
		if (matchesKey(data, Key.escape)) {
			this.#actions.close();
			return;
		}
		if (matchesKey(data, Key.tab)) {
			this.#cycleSection(1);
			return;
		}
		if (matchesKey(data, Key.shift("tab"))) {
			this.#cycleSection(-1);
			return;
		}
		if (matchesKey(data, "1")) {
			this.#select("submitted");
			return;
		}
		if (matchesKey(data, "2")) {
			this.#select("responding");
			return;
		}
		if (matchesKey(data, "3")) {
			this.#select("objective");
			return;
		}
		// The viewport matches its own navigation keys: arrows, paging, home/end.
		if (this.#scroll.handleScrollKey(data)) return;
		if (matchesKey(data, "c")) {
			this.#copy();
			return;
		}
		if (matchesKey(data, "p")) {
			this.#pin();
			return;
		}
		if (matchesKey(data, "u")) {
			this.#unpin();
			return;
		}
		// Every other key is ignored: the viewer never edits or replays a prompt.
	}

	dispose(): void {
		if (this.#disposed) return;
		this.#disposed = true;
		this.#content = undefined;
		this.#status = undefined;
		this.#scroll.dispose();
	}

	#terminalRows(): number {
		const rows = this.#getRows();
		return Number.isFinite(rows) ? Math.max(1, Math.trunc(rows)) : 1;
	}

	#cycleSection(delta: number): void {
		const index = SECTIONS.indexOf(this.#section);
		const next = SECTIONS[(index + delta + SECTIONS.length) % SECTIONS.length] ?? this.#section;
		this.#select(next);
	}

	#select(section: CardSection): void {
		if (section === this.#section) return;
		this.#section = section;
		// The pending message described the section the user just left.
		this.#status = undefined;
		this.#scroll.setScrollOffset(0);
		this.#requestRender();
	}

	/** Never draws a closed card: an in-flight clipboard result stays silent. */
	#setStatus(text: string, kind: StatusKind): void {
		if (this.#disposed) return;
		this.#status = { text, kind };
		this.#requestRender();
	}

	#copy(): void {
		// `sectionText` yields only real content: blank selections are undefined.
		const original = sectionText(this.#getSnapshot(), this.#section);
		if (original === undefined) {
			this.#setStatus("в этом разделе нечего копировать", "error");
			return;
		}
		let copied: Promise<void>;
		try {
			copied = Promise.resolve(this.#actions.copy(original));
		} catch (error) {
			this.#setStatus(`не удалось скопировать: ${errorText(error)}`, "error");
			return;
		}
		// Both arms are attached here, so a clipboard rejection is reported and
		// never becomes an unhandled promise.
		copied.then(
			() => this.#setStatus("скопировано в буфер обмена", "info"),
			(error: unknown) => this.#setStatus(`не удалось скопировать: ${errorText(error)}`, "error"),
		);
	}

	#pin(): void {
		if (this.#section === "objective") {
			this.#setStatus("в разделе «Цель» нет запроса для закрепа", "error");
			return;
		}
		const original = sectionText(this.#getSnapshot(), this.#section);
		if (original === undefined) {
			this.#setStatus("в этом разделе нечего закреплять", "error");
			return;
		}
		try {
			this.#actions.pin(original);
		} catch (error) {
			this.#setStatus(`не удалось закрепить: ${errorText(error)}`, "error");
			return;
		}
		this.#setStatus("закреплено как локальная цель", "info");
	}

	#unpin(): void {
		if (this.#getSnapshot().model.pin === undefined) {
			this.#setStatus("нет закрепа для снятия", "error");
			return;
		}
		try {
			this.#actions.unpin();
		} catch (error) {
			this.#setStatus(`не удалось снять закреп: ${errorText(error)}`, "error");
			return;
		}
		this.#setStatus("закреп снят", "info");
	}

	/** Title embedded in the top border: live state, selected section, and meta. */
	#titleSegment(snapshot: CardSnapshot): string {
		const { glyph, label: state } = stateMark(snapshot);
		let line = `${glyph} ${paint(SGR.bold, "Карточка")}${paint(SGR.dim, " · ")}${paint(
			SGR.accentStrong,
			sectionTitle(this.#section, snapshot),
		)}`;
		if (state !== "") line += `${paint(SGR.dim, " · ")}${paint(SGR.dim, state)}`;
		const meta = this.#sectionMeta(snapshot);
		if (meta !== "") line += `${paint(SGR.dim, " · ")}${paint(SGR.dim, meta)}`;
		return line;
	}

	#tabRow(snapshot: CardSnapshot): string {
		const tabs = SECTIONS.map((section, index) => {
			const label = `${index + 1} ${sectionTitle(section, snapshot)}`;
			return section === this.#section ? paint(SGR.accentStrong, label) : paint(SGR.dim, label);
		});
		return tabs.join(TAB_GAP);
	}

	/**
	 * Key-action capsules. Each one names a key the viewer already handles, so
	 * the row is an affordance rather than a fake button; pin is hidden on the
	 * objective tab (which cannot be pinned) and unpin only appears when there
	 * is a pin to clear.
	 */
	#actionRow(snapshot: CardSnapshot): string {
		const hasText = sectionText(snapshot, this.#section) !== undefined;
		const parts: string[] = [];
		if (hasText) parts.push(capsule("c", "Копировать"));
		if (hasText && this.#section !== "objective") parts.push(capsule("p", "Закрепить цель"));
		if (snapshot.model.pin !== undefined) parts.push(capsule("u", "Снять закреп"));
		if (parts.length === 0) return paint(SGR.dim, "(нет действий)");
		return parts.join(paint(SGR.dim, TAB_GAP));
	}

	#helpRow(): string {
		const status = this.#status;
		if (status === undefined) return paint(SGR.dim, HELP);
		const text = collapseLine(sanitizeText(status.text));
		return `▸ ${paint(status.kind === "error" ? SGR.danger : SGR.accent, text)}`;
	}

	/** What the section is besides its text: origin, time, and attachment count. */
	#sectionMeta(snapshot: CardSnapshot): string {
		const model = snapshot.model;
		if (this.#section === "objective") {
			if (model.pin !== undefined) return "локальный закреп";
			const goal = model.goal;
			if (goal === undefined) return "";
			return goal.paused ? "режим цели · пауза" : "режим цели";
		}
		const record = this.#section === "submitted" ? model.submitted : model.responding;
		if (record === undefined) return "";
		const parts: string[] = [];
		const time = formatTime(record.timestamp);
		if (time !== "") parts.push(time);
		const images = imageNote(record.images);
		if (images !== "") parts.push(images);
		return parts.join(" · ");
	}

	/**
	 * Wrap the selected text for the current surface, reusing the previous
	 * result while the width, the viewport, the section, and the original
	 * string are unchanged. Progress frames never reach this cache, so a busy
	 * card does not re-wrap a huge prompt on every tick.
	 */
	#contentLines(width: number, capacity: number, source: string | undefined): readonly string[] {
		const cached = this.#content;
		if (
			cached !== undefined &&
			cached.width === width &&
			cached.capacity === capacity &&
			cached.section === this.#section &&
			cached.source === source
		) {
			return cached.lines;
		}
		const display = this.#displayText(source);
		// Reserve the scrollbar column first: the wider wrap is used only when
		// it still fits the viewport, which is exactly when ScrollView hides the
		// bar. Wrapped rows then always match the width the viewport uses.
		const narrow = wrapTextWithAnsi(replaceTabs(display), Math.max(1, width - 1));
		const lines = narrow.length > capacity ? narrow : wrapTextWithAnsi(replaceTabs(display), Math.max(1, width));
		this.#content = { width, capacity, section: this.#section, source, lines };
		this.#scroll.setLines(lines);
		return lines;
	}

	/** Display text for a section; a missing or blank original shows a placeholder. */
	#displayText(source: string | undefined): string {
		const sanitized = source === undefined ? "" : sanitizeText(source);
		return sanitized.trim() === "" ? PLACEHOLDERS[this.#section] : sanitized;
	}
}
