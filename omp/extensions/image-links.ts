/**
 * OMP ↔ Kitty: Ctrl-клик по путям изображений.
 *
 * Расширение переписывает только текстовые блоки финализированного сообщения
 * ассистента: обычные (не внутри ссылки/кода) пути к существующим локальным
 * файлам изображений оборачиваются в Markdown-ссылки с `file://` целью, чтобы
 * терминал отрисовал их как OSC 8 hyperlink и открыл по Ctrl-клику. Видимое
 * написание пути сохраняется. Существующие ссылки, изображения, HTML,
 * reference-определения и код (включая fenced-листинги путей) не меняются;
 * thinking- и toolCall-блоки не трогаются вовсе.
 *
 * Пакеты OMP не патчатся: используются задокументированные хуки
 * `assistant_message` (перезапись текста финального сообщения) и
 * `before_agent_start` (короткая политика в systemPrompt), а разбор Markdown
 * идёт лексером хоста `@oh-my-pi/pi-utils/marked`, а не вторым парсером.
 *
 * Разрешение путей детерминировано: кандидат принимается, только если это
 * существующий обычный файл с image-расширением, найденный относительно cwd
 * сессии либо относительно каталога, явно объявленного в том же тексте как
 * worktree/cwd (метка плюс существующий абсолютный или `~/` каталог). Basename
 * разрешается только прямо под такой известной базой; рекурсивного поиска по
 * basename и обхода чужих worktree нет. Если кандидат даёт разные реальные
 * файлы в разных базах или не найден вовсе — текст остаётся как есть. Кеши
 * файловой системы живут только внутри одного финализированного сообщения;
 * глобальных кешей путей нет.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { Lexer, type Token, type Tokens } from "@oh-my-pi/pi-utils/marked";

/** Универсальный взгляд на токен лексера: известные поля плюс index signature. */
type AnyToken = Tokens.Generic;

/** Маркер, по которому политика не добавляется в systemPrompt дважды. */
const POLICY_MARKER = "IMAGE LINKS:";

/** Короткая политика для стримингового ответа: финальную перезапись делает хук. */
const POLICY = `${POLICY_MARKER} if you mention an existing local image, also write it as a Markdown link whose visible text stays the path you quoted and whose target is that file's URL, e.g. \`[shot.png](<file:///home/q/shot.png>)\`. Use the full absolute path you actually observed; when you work outside the session cwd, keep that real worktree path instead of guessing. Never link — or claim to have observed — a file that does not exist.`;

/** Допустимые расширения изображений (без учёта регистра). */
const IMAGE_EXTENSION = /\.(?:png|jpe?g|webp|gif|avif|svg|tiff?|bmp|heic|heif|jxl)$/i;

/** Быстрый предфильтр: есть ли в тексте хоть намёк на image-расширение. */
const IMAGE_EXTENSION_HINT = /\.(?:png|jpe?g|webp|gif|avif|svg|tiff?|bmp|heic|heif|jxl)\b/i;

/** Символы, обрывающие «слово» пути в прозе (кавычки, скобки, пунктуация). */
const TOKEN_STOP = " \t\n\r`\"'<>[](){}|*?!,;:#\\";

/** Символы, обрывающие `file://` URL (пробелы и markdown-обёртки). */
const URL_STOP = " \t\n\r`\"'<>[](){}|*?";

/** Лимит кандидатов на один текстовый блок, чтобы хук оставался дешёвым. */
const MAX_CANDIDATES = 1000;

/** Лимит длины текстового блока, для которого вообще имеет смысл разбор. */
const MAX_TEXT_LENGTH = 1_000_000;

interface PathCache {
	/** stat по абсолютному пути; null — путь не существует/недоступен. */
	stat: Map<string, fs.Stats | null>;
	/** realpath по абсолютному пути; null — не удалось. */
	real: Map<string, string | null>;
	/** Базы для относительных путей: cwd сессии плюс явно названные каталоги. */
	bases: string[];
}

interface Range {
	start: number;
	end: number;
}

interface Edit {
	/** Смещение начала в нормализованном тексте. */
	start: number;
	/** Смещение конца (исключающего) в нормализованном тексте; равно start для вставки. */
	end: number;
	/** Чем заменить диапазон (для вставки — просто текст). */
	text: string;
}

/** Состояние одного текстового блока. */
interface Doc {
	norm: string;
	protected: Range[];
	edits: Edit[];
	cache: PathCache;
}

function statOf(cache: PathCache, absolute: string): fs.Stats | null {
	const cached = cache.stat.get(absolute);
	if (cached !== undefined) return cached;
	let value: fs.Stats | null = null;
	try {
		value = fs.statSync(absolute);
	} catch {
		value = null;
	}
	cache.stat.set(absolute, value);
	return value;
}

function realOf(cache: PathCache, absolute: string): string | null {
	const cached = cache.real.get(absolute);
	if (cached !== undefined) return cached;
	let value: string | null = null;
	try {
		value = fs.realpathSync(absolute);
	} catch {
		value = null;
	}
	cache.real.set(absolute, value);
	return value;
}

/**
 * Нормализация (та же, что делает лексер хоста перед блочным разбором) плюс
 * карта «нормализованное смещение → смещение в исходнике».
 * Нужна, чтобы правки вставлялись обратно в исходный текст без потери
 * табов/CRLF где-либо ещё.
 */
function buildNormalizedMap(text: string): { norm: string; toOriginal: number[] } {
	let norm = "";
	const toOriginal: number[] = [];
	for (let i = 0; i < text.length; i++) {
		const ch = text.charAt(i);
		if (ch === "\r") {
			const at = i;
			if (text.charAt(i + 1) === "\n") i++;
			norm += "\n";
			toOriginal.push(at);
		} else if (ch === "\t") {
			for (let k = 0; k < 4; k++) {
				norm += " ";
				toOriginal.push(i);
			}
		} else {
			norm += ch;
			toOriginal.push(i);
		}
	}
	toOriginal.push(text.length);
	return { norm, toOriginal };
}

/** Похоже ли значение на путь к изображению по расширению и без wildcard. */
function looksLikeImagePath(value: string): boolean {
	if (value.length === 0 || value.length > 4096) return false;
	if (value.includes("*") || value.includes("?")) return false;
	return IMAGE_EXTENSION.test(value);
}

interface Resolved {
	/** Доказанно существующий абсолютный путь (без realpath: сохраняем написание). */
	absolute: string;
	/** Готовая `file://` цель. */
	url: string;
}

/**
 * Разрешить кандидата в единственный существующий файл-изображение.
 * `null` — не изображение, не существует, недоступно или неоднозначно;
 * удалённые (http/https, внутренние схемы OMP) пути отклоняются.
 */
function resolveImagePath(raw: string, cache: PathCache): Resolved | null {
	const value = raw.trim();
	if (!looksLikeImagePath(value)) return null;
	if (/[\x00-\x1f\x7f]/.test(value)) return null;

	const schemeMatch = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(value);
	const scheme: boolean | undefined = schemeMatch ? schemeMatch[1].toLowerCase() === "file" : undefined;
	const candidates: string[] = [];

	if (scheme === false) return null;
	if (scheme === true) {
		if (!/^file:\/\//i.test(value)) return null;
		try {
			candidates.push(fileURLToPath(value));
		} catch {
			return null;
		}
	} else if (value.startsWith("~/")) {
		candidates.push(path.join(os.homedir(), value.slice(2)));
	} else if (path.isAbsolute(value)) {
		candidates.push(value);
	} else {
		// Относительный путь (включая чистый basename) разрешается прямо под
		// каждой известной базой: cwd сессии или явно названный каталог.
		// Никакого рекурсивного поиска по basename и обхода каталогов.
		for (const base of cache.bases) {
			if (!path.isAbsolute(base)) continue;
			candidates.push(path.resolve(base, value));
		}
	}

	const files: string[] = [];
	const seenReal = new Set<string>();
	for (const candidate of candidates) {
		if (/[\x00-\x1f\x7f]/.test(candidate)) continue;
		const stats = statOf(cache, candidate);
		if (!stats?.isFile()) continue;
		const real = realOf(cache, candidate) ?? candidate;
		if (seenReal.has(real)) continue;
		seenReal.add(real);
		files.push(candidate);
	}

	// Ровно один реальный файл; два разных — неоднозначность, менять нельзя.
	if (files.length !== 1) return null;
	const absolute = files[0] as string;
	if (/[\x00-\x1f\x7f]/.test(absolute)) return null;
	return { absolute, url: pathToFileURL(absolute).href };
}

/**
 * Явно названные в тексте каталоги — дополнительные базы для относительных
 * путей. Базой становится только каталог, объявленный меткой
 * worktree/cwd/current working directory/рабочий каталог/ворктри на той же
 * строке непосредственно перед значением, начинающийся с `/` или `~/` и
 * реально существующий как каталог. Произвольные абсолютные подстроки
 * (ссылки, URL, примеры кода) базами не становятся. Пути с пробелами
 * берутся из кавычек и кодеспанов.
 */
function collectBaseDirs(norm: string, cache: PathCache): string[] {
	const bases: string[] = [];
	const seenReal = new Set<string>();
	const label = /(?:\bworktrees?\b|\bcwd\b|working directory|рабочий каталог|ворктри)\s*(?:[:=—–-]\s*)?["'`]?$/i;
	const consider = (value: string, at: number): void => {
		if (bases.length >= 64) return;
		const trimmed = value.trim();
		if (trimmed.length < 2 || trimmed.length > 4096) return;
		if (!trimmed.startsWith("~/") && !path.isAbsolute(trimmed)) return;
		if (/[\x00-\x1f\x7f]/.test(trimmed)) return;
		const lineStart = norm.lastIndexOf("\n", Math.max(at - 1, 0)) + 1;
		if (!label.test(norm.slice(lineStart, at))) return;
		const candidate = trimmed.startsWith("~/") ? path.join(os.homedir(), trimmed.slice(2)) : trimmed;
		if (/[\x00-\x1f\x7f]/.test(candidate)) return;
		const stats = statOf(cache, candidate);
		if (!stats?.isDirectory()) return;
		const real = realOf(cache, candidate) ?? candidate;
		if (seenReal.has(real)) return;
		seenReal.add(real);
		bases.push(candidate);
	};

	const spanned = /`([^`\n]+)`|"([^"\n]+)"|'([^'\n]+)'/g;
	for (const match of norm.matchAll(spanned)) {
		const value = match[1] ?? match[2] ?? match[3];
		if (value === undefined) continue;
		consider(value, (match.index ?? 0) + 1);
	}
	const bare = /(?:~\/|\/)[^\s"'`()[\]{}<>|*?,;:!]+/g;
	for (const match of norm.matchAll(bare)) {
		const value = match[0];
		if (value === undefined) continue;
		consider(value, match.index ?? 0);
	}
	return bases;
}

/** Найдено ли `raw` в нормализованном тексте в границах контейнера. */
function locate(doc: Doc, raw: string, from: number, limit: number): number {
	const at = doc.norm.indexOf(raw, from);
	if (at === -1 || at + raw.length > limit) return -1;
	return at;
}

/** Прочитать «слово» пути: от `start` до термminатора, обрезав хвостовую точку. */
function readToken(norm: string, start: number): { end: number; scanEnd: number } {
	let end = start;
	while (end < norm.length && !TOKEN_STOP.includes(norm.charAt(end))) end++;
	let trimmed = end;
	while (trimmed > start && norm.charAt(trimmed - 1) === ".") trimmed--;
	return { end: trimmed, scanEnd: end };
}

/** То же для `file://` URL: `:` внутри схемы не должен обрывать токен. */
function readUrlToken(norm: string, start: number): { end: number; scanEnd: number } {
	let end = start;
	while (end < norm.length && !URL_STOP.includes(norm.charAt(end))) end++;
	let trimmed = end;
	while (trimmed > start && (norm.charAt(trimmed - 1) === "." || norm.charAt(trimmed - 1) === ")")) trimmed--;
	return { end: trimmed, scanEnd: end };
}

/** Ячейка/элемент с вложенными inline-токенами. */
interface TokenGroup {
	tokens?: Token[];
}

/**
 * Экранировать подпись ссылки так, чтобы «опасные» символы Markdown
 * (обратный слеш, бэктик, эмфазис, скобки, угловые скобки) не ломали
 * конструкцию `[label](<url>)`; видимое написание сохраняется.
 */
function linkLabel(visible: string): string {
	return visible.replace(/([\\`*_[\]<>])/g, "\\$1");
}

/** Ссылка на цель внутри code span: заменяем весь span на `[raw](<url>)`. */
function codespanEdit(doc: Doc, token: AnyToken, start: number, end: number): Edit | null {
	const text = typeof token.text === "string" ? token.text.trim() : "";
	if (!looksLikeImagePath(text)) return null;
	const resolved = resolveImagePath(text, doc.cache);
	if (!resolved) return null;
	const raw = typeof token.raw === "string" ? token.raw : "";
	if (raw.length === 0) return null;
	return { start, end, text: `[${raw}](<${resolved.url}>)` };
}

/**
 * Fenced-листинг, целиком состоящий из путей к существующим изображениям:
 * после блока добавляем компактный кликабельный список, не меняя сам листинг.
 */
function fenceListingEdit(doc: Doc, token: AnyToken, end: number): Edit | null {
	const raw = typeof token.raw === "string" ? token.raw : "";
	if (!/^ {0,3}(?:`{3,}|~{3,})/.test(raw)) return null;
	const lang = typeof token.lang === "string" ? token.lang.trim().toLowerCase() : "";
	if (lang !== "" && !["text", "txt", "path", "paths", "file", "files", "image", "images"].includes(lang)) {
		return null;
	}
	const lines = String(token.text ?? "")
		.split("\n")
		.map(line => line.trim())
		.filter(line => line.length > 0);
	if (lines.length === 0) return null;
	const links: string[] = [];
	for (const line of lines) {
		if (!looksLikeImagePath(line)) return null;
		const resolved = resolveImagePath(line, doc.cache);
		if (!resolved) return null;
		links.push(`[${linkLabel(line)}](<${resolved.url}>)`);
	}
	return { start: end, end, text: `\n\nИзображения: ${links.join(" · ")}` };
}

/**
 * Выполнить локализацию контейнера и откатить уже собранные правки, если она
 * не удалась: иначе частично собранные правки перекрыли бы защиту контейнера.
 */
function withRollback(doc: Doc, run: () => boolean): boolean {
	const edits = doc.edits.length;
	const protectedCount = doc.protected.length;
	const ok = run();
	if (!ok) {
		doc.edits.length = edits;
		doc.protected.length = protectedCount;
	}
	return ok;
}

/** Классифицировать блочный токен: защитить непрозрачное, пройти прозу. */
function classifyBlockToken(doc: Doc, token: AnyToken, start: number, end: number, topLevel: boolean): boolean {
	switch (token.type) {
		case "code": {
			doc.protected.push({ start, end });
			if (topLevel) {
				const edit = fenceListingEdit(doc, token, end);
				if (edit) doc.edits.push(edit);
			}
			return true;
		}
		case "html":
		case "def":
		case "image":
		case "link": {
			doc.protected.push({ start, end });
			return true;
		}
		case "codespan": {
			// Кодеспан защищается всегда: даже с заменяющей правкой проза
			// внутри тех же бэктиков не должна обходиться повторно.
			doc.protected.push({ start, end });
			const edit = codespanEdit(doc, token, start, end);
			if (edit) doc.edits.push(edit);
			return true;
		}
		case "paragraph":
		case "heading": {
			return withRollback(doc, () => walkInline(doc, (token.tokens ?? []) as Token[], start, end));
		}
		case "blockquote": {
			return withRollback(doc, () => walkBlocks(doc, (token.tokens ?? []) as Token[], start, end, false));
		}
		case "list": {
			const items = (token.items ?? []) as TokenGroup[];
			return withRollback(doc, () =>
				walkGroups(
					doc,
					items.map(item => (item.tokens ?? []) as Token[]),
					start,
					end,
					false,
				),
			);
		}
		case "table": {
			const header = (token.header ?? []) as TokenGroup[];
			const rows = (token.rows ?? []) as TokenGroup[][];
			const cells = header.concat(...rows);
			return withRollback(doc, () =>
				walkGroups(
					doc,
					cells.map(cell => (cell.tokens ?? []) as Token[]),
					start,
					end,
					false,
				),
			);
		}
		case "text": {
			const inner = token.tokens;
			if (Array.isArray(inner) && inner.length > 0) {
				return withRollback(doc, () => walkInline(doc, inner as Token[], start, end));
			}
			return true;
		}
		default:
			return true;
	}
}

/** Классифицировать inline-токен. */
function classifyInlineToken(doc: Doc, token: AnyToken, start: number, end: number): boolean {
	switch (token.type) {
		case "codespan": {
			// Кодеспан защищается всегда: даже с заменяющей правкой проза
			// внутри тех же бэктиков не должна обходиться повторно.
			doc.protected.push({ start, end });
			const edit = codespanEdit(doc, token, start, end);
			if (edit) doc.edits.push(edit);
			return true;
		}
		case "link":
		case "image":
		case "html": {
			doc.protected.push({ start, end });
			return true;
		}
		case "em":
		case "strong":
		case "del":
		case "text": {
			const inner = token.tokens;
			if (Array.isArray(inner) && inner.length > 0) {
				return withRollback(doc, () => walkInline(doc, inner as Token[], start, end));
			}
			return true;
		}
		default:
			return true;
	}
}

/** Пройти список inline-токенов внутри контейнера. false — не удалось локализовать. */
function walkInline(doc: Doc, tokens: Token[], from: number, limit: number): boolean {
	let cursor = from;
	for (const rawToken of tokens) {
		const raw = typeof rawToken.raw === "string" ? rawToken.raw : "";
		if (raw.length === 0 || /^\s+$/.test(raw)) continue;
		const at = locate(doc, raw, cursor, limit);
		if (at === -1) return false;
		cursor = at + raw.length;
		const token = rawToken as AnyToken;
		if (!classifyInlineToken(doc, token, at, cursor)) doc.protected.push({ start: at, end: cursor });
	}
	return true;
}

/** Пройти блочные токены внутри контейнера. false — не удалось локализовать. */
function walkBlocks(doc: Doc, tokens: Token[], from: number, limit: number, topLevel: boolean): boolean {
	let cursor = from;
	for (const rawToken of tokens) {
		const raw = typeof rawToken.raw === "string" ? rawToken.raw : "";
		if (raw.length === 0 || /^\s+$/.test(raw)) continue;
		const at = locate(doc, raw, cursor, limit);
		if (at === -1) return false;
		cursor = at + raw.length;
		const token = rawToken as AnyToken;
		if (!classifyBlockToken(doc, token, at, cursor, topLevel)) {
			doc.protected.push({ start: at, end: cursor });
		}
	}
	return true;
}

/** Пройти несколько групп токенов (ячейки таблицы, элементы списка) с общим курсором. */
function walkGroups(doc: Doc, groups: Token[][], from: number, limit: number, topLevel: boolean): boolean {
	let cursor = from;
	for (const group of groups) {
		for (const rawToken of group) {
			const raw = typeof rawToken.raw === "string" ? rawToken.raw : "";
			if (raw.length === 0 || /^\s+$/.test(raw)) continue;
			const at = locate(doc, raw, cursor, limit);
			if (at === -1) return false;
			cursor = at + raw.length;
			const token = rawToken as AnyToken;
			if (!classifyBlockToken(doc, token, at, cursor, topLevel)) {
				doc.protected.push({ start: at, end: cursor });
			}
		}
	}
	return true;
}

/** Проверка защищённых диапазонов: точечная и по всему интервалу кандидата. */
interface Protection {
	/** Индекс внутри защищённого диапазона. */
	at(index: number): boolean;
	/** Есть ли защищённый диапазон, пересекающий [start, end). */
	spans(start: number, end: number): boolean;
}

/** Проверка «внутри защищённого диапазона» с линейным курсором по возрастанию. */
function createProtectedChecker(ranges: Range[]): Protection {
	const sorted = ranges.slice().sort((a, b) => a.start - b.start);
	let cursor = 0;
	return {
		at(index: number): boolean {
			while (cursor < sorted.length && (sorted[cursor] as Range).end <= index) cursor++;
			const range = sorted[cursor];
			return range !== undefined && range.start <= index && index < range.end;
		},
		spans(start: number, end: number): boolean {
			for (const range of sorted) {
				if (range.end <= start) continue;
				if (range.start >= end) return false;
				return true;
			}
			return false;
		},
	};
}

/**
 * Просканировать незащищённую прозу на пути изображений и добавить правки.
 * Кавычки и `file://` обрабатываются до «слов», чтобы сохранить пробелы и
 * схему. Кандидат должен целиком лежать вне защищённых диапазонов.
 */
function scanProse(doc: Doc, isProtected: Protection): void {
	const norm = doc.norm;
	let candidates = 0;
	let index = 0;
	while (index < norm.length && candidates < MAX_CANDIDATES) {
		if (isProtected.at(index)) {
			index++;
			continue;
		}
		const ch = norm.charAt(index);

		if ((ch === '"' || ch === "'") && (index === 0 || !/[A-Za-z0-9]/.test(norm.charAt(index - 1)))) {
			const close = norm.indexOf(ch, index + 1);
			if (close === -1 || close - index > 4096) {
				index++;
				continue;
			}
			const inner = norm.slice(index + 1, close);
			if (!inner.includes("\n")) {
				const lead = /^\s*/.exec(inner)?.[0].length ?? 0;
				const trail = /\s*$/.exec(inner)?.[0].length ?? 0;
				const core = inner.slice(lead, inner.length - trail);
				const coreStart = index + 1 + lead;
				const coreEnd = coreStart + core.length;
				if (core.length > 0 && !isProtected.spans(coreStart, coreEnd) && looksLikeImagePath(core)) {
					const resolved = resolveImagePath(core, doc.cache);
					if (resolved) {
						candidates++;
						doc.edits.push({ start: coreStart, end: coreEnd, text: `[${linkLabel(core)}](<${resolved.url}>)` });
					}
				}
			}
			index = close + 1;
			continue;
		}

		const code = ch.charCodeAt(0);
		const isPathStart =
			ch === "/" ||
			ch === "~" ||
			ch === "." ||
			ch === "_" ||
			(code >= 48 && code <= 57) ||
			(code >= 65 && code <= 90) ||
			(code >= 97 && code <= 122) ||
			code > 127;
		if (isPathStart && (index === 0 || !/[A-Za-z0-9_./~-]/.test(norm.charAt(index - 1)))) {
			// Токен с чужой схемой (в т.ч. внутренние/удалённые) пропускается
			// целиком, чтобы его `//`-хвост не был принят за локальный путь.
			const schemeMatch = /^([A-Za-z][A-Za-z0-9+.-]*):(?=\S)/.exec(norm.slice(index, index + 64));
			if (schemeMatch) {
				if ((schemeMatch[1] ?? "").toLowerCase() === "file" && /^file:\/\//i.test(norm.slice(index))) {
					const url = readUrlToken(norm, index);
					const visible = norm.slice(index, url.end);
					if (!isProtected.spans(index, url.end) && looksLikeImagePath(visible)) {
						const resolved = resolveImagePath(visible, doc.cache);
						if (resolved) {
							candidates++;
							doc.edits.push({ start: index, end: url.end, text: `[${linkLabel(visible)}](<${resolved.url}>)` });
						}
					}
					index = Math.max(url.scanEnd, index + 1);
					continue;
				}
				const skip = readUrlToken(norm, index);
				index = Math.max(skip.scanEnd, index + 1);
				continue;
			}
			const token = readToken(norm, index);
			if (token.end > index) {
				const visible = norm.slice(index, token.end);
				if (!isProtected.spans(index, token.end) && looksLikeImagePath(visible)) {
					const resolved = resolveImagePath(visible, doc.cache);
					if (resolved) {
						candidates++;
						doc.edits.push({ start: index, end: token.end, text: `[${linkLabel(visible)}](<${resolved.url}>)` });
					}
				}
			}
			index = Math.max(token.scanEnd, index + 1);
			continue;
		}

		index++;
	}
}

/** Применить правки к исходному тексту через карту нормализации. */
function applyEdits(text: string, toOriginal: number[], edits: Edit[]): string | undefined {
	const mapped: Edit[] = [];
	for (const edit of edits) {
		const start = toOriginal[edit.start];
		const end = toOriginal[edit.end];
		if (start === undefined || end === undefined || end < start) continue;
		mapped.push({ start, end, text: edit.text });
	}
	if (mapped.length === 0) return undefined;
	mapped.sort((a, b) => b.start - a.start || b.end - a.end);
	let out = text;
	let boundary = text.length + 1;
	for (const edit of mapped) {
		if (edit.end > boundary) continue;
		out = out.slice(0, edit.start) + edit.text + out.slice(edit.end);
		boundary = edit.start;
	}
	return out === text ? undefined : out;
}

/** Переписать один текстовый блок; undefined — оставить как есть. */
function rewriteText(
	text: string,
	normalized: { norm: string; toOriginal: number[] },
	cache: PathCache,
): string | undefined {
	const { norm, toOriginal } = normalized;
	const doc: Doc = { norm, protected: [], edits: [], cache };
	const tokens = Lexer.lex(text) as Token[];
	if (!walkBlocks(doc, tokens, 0, norm.length, true)) return undefined;

	scanProse(doc, createProtectedChecker(doc.protected));
	return applyEdits(text, toOriginal, doc.edits);
}

export default function (pi: ExtensionAPI) {
	pi.on("before_agent_start", event => {
		const systemPrompt = event.systemPrompt;
		if (systemPrompt.some(part => part.includes(POLICY_MARKER))) return;
		return { systemPrompt: [...systemPrompt, POLICY] };
	});

	pi.on("assistant_message", (event, ctx) => {
		const content = event.message.content;
		if (!Array.isArray(content) || content.length === 0) return;

		// Кеш живёт ровно одно финализированное сообщение: никаких глобальных
		// записей о путях, которые могли устареть. Базы для относительных путей
		// берутся из cwd сессии и из явно объявленных каталогов этого же
		// сообщения — во всех его текстовых блоках, даже без image-расширения.
		const cache: PathCache = { stat: new Map(), real: new Map(), bases: [] };
		const normalizedAll = new Map<number, { norm: string; toOriginal: number[] }>();
		const prepared = new Map<number, { norm: string; toOriginal: number[] }>();
		for (const [index, block] of content.entries()) {
			if (block.type !== "text") continue;
			if (block.text.length === 0 || block.text.length > MAX_TEXT_LENGTH) continue;
			const normalized = buildNormalizedMap(block.text);
			normalizedAll.set(index, normalized);
			if (IMAGE_EXTENSION_HINT.test(block.text)) prepared.set(index, normalized);
		}
		if (prepared.size === 0) return;

		const bases: string[] = [];
		const seenBases = new Set<string>();
		if (path.isAbsolute(ctx.cwd)) {
			seenBases.add(realOf(cache, ctx.cwd) ?? ctx.cwd);
			bases.push(ctx.cwd);
		}
		for (const { norm } of normalizedAll.values()) {
			if (bases.length >= 64) break;
			for (const dir of collectBaseDirs(norm, cache)) {
				if (bases.length >= 64) break;
				const real = realOf(cache, dir) ?? dir;
				if (seenBases.has(real)) continue;
				seenBases.add(real);
				bases.push(dir);
			}
		}
		cache.bases = bases;

		let changed = false;
		const next = content.map((block, index) => {
			if (block.type !== "text") return block;
			const normalized = prepared.get(index);
			if (!normalized) return block;
			const rewritten = rewriteText(block.text, normalized, cache);
			if (rewritten === undefined || rewritten === block.text) return block;
			changed = true;
			return { ...block, text: rewritten };
		});
		if (!changed) return;
		return { content: next };
	});
}
