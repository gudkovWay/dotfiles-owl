/**
 * OMP status-line path segment override.
 *
 * Заменяет SEGMENTS.path из @oh-my-pi/pi-tui на компактный вариант: обычная
 * сессия показывает только basename каталога запуска, а единственный Git-маркер
 * (короткое имя выбранного worktree) добавляется к нему отдельной ссылкой.
 * Иконка в начале зависит от того, в каком корне лежит физический каталог
 * запуска. Ничего из node_modules не патчится — подмена и восстановление идут
 * через экспортируемый SEGMENTS и только на главном TUI-binding'е.
 *
 * Дополнительно сегмент показывает рабочий worktree, реально выбранный агентом
 * (`wt switch ... --format json`), независимо от cwd процесса OMP: компактная
 * basename-подпись с git-иконкой темы и отдельной гиперссылкой на выбранный
 * каталог. Выбор живёт в custom-записи сессии и восстанавливается из активной
 * ветки, включая сессии, созданные до появления этой правки. Коллизии подписей
 * разводятся по каталогу worktree того же репозитория.
 *
 * Дорогие вещи вынесены из рендера: шесть именованных корней канонизируются
 * один раз при загрузке модуля, физический путь/подпись/категория пересчитываются
 * только при смене каталога проекта (кэш на одну запись), а выбор worktree —
 * только в lifecycle-событиях и обработке результатов инструментов. Рендер лишь
 * читает закэшированную подпись и текущую тему.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";
import { SEGMENTS } from "@oh-my-pi/pi-tui/status-line";
import type { SegmentView, StatusLineSegment } from "@oh-my-pi/pi-tui/status-line/types";
import { theme } from "@oh-my-pi/pi-tui/theme";
import { fileHyperlink } from "@oh-my-pi/pi-tui/render/hyperlink";
import { sanitizeStatusText } from "@oh-my-pi/pi-tui/chrome/shared";
import { getProjectDir } from "@oh-my-pi/pi-utils";
import type { ExtensionAPI, ExtensionContext, SessionEntry, ToolResultEvent } from "@oh-my-pi/pi-coding-agent";

/** Nerd Font кодопункты для категорий, у которых нет семантической иконки в теме. */
const ICON_STORAGE = "\uF1C0"; // nf-fa-database
const ICON_DEV = "\uE796"; // nf-dev-code
const ICON_CONFIG = "\uF013"; // nf-fa-gear
const ICON_LOCAL = "\uF015"; // nf-fa-home

/** Категория корня каталога запуска. */
type RootCategory = "storage" | "dev" | "config" | "local" | "omp" | "tmp" | "other";

/** realpath с откатом на resolve, если каталог ещё не существует. */
function canonicalPath(dir: string): string {
	try {
		return fs.realpathSync.native(dir);
	} catch {
		return path.resolve(dir);
	}
}

/** Именованные корни каталога запуска вместе с их категориями. */
const ROOTS: readonly (readonly [RootCategory, string])[] = [
	["storage", path.join(os.homedir(), "storage")],
	["dev", path.join(os.homedir(), "dev")],
	["config", path.join(os.homedir(), ".config")],
	["local", path.join(os.homedir(), ".local")],
	["omp", path.join(os.homedir(), ".omp")],
	["tmp", os.tmpdir()],
];

/**
 * Те же корни, канонизированные один раз при загрузке модуля: рендер не должен
 * трогать ФС и строить пути.
 */
const CANONICAL_ROOTS: readonly (readonly [RootCategory, string])[] = ROOTS.map(
	([category, root]) => [category, canonicalPath(root)] as const,
);

function withIcon(icon: string, text: string): string {
	return icon ? `${icon} ${text}` : text;
}

/**
 * Категория физического каталога по каноническим корням; вне корней — other.
 * Граница по разделителю: /foo/bar не матчит /foo/baz (оба пути канонические).
 */
function classifyRoot(realDir: string): RootCategory {
	for (const [category, root] of CANONICAL_ROOTS) {
		if (!root) continue;
		const prefix = root.endsWith(path.sep) ? root : root + path.sep;
		if (realDir === root || realDir.startsWith(prefix)) return category;
	}
	return "other";
}

/**
 * Private Use Area: BMP U+E000–U+F8FF и supplementary-плоскости 15/16
 * (U+F0000–U+FFFFD и U+100000–U+10FFFD) — там живут Nerd Font глифы.
 */
function isPrivateUse(codePoint: number): boolean {
	return (
		(codePoint >= 0xe000 && codePoint <= 0xf8ff) ||
		(codePoint >= 0xf0000 && codePoint <= 0xffffd) ||
		(codePoint >= 0x100000 && codePoint <= 0x10fffd)
	);
}

/** Есть ли в строке хотя бы один PUA-кодопункт (BMP или supplementary). */
function hasPrivateUse(text: string | undefined): boolean {
	if (!text) return false;
	for (const char of text) {
		const codePoint = char.codePointAt(0);
		if (codePoint !== undefined && isPrivateUse(codePoint)) return true;
	}
	return false;
}

/** Иконка категории: PUA-литералы только на Nerd-capable теме, иначе иконки темы. */
function categoryIcon(category: RootCategory): string {
	// Nerd-capable определяется по иконкам активной темы на каждом рендере: смена
	// темы или preset видна сразу, а не-PUA preset не получает PUA-литералов.
	const nerd =
		hasPrivateUse(theme.icon.omp) || hasPrivateUse(theme.icon.folder) || hasPrivateUse(theme.icon.worktree);
	switch (category) {
		case "storage":
			return nerd ? ICON_STORAGE : theme.icon.cache;
		case "dev":
			return nerd ? ICON_DEV : theme.icon.file;
		case "config":
			return nerd ? ICON_CONFIG : theme.cmd.settings || theme.icon.folder;
		case "local":
			return nerd ? ICON_LOCAL : theme.icon.package;
		case "omp":
			return theme.icon.omp || theme.icon.folder;
		case "tmp":
			return theme.icon.scratchFolder;
		default:
			return theme.icon.folder;
	}
}

/** Basename каталога; для корня ФС вербальная заглушка не нужна — возвращаем сам корень. */
function dirLabel(dir: string): string {
	const parsed = path.parse(dir);
	if (parsed.root === dir) return dir;
	return path.basename(dir) || dir;
}

interface ProjectMeta {
	/** Логический каталог, для которого построена запись кэша. */
	dir: string;
	/** Канонический физический путь: гиперссылка и категория корня. */
	realDir: string;
	/** Закэшированная ссылка для native-описания сегмента. */
	href: string;
	/** Санированная подпись обычной (не worktree) сессии. */
	label: string;
	/** Категория корня для realDir. */
	category: RootCategory;
}

let cachedMeta: ProjectMeta | undefined;

/**
 * Кэш на одну запись: пока getProjectDir() не сменился, ни realpath, ни
 * разбор корней, ни санирование подписи не повторяются.
 */
function projectMeta(dir: string): ProjectMeta {
	if (cachedMeta?.dir === dir) return cachedMeta;
	const realDir = canonicalPath(dir);
	cachedMeta = {
		dir,
		realDir,
		href: pathToFileURL(realDir).href,
		label: sanitizeStatusText(dirLabel(dir)),
		category: classifyRoot(realDir),
	};
	return cachedMeta;
}

// ============================================================================
// Рабочий worktree, выбранный агентом
// ============================================================================

/** Уникальное имя custom-записи сессии для выбранного рабочего worktree. */
const WT_ENTRY_TYPE = "statusline-working-worktree";
/** Версия payload: меняется вместе с его формой. */
const WT_ENTRY_VERSION = 1;
/** Custom-запись OMP с аргументами уже стартовавшего вызова инструмента. */
const TOOL_START_ENTRY_TYPE = "tool_execution_start";
/** Успешные действия Worktrunk `wt switch`; всё прочее — не выбор worktree. */
const WT_SWITCH_ACTIONS: Record<string, true> = {
	created: true,
	switched: true,
	existing: true,
	already_at: true,
};
/** Владельческие префиксы, которые снимаются вместе с DEV- в короткой подписи. */
const OWNER_PREFIXES = ["capitalism-slave-", "yeqwer-"] as const;
/** Таймаут единственного git-запроса вне рендера. */
const GIT_TIMEOUT_MS = 5000;

/** Сохранённый в сессии выбор: полный путь или явная очистка. */
interface PersistedSelection {
	v: number;
	path: string | null;
}

/** Готовые к рендеру подпись и цель гиперссылки выбранного worktree. */
interface WtDisplay {
	label: string;
	hyperlink: string;
	href: string;
}

/** Корень worktree репозитория из каталога git. */
interface WorktreeRoot {
	/** Канонический корень worktree. */
	root: string;
	/** Главный checkout репозитория (не linked worktree). */
	main: boolean;
}

/** Минимальная структурная форма части контента инструмента. */
interface ContentPartLike {
	type?: unknown;
	text?: unknown;
}

/**
 * Изменяемое состояние одного binding'а расширения. Живёт в замыкании фабрики:
 * OMP переиспользует модуль для корня и дочерних сессий, поэтому модульная
 * переменная означала бы общий — и перезаписываемый сабагентом — сегмент.
 */
interface WtState {
	/** Подпись и гиперссылка выбранного рабочего worktree; undefined — маркера нет. */
	display: WtDisplay | undefined;
	/** Поколение async-обновлений: устаревший ответ не перезапишет новый выбор. */
	generation: number;
	/** Идентичность сессии, к которой относится текущий async-запрос. */
	sessionId: string | undefined;
	/** Последний записанный в сессию выбор — защита от дублирующих appendEntry. */
	lastPersisted: string | null | undefined;
	/** Текущее состояние выведено из явного `wt switch`, а не из cwd-фолбэка. */
	explicit: boolean;
	/** Последний наблюдённый cwd сессии: смена пересобирает фолбэк без ФС в рендере. */
	observedCwd: string | undefined;
	/** Сегмент этого binding'а стоит в глобальном реестре SEGMENTS. */
	installed: boolean;
	/** Сегмент, лежавший в SEGMENTS.path до установки: восстановление только своего binding'а. */
	previous: StatusLineSegment | undefined;
}

/**
 * Разбор `git worktree list --porcelain -z`: поля разделены NUL, записи — пустым
 * полем. Main-корень отличается тем, что `.git` у него каталог, а у linked — файл.
 * Запись без актуального `.git` (prunable/удалённый каталог) не существует и в
 * каталог не попадает: она не может ни стать main, ни быть выбранной.
 */
function parseWorktreeList(stdout: string): WorktreeRoot[] {
	const roots: WorktreeRoot[] = [];
	let current: string | undefined;
	let bare = false;
	const flush = () => {
		if (current === undefined) return;
		const root = canonicalPath(current);
		if (bare) {
			roots.push({ root, main: true });
		} else {
			let isDirectory: boolean | undefined;
			try {
				isDirectory = fs.statSync(path.join(root, ".git")).isDirectory();
			} catch {
				isDirectory = undefined;
			}
			if (isDirectory !== undefined) roots.push({ root, main: isDirectory });
		}
		current = undefined;
		bare = false;
	};
	for (const field of stdout.split("\0")) {
		if (field === "") {
			flush();
			continue;
		}
		if (field.startsWith("worktree ")) {
			flush();
			current = field.slice("worktree ".length);
			continue;
		}
		if (current === undefined) continue;
		if (field === "bare") bare = true;
	}
	flush();
	return roots;
}

/** Каталог worktree одного репозитория, прочитанный ровно один раз вне рендера. */
async function readWorktreeCatalog(api: ExtensionAPI, dir: string): Promise<WorktreeRoot[]> {
	try {
		const result = await api.exec("git", ["-C", dir, "worktree", "list", "--porcelain", "-z"], {
			timeout: GIT_TIMEOUT_MS,
		});
		if (result.code !== 0 || !result.stdout) return [];
		return parseWorktreeList(result.stdout);
	} catch {
		return [];
	}
}

/** Снять ровно один известный владельческий префикс. */
function stripOwner(name: string): string {
	for (const owner of OWNER_PREFIXES) {
		if (name.startsWith(owner)) return name.slice(owner.length);
	}
	return name;
}

/** Уровень 1: снять DEV- и известного владельца; пустой результат — исходный basename. */
function shortWorktreeName(name: string): string {
	const withoutDev = name.startsWith("DEV-") ? name.slice("DEV-".length) : name;
	const stripped = stripOwner(withoutDev);
	return stripped || name;
}

/** Уровень 2: снять только DEV- (владелец возвращается); пустой результат — исходный basename. */
function devWorktreeName(name: string): string {
	const stripped = name.startsWith("DEV-") ? name.slice("DEV-".length) : name;
	return stripped || name;
}

/** Общий каталог-предок набора путей. */
function commonAncestor(dirs: readonly string[]): string {
	if (dirs.length === 0) return path.sep;
	let parts = dirs[0].split(path.sep);
	for (const dir of dirs.slice(1)) {
		const other = dir.split(path.sep);
		let i = 0;
		while (i < parts.length && i < other.length && parts[i] === other[i]) i++;
		parts = parts.slice(0, i);
	}
	return parts.join(path.sep) || path.sep;
}

/**
 * Подписи для набора linked worktree одного репозитория. Каждый корень начинает
 * с самого короткого варианта и удлиняется только при коллизии — остальные имена
 * не удлиняются. Если одинаковых basename всё ещё несколько, разводим
 * неабсолютным относительным путём от общего предка.
 */
function assignWorktreeLabels(roots: readonly WorktreeRoot[]): Map<string, string> {
	const names = roots.map(root => path.basename(root.root) || root.root);
	const levels = names.map(() => 0);
	const candidates = [shortWorktreeName, devWorktreeName, (name: string) => name];
	const labelAt = (index: number) => candidates[levels[index]](names[index]) || names[index];

	for (let pass = 0; pass < 4; pass++) {
		const groups = new Map<string, number[]>();
		roots.forEach((_root, index) => {
			const key = labelAt(index);
			const group = groups.get(key);
			if (group) group.push(index);
			else groups.set(key, [index]);
		});
		let changed = false;
		for (const group of groups.values()) {
			if (group.length < 2) continue;
			for (const index of group) {
				if (levels[index] < candidates.length - 1) {
					levels[index]++;
					changed = true;
				}
			}
		}
		if (!changed) break;
	}

	const groups = new Map<string, number[]>();
	roots.forEach((_root, index) => {
		const key = labelAt(index);
		const group = groups.get(key);
		if (group) group.push(index);
		else groups.set(key, [index]);
	});

	const labels = new Map<string, string>();
	for (const group of groups.values()) {
		if (group.length < 2) {
			for (const index of group) labels.set(roots[index].root, labelAt(index));
			continue;
		}
		const common = commonAncestor(group.map(index => path.dirname(roots[index].root)));
		for (const index of group) {
			const relative = path.relative(common, roots[index].root);
			labels.set(roots[index].root, relative || roots[index].root);
		}
	}
	return labels;
}

/**
 * Разбиение командной строки на сегменты по неэкранированным `&&`, `||`, `;`,
 * `|` и переводам строк. Достаточно консервативно: полноценный shell-парсер не
 * нужен и не должен угадывать. Незакавыченный `#` в начале слова открывает
 * комментарий до конца строки: ни разделители, ни текст внутри него сегментами
 * не становятся (`#` внутри слова или в кавычках — литерал).
 */
function shellSegments(command: string): string[] {
	const segments: string[] = [];
	let buffer = "";
	let quote: string | undefined;
	let comment = false;
	// Начало слова: только здесь `#` открывает комментарий.
	let atWordStart = true;
	for (let i = 0; i < command.length; i++) {
		const char = command[i];
		if (comment) {
			if (char !== "\n") continue;
			comment = false;
			segments.push(buffer);
			buffer = "";
			atWordStart = true;
			continue;
		}
		if (quote) {
			buffer += char;
			if (char === "\\" && quote === '"' && i + 1 < command.length) buffer += command[++i];
			else if (char === quote) quote = undefined;
			continue;
		}
		if (char === "'" || char === '"') {
			quote = char;
			buffer += char;
			atWordStart = false;
			continue;
		}
		if (char === "\\") {
			buffer += char;
			if (i + 1 < command.length) buffer += command[++i];
			atWordStart = false;
			continue;
		}
		if (char === "#" && atWordStart) {
			comment = true;
			continue;
		}
		if (char === "\n" || char === "&" || char === "|" || char === ";") {
			segments.push(buffer);
			buffer = "";
			atWordStart = true;
			continue;
		}
		if (char === " " || char === "\t") {
			buffer += char;
			atWordStart = true;
			continue;
		}
		buffer += char;
		atWordStart = false;
	}
	segments.push(buffer);
	return segments;
}

/** Разбор одного сегмента в argv-подобные токены со снятием кавычек. */
function shellTokens(segment: string): string[] {
	const tokens: string[] = [];
	let buffer = "";
	let quote: string | undefined;
	let hasContent = false;
	for (let i = 0; i < segment.length; i++) {
		const char = segment[i];
		if (quote) {
			if (char === quote) {
				quote = undefined;
				continue;
			}
			if (char === "\\" && quote === '"' && i + 1 < segment.length) {
				buffer += segment[++i];
				hasContent = true;
				continue;
			}
			buffer += char;
			hasContent = true;
			continue;
		}
		if (char === "'" || char === '"') {
			quote = char;
			hasContent = true;
			continue;
		}
		if (char === "\\") {
			if (i + 1 < segment.length) {
				buffer += segment[++i];
				hasContent = true;
			}
			continue;
		}
		if (char === " " || char === "\t") {
			if (hasContent) {
				tokens.push(buffer);
				buffer = "";
				hasContent = false;
			}
			continue;
		}
		buffer += char;
		hasContent = true;
	}
	if (hasContent) tokens.push(buffer);
	return tokens;
}

/**
 * Настоящий ли это `wt switch ... --format json`. Только первый токен сегмента
 * может быть wt (абсолютный путь допустим, basename обязан быть `wt`); строки
 * вроде `echo 'wt switch ...'`, комментарии, heredoc-тела, `wt list` и чужой
 * текст с упоминанием wt не считаются выбором.
 */
function isWtSwitchJson(command: string): boolean {
	// Тело heredoc — не исполняемая команда; не пытаемся его разбирать.
	if (command.includes("<<")) return false;
	for (const segment of shellSegments(command)) {
		const tokens = shellTokens(segment);
		if (tokens.length < 2) continue;
		const executable = path.basename(tokens[0]).replace(/\.exe$/i, "");
		if (executable !== "wt" || tokens[1] !== "switch") continue;
		for (let i = 2; i < tokens.length; i++) {
			const token = tokens[i];
			if (token === "--format=json") return true;
			if (token === "--format" && tokens[i + 1] === "json") return true;
		}
	}
	return false;
}

/** Успешные записи переключения из построчного JSON-вывода wt switch. */
function parseSwitchRecords(text: string): string[] {
	const paths: string[] = [];
	for (const line of text.split("\n")) {
		const trimmed = line.trim();
		if (!trimmed.startsWith("{")) continue;
		let value: unknown;
		try {
			value = JSON.parse(trimmed);
		} catch {
			continue;
		}
		if (!value || typeof value !== "object") continue;
		if (!("action" in value) || !("path" in value)) continue;
		const action = value.action;
		const target = value.path;
		if (typeof action !== "string" || WT_SWITCH_ACTIONS[action] !== true) continue;
		if (typeof target !== "string" || !target || !path.isAbsolute(target)) continue;
		paths.push(target);
	}
	return paths;
}

/** Текстовые части контента инструмента, склеенные переводами строк. */
function contentText(content: readonly ContentPartLike[]): string {
	let text = "";
	for (const part of content) {
		if (!part || typeof part !== "object") continue;
		if (part.type === "text" && typeof part.text === "string") text += `${part.text}\n`;
	}
	return text;
}

/**
 * Путь выбранного worktree из результата bash-вызова, если это настоящий
 * `wt switch --format json`. `undefined` — вызов к состоянию не относится.
 */
function candidateFromToolResult(
	command: string,
	content: readonly ContentPartLike[],
	isError: boolean,
): string | undefined {
	if (isError || !isWtSwitchJson(command)) return undefined;
	const paths = parseSwitchRecords(contentText(content));
	if (paths.length === 0) return undefined;
	// Последняя успешная запись в поддерживаемой команде побеждает.
	return paths[paths.length - 1];
}

/** Запомнить команду bash-вызова по его toolCallId, если это bash. */
function rememberBashCommand(commands: Map<string, string>, raw: unknown): void {
	if (!raw || typeof raw !== "object") return;
	if (!("toolName" in raw) || raw.toolName !== "bash") return;
	if (!("toolCallId" in raw) || typeof raw.toolCallId !== "string") return;
	if (!("args" in raw)) return;
	const args = raw.args;
	if (!args || typeof args !== "object" || !("command" in args)) return;
	const command = args.command;
	if (typeof command === "string") commands.set(raw.toolCallId, command);
}

/**
 * Разобрать payload custom-записи: `undefined` — запись чужой/старой версии,
 * `null` — явная очистка, строка — выбранный путь.
 */
function persistedSelection(raw: unknown): string | null | undefined {
	if (!raw || typeof raw !== "object") return undefined;
	if (!("v" in raw) || raw.v !== WT_ENTRY_VERSION) return undefined;
	if (!("path" in raw) || raw.path === null) return null;
	return typeof raw.path === "string" && raw.path ? raw.path : null;
}

/**
 * Последний выбор рабочего worktree в активной ветке сессии: custom-записи этой
 * расшифровки и успешные исторические `wt switch`, в хронологическом порядке —
 * более новая запись перекрывает старую. Сканируется только активная ancestry
 * (getBranch), а не соседние ветки дерева сессии.
 */
function candidateFromBranch(entries: readonly SessionEntry[]): string | null | undefined {
	const commands = new Map<string, string>();
	let candidate: string | null | undefined;
	for (const entry of entries) {
		if (entry.type === "custom") {
			if (entry.customType === WT_ENTRY_TYPE) {
				const selection = persistedSelection(entry.data);
				if (selection !== undefined) candidate = selection;
			} else if (entry.customType === TOOL_START_ENTRY_TYPE) {
				rememberBashCommand(commands, entry.data);
			}
			continue;
		}
		if (entry.type !== "message") continue;
		const message = entry.message;
		if (message.role === "assistant") {
			for (const part of message.content) {
				if (part.type !== "toolCall") continue;
				rememberBashCommand(commands, { toolCallId: part.id, toolName: part.name, args: part.arguments });
			}
		} else if (message.role === "toolResult" && message.toolName === "bash") {
			const command = commands.get(message.toolCallId);
			if (command === undefined) continue;
			const next = candidateFromToolResult(command, message.content, message.isError);
			if (next !== undefined) candidate = next;
		}
	}
	return candidate;
}

/**
 * Превратить кандидата в готовую к рендеру подпись. Валидация идёт по каталогу
 * worktree репозитория: связанный worktree показывается, main checkout и
 * неизвестный/удалённый путь очищают маркер (без воскрешения прошлого выбора).
 * Без явного кандидата берётся linked worktree, содержащий cwd сессии.
 */
async function resolveCandidate(
	api: ExtensionAPI,
	candidate: string | null | undefined,
	cwd: string,
): Promise<WtDisplay | undefined> {
	// Явная очистка: агент переключился на main checkout, маркер снимается.
	if (candidate === null) return undefined;

	const roots = await readWorktreeCatalog(api, typeof candidate === "string" ? candidate : cwd);
	if (roots.length === 0) return undefined;

	let selected: WorktreeRoot | undefined;
	if (typeof candidate === "string") {
		const realTarget = canonicalPath(candidate);
		selected = roots.find(root => root.root === realTarget);
		// Неизвестный или удалённый путь не воскрешает более старый выбор.
		if (!selected || selected.main) return undefined;
	} else {
		const realCwd = canonicalPath(cwd);
		for (const root of roots) {
			if (root.main) continue;
			if (realCwd !== root.root && !realCwd.startsWith(root.root + path.sep)) continue;
			if (!selected || root.root.length > selected.root.length) selected = root;
		}
		if (!selected) return undefined;
	}

	const labels = assignWorktreeLabels(roots.filter(root => !root.main));
	const label = labels.get(selected.root) ?? (path.basename(selected.root) || selected.root);
	return {
		label: sanitizeStatusText(label),
		hyperlink: selected.root,
		href: pathToFileURL(selected.root).href,
	};
}

/** Записать выбор в сессию, если он отличается от уже записанного. */
function persistSelection(api: ExtensionAPI, state: WtState, selection: string | null): void {
	if (state.lastPersisted === selection) return;
	state.lastPersisted = selection;
	api.appendEntry<PersistedSelection>(WT_ENTRY_TYPE, { v: WT_ENTRY_VERSION, path: selection });
}

/**
 * Полная пересборка состояния: чтение ветки сессии, валидация и разведение
 * коллизий — один раз, вне рендера. Устаревший ответ отбрасывается по поколению
 * и идентичности сессии, чтобы не перезаписать более новый выбор.
 */
async function restart(api: ExtensionAPI, state: WtState, ctx: ExtensionContext): Promise<void> {
	const sessionId = ctx.sessionManager.getSessionId();
	state.sessionId = sessionId;
	state.observedCwd = ctx.cwd;
	const currentGeneration = ++state.generation;
	state.display = undefined;

	const candidate = candidateFromBranch(ctx.sessionManager.getBranch());
	state.explicit = candidate !== undefined;
	// Сравнение для защиты от дублей ведётся в том же каноническом виде, что и
	// запись при живом переключении.
	state.lastPersisted = typeof candidate === "string" ? canonicalPath(candidate) : candidate;

	const resolved = await resolveCandidate(api, candidate, ctx.cwd);
	if (currentGeneration !== state.generation || state.sessionId !== sessionId) return;
	state.display = resolved;
}

/** Живое переключение из результата bash-вызова и отслеживание смены cwd. */
async function handleToolResult(
	api: ExtensionAPI,
	state: WtState,
	event: ToolResultEvent,
	ctx: ExtensionContext,
): Promise<void> {
	if (ctx.cwd !== state.observedCwd) {
		state.observedCwd = ctx.cwd;
		// Явный выбор агента от cwd не зависит; cwd-фолбэк пересобирается до
		// возврата управления хосту, иначе перерисовка увидит старое состояние.
		if (!state.explicit) await restart(api, state, ctx);
	}
	if (event.toolName !== "bash") return;
	const command = event.input.command;
	if (typeof command !== "string") return;
	const candidate = candidateFromToolResult(command, event.content, event.isError);
	if (candidate === undefined) return;

	const sessionId = ctx.sessionManager.getSessionId();
	state.sessionId = sessionId;
	state.explicit = true;
	const currentGeneration = ++state.generation;
	const resolved = await resolveCandidate(api, candidate, ctx.cwd);
	if (currentGeneration !== state.generation || state.sessionId !== sessionId) return;
	state.display = resolved;
	persistSelection(api, state, canonicalPath(candidate));
}

/**
 * Сегмент одного binding'а: рендер читает состояние из замыкания, а не из
 * модульной переменной, чтобы дочерние сессии не делили одну подпись.
 */
function createPathSegment(state: WtState): StatusLineSegment {
	return {
		id: "path",
		render(ctx) {
			const meta = projectMeta(getProjectDir());

			// В linked-cwd подпись lhs — имя проекта из встроенного контекста;
			// в остальных случаях — обычная подпись каталога запуска.
			const lhs = ctx.worktree ? sanitizeStatusText(ctx.worktree.projectName) : meta.label;
			// Гиперссылка ведёт на физический каталог: логический путь может быть симлинком.
			const content = withIcon(categoryIcon(meta.category), fileHyperlink(meta.realDir, lhs));

			// Единственный Git-маркер: короткое имя рабочего worktree, выбранного
			// агентом (или cwd-фолбэком), со своей гиперссылкой на его реальный корень.
			const selected = state.display;
			if (!selected) return { content: theme.fg("statusLinePath", content), visible: true };
			const marker = fileHyperlink(selected.hyperlink, withIcon(theme.icon.git, selected.label));
			return { content: theme.fg("statusLinePath", `${content} › ${marker}`), visible: true };
		},
		describe(ctx) {
			const meta = projectMeta(getProjectDir());
			const lhs = ctx.worktree ? sanitizeStatusText(ctx.worktree.projectName) : meta.label;
			const spans: SegmentView["spans"][number][] = [
				{ t: withIcon(categoryIcon(meta.category), lhs), s: "statusLinePath", href: meta.href },
			];
			const selected = state.display;
			if (selected) {
				spans.push(
					{ t: " › ", s: "statusLinePath" },
					{
						t: withIcon(theme.icon.git, selected.label),
						s: "statusLinePath",
						href: selected.href,
					},
				);
			}
			return { spans };
		},
	};
}

export default function (pi: ExtensionAPI) {
	/** Состояние этого binding'а: у main и сабагентов оно своё. */
	const state: WtState = {
		display: undefined,
		generation: 0,
		sessionId: undefined,
		lastPersisted: undefined,
		explicit: false,
		observedCwd: undefined,
		installed: false,
		previous: undefined,
	};
	const segment = createPathSegment(state);

	/**
	 * Подменять глобальный SEGMENTS.path разрешено только главному TUI-binding'у:
	 * сабагенты получают те же модули, но не должны ни менять общий реестр, ни
	 * восстанавливать его при своём завершении.
	 */
	const ensureInstalled = (ctx: ExtensionContext): void => {
		if (state.installed) return;
		if (ctx.agent.kind !== "main" || ctx.mode !== "tui") return;
		state.previous = SEGMENTS.path;
		SEGMENTS.path = segment;
		state.installed = true;
	};

	const activate = (ctx: ExtensionContext): Promise<void> => {
		ensureInstalled(ctx);
		return restart(pi, state, ctx);
	};

	pi.on("session_start", (_event, ctx) => activate(ctx));
	pi.on("session_switch", (_event, ctx) => activate(ctx));
	pi.on("session_branch", (_event, ctx) => activate(ctx));
	pi.on("session_tree", (_event, ctx) => activate(ctx));
	pi.on("tool_result", (event, ctx) => {
		ensureInstalled(ctx);
		return handleToolResult(pi, state, event, ctx);
	});

	pi.on("session_shutdown", () => {
		// Гасим все висящие async-обновления и забываем состояние этой сессии.
		state.generation++;
		state.sessionId = undefined;
		state.display = undefined;
		state.explicit = false;
		state.observedCwd = undefined;
		// Восстанавливаем только если после нас никто не подменил сегмент ещё раз.
		if (state.installed) {
			if (SEGMENTS.path === segment && state.previous) SEGMENTS.path = state.previous;
			state.installed = false;
		}
	});
}
