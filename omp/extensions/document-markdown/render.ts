import { Markdown, TERMINAL, truncateToWidth, visibleWidth } from "@oh-my-pi/pi-tui";
import { AssistantMessageComponent } from "@oh-my-pi/pi-tui/chat/assistant-message";
import { plainText } from "@oh-my-pi/pi-tui/native/spans";
import { getMarkdownTheme, theme, type Theme } from "@oh-my-pi/pi-tui/theme";
import type { MarkdownTheme } from "@oh-my-pi/pi-tui";

// Only public exported host surfaces. Never alter model/session Markdown source,
// the package on disk, or the core's theme-change callback.
const INSTALLED = Symbol.for("q.omp.document-markdown.render.v1");
const adapted = new WeakSet<MarkdownTheme>();
type Panel = "userMessageBg" | "customMessageBg";
interface CachedRows {
  input: readonly string[];
  output: readonly string[];
  width: number;
  palette: Theme;
}
const rowCache = new WeakMap<Markdown, CachedRows>();
const HEADING_PREFIX = /^((?:\x1b\[[\d;:]*m)*)(#{3,6})[ \t]+/;

function adaptTheme(): void {
  const mdTheme = getMarkdownTheme();
  if (adapted.has(mdTheme)) return;
  const heading = mdTheme.heading;
  const linkUrl = mdTheme.linkUrl;
  const codeBorder = mdTheme.codeBlockBorder;
  mdTheme.heading = value => {
    const match = HEADING_PREFIX.exec(value);
    if (!match) return heading(value);
    const level = match[2]!.length;
    const text = match[1]! + value.slice(match[0].length);
    // H1 keeps the host's underline/optional Kitty sizing, H2 its bold face.
    // Subheads become indented, quieter labels instead of source markers.
    const indent = " ".repeat((level - 2) * 2);
    return indent + theme.fg("mdQuote", level > 3 ? theme.italic(text) : text);
  };
  mdTheme.linkUrl = value => TERMINAL.hyperlinks ? "" : linkUrl(value);
  mdTheme.codeBlockBorder = value => {
    if (!value.startsWith("```")) return codeBorder(value);
    const panel: Panel = /^```(?:plan|план)(?:\s|$)/i.test(value) ? "customMessageBg" : "userMessageBg";
    // Real background SGR also identifies fence rows after native wrapping.
    // Do not put custom escape protocols or metadata into the model text.
    return theme.bg(panel, codeBorder(value));
  };
  adapted.add(mdTheme);
}

function fillPanels(rows: readonly string[], width: number): readonly string[] {
  const codeOpen = theme.getBgAnsi("userMessageBg");
  const planOpen = theme.getBgAnsi("customMessageBg");
  let panel: Panel | undefined;
  let output: string[] | undefined;
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index]!;
    let closing = false;
    if (row.includes(codeOpen) || row.includes(planOpen)) {
      const fence = /```([^`]*)$/.exec(plainText(row).trimEnd());
      if (fence) {
        if (panel !== undefined && fence[1]!.trim() === "") closing = true;
        else panel = /^(?:plan|план)(?:\s|$)/i.test(fence[1]!) ? "customMessageBg" : "userMessageBg";
      }
    }
    if (panel !== undefined) {
      output ??= rows.slice();
      const clipped = visibleWidth(row) > width ? truncateToWidth(row, width, "") : row;
      const padding = Math.max(0, width - visibleWidth(clipped));
      output[index] = theme.bgFill(panel, clipped + " ".repeat(padding));
    }
    if (closing) panel = undefined;
  }
  return output ?? rows;
}

export function installDocumentRendering(): void {
  const prototype = Markdown.prototype as Markdown & { [INSTALLED]?: boolean };
  adaptTheme();
  if (prototype[INSTALLED]) return;
  const render = prototype.render;
  const update = AssistantMessageComponent.prototype.updateContent;
  if (typeof render !== "function" || typeof update !== "function") {
    throw new Error("Document Markdown: unsupported OMP host rendering API");
  }
  // Theme replacement can happen independently of an agent turn. Refresh the
  // cached public adapter before the assistant captures it (including copies
  // carrying relative-link resolution), not by replacing core theme callbacks.
  AssistantMessageComponent.prototype.updateContent = function (...args) {
    adaptTheme();
    return update.apply(this, args);
  };
  prototype.render = function (width) {
    adaptTheme();
    const rows = render.call(this, width);
    const cached = rowCache.get(this);
    if (cached?.input === rows && cached.width === width && cached.palette === theme) return cached.output;
    const output = fillPanels(rows, width);
    rowCache.set(this, { input: rows, output, width, palette: theme });
    return output;
  };
  Object.defineProperty(prototype, INSTALLED, { value: true });
}
