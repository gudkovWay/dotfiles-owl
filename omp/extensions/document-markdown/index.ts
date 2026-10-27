import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { installDocumentRendering } from "./render";

const MARKER = "DOCUMENT MARKDOWN:";
const POLICY = `${MARKER} Keep the user's existing terminal theme. Structure substantial replies as readable documents: lead with the result; use short ## sections, compact paragraphs, and occasional bold labels for findings, causes, conclusions and verification. Use lists for real steps or independent items, not every sentence. Short answers need no headings. Use meaningful link labels; preserve real destinations and required visible file paths. Use ordinary fenced blocks with their real language for source code and commands. For an actual actionable plan that benefits from a separate panel, use a fenced block labelled plan, containing plain-text numbered steps or checkboxes; do not hide ordinary explanations, prose or entire replies in code/plan fences. The renderer supplies backgrounds; do not emit ANSI or fake UI boxes. Preserve all requested detail and acceptance criteria; structure is not permission to omit content.`;

export default function documentMarkdown(pi: ExtensionAPI): void {
  installDocumentRendering();
  pi.on("before_agent_start", event => {
    if (event.systemPrompt.includes(MARKER)) return;
    return { systemPrompt: `${event.systemPrompt}\n\n${POLICY}` };
  });
}
