import assert from "node:assert/strict";
import { Markdown, TERMINAL, visibleWidth } from "@oh-my-pi/pi-tui";
import { plainText } from "@oh-my-pi/pi-tui/native/spans";
import { getMarkdownTheme, initThemeSync, setTheme, theme } from "@oh-my-pi/pi-tui/theme";
import { installDocumentRendering } from "../omp/extensions/document-markdown/render";

initThemeSync();
TERMINAL.hyperlinks = true;
installDocumentRendering();
const render = (source: string, width = 72) => {
  const md = new Markdown(source, 1, 0, getMarkdownTheme());
  return { md, rows: md.render(width) };
};
let checks = 0;
const check = (name: string, fn: () => void) => { fn(); checks++; console.log(`OK: ${name}`); };

check("named links hide destinations while retaining clickable targets and source", () => {
  const source = "[Документ](https://example.com/very/long/path?q=1)";
  const { md, rows } = render(source);
  assert.equal(plainText(rows.join("\n")).trim(), "Документ");
  assert.match(rows.join("\n"), /\x1b\]8;;https:\/\/example\.com\/very\/long\/path\?q=1/);
  assert.equal(md.describe({} as never).p?.text, source);
});
check("reference links retain their actual target", () => {
  const { rows } = render("[Источник][s]\n\n[s]: https://example.com/reference");
  assert.match(rows.join("\n"), /\x1b\]8;;https:\/\/example\.com\/reference/);
  assert.equal(plainText(rows.join("\n")).trim(), "Источник");
});
check("non-hyperlink terminals keep usable link destinations", () => {
  TERMINAL.hyperlinks = false;
  assert.match(plainText(render("[Источник](https://example.com)").rows.join("\n")), /https:\/\/example\.com/);
  TERMINAL.hyperlinks = true;
});
check("all six heading levels omit Markdown source markers", () => {
  for (let depth = 1; depth <= 6; depth++) {
    const { rows } = render(`${"#".repeat(depth)} Раздел`);
    assert.equal(plainText(rows.join("\n")).trim(), "Раздел");
    assert.ok(!plainText(rows.join("\n")).includes("#"));
  }
});
check("heading hierarchy differs without damaging literal hashes in text/code", () => {
  const h2 = render("## Раздел").rows[0];
  const h3 = render("### Раздел").rows[0];
  assert.notEqual(h2, h3);
  assert.match(plainText(render("Текст ### остаётся\n\n```text\n### literal\n```").rows.join("\n")), /### literal/);
});
check("code fences and explicit plans have distinct full-width backgrounds", () => {
  const { rows } = render("```text\ncode\n\nsecond\n```\n\n```plan\n1. Проверка\n```\n\nОбычный текст", 48);
  const code = rows.find(row => plainText(row).trim() === "code")!;
  const plan = rows.find(row => plainText(row).trim() === "1. Проверка")!;
  const prose = rows.find(row => plainText(row).trim() === "Обычный текст")!;
  assert.ok(code.includes(theme.getBgAnsi("userMessageBg")));
  assert.ok(plan.includes(theme.getBgAnsi("customMessageBg")));
  assert.notEqual(theme.getBgAnsi("userMessageBg"), theme.getBgAnsi("customMessageBg"));
  assert.equal(visibleWidth(code), 48);
  assert.equal(visibleWidth(plan), 48);
  assert.ok(!prose.includes(theme.getBgAnsi("userMessageBg")));
  for (const row of rows) assert.ok(visibleWidth(row) <= 48);
});
check("empty-language and unfinished streaming fences stay inside their background", () => {
  const { md } = render("```\nначало");
  md.transientRenderCache = true;
  assert.ok(md.render(40).find(row => plainText(row).trim() === "начало")?.includes(theme.getBgAnsi("userMessageBg")));
  md.setText("```\nначало\nконец\n```\n\nПосле");
  md.transientRenderCache = false;
  const rows = md.render(40);
  assert.ok(!rows.find(row => plainText(row).trim() === "После")?.includes(theme.getBgAnsi("userMessageBg")));
});
check("unchanged renders reuse rows and resize recomputes background width", () => {
  const { md, rows } = render("```text\ncode\n```", 48);
  assert.equal(md.render(48), rows);
  assert.equal(visibleWidth(md.render(30).find(row => plainText(row).trim() === "code")!), 30);
});
const oldHeading = render("### Раздел").rows.join("\n");
const switched = await setTheme("light");
assert.ok(switched.success, switched.error);
check("theme replacement refreshes colors rather than retaining the old palette", () => {
  const after = render("### Раздел").rows.join("\n");
  assert.notEqual(oldHeading, after);
});
console.log(`PASS: ${checks} document-rendering checks`);
