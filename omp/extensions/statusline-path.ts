/**
 * OMP status-line path segment override.
 *
 * Заменяет SEGMENTS.path из @oh-my-pi/pi-tui на компактный вариант: обычная
 * сессия показывает только basename каталога запуска, связанный worktree —
 * имя проекта, разделитель и имя worktree. Иконка в начале зависит от того,
 * в каком корне лежит физический каталог запуска. Ничего из node_modules не
 * патчится — подмена и восстановление идут через экспортируемый SEGMENTS.
 *
 * Дорогие вещи вынесены из рендера: шесть именованных корней канонизируются
 * один раз при загрузке модуля, а физический путь, подпись и категория корня
 * пересчитываются только при смене каталога проекта (кэш на одну запись).
 * Иконки темы читаются на каждом рендере, чтобы смена темы/preset была видна.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { SEGMENTS } from "@oh-my-pi/pi-tui/status-line";
import type { StatusLineSegment } from "@oh-my-pi/pi-tui/status-line/types";
import { theme } from "@oh-my-pi/pi-tui/theme";
import { fileHyperlink } from "@oh-my-pi/pi-tui/render/hyperlink";
import { sanitizeStatusText } from "@oh-my-pi/pi-tui/chrome/shared";
import { getProjectDir } from "@oh-my-pi/pi-utils";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

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
		label: sanitizeStatusText(dirLabel(dir)),
		category: classifyRoot(realDir),
	};
	return cachedMeta;
}

const pathSegment: StatusLineSegment = {
	id: "path",
	render(ctx) {
		const meta = projectMeta(getProjectDir());

		// Связанный worktree: имя проекта, видимый разделитель и имя worktree —
		// безусловно, даже когда оно совпадает с веткой (её показывает git-сегмент).
		if (ctx.worktree) {
			const project = sanitizeStatusText(ctx.worktree.projectName);
			const worktree = sanitizeStatusText(ctx.worktree.worktreeName);
			const label = `${project} › ${withIcon(theme.icon.worktree, worktree)}`;
			// Гиперссылка ведёт на физический каталог: логический путь может быть симлинком.
			const content = withIcon(categoryIcon(meta.category), fileHyperlink(meta.realDir, label));
			return { content: theme.fg("statusLinePath", content), visible: true };
		}

		const content = withIcon(categoryIcon(meta.category), fileHyperlink(meta.realDir, meta.label));
		return { content: theme.fg("statusLinePath", content), visible: true };
	},
};

export default function (pi: ExtensionAPI) {
	const previous = SEGMENTS.path;
	SEGMENTS.path = pathSegment;

	pi.on("session_shutdown", () => {
		// Восстанавливаем только если после нас никто не подменил сегмент ещё раз.
		if (SEGMENTS.path === pathSegment) SEGMENTS.path = previous;
	});
}
