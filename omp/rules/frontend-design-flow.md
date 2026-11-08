---
alwaysApply: false
description: "Web UI: Taste before implementation, fixed design direction, Anti Slop during implementation. OMP-specific sequencing and conflict precedence."
---

# Web UI: Taste → direction → Anti Slop during

Applies to designing, building, redesigning or restyling websites and web-app screens in OMP. It does not start a design project for backend work, prose/comment-only changes, native desktop work, or a discussion of skills. Review-only requests stay read-only.

## 1. Direction before implementation

Read `skill://design-taste-frontend` before web UI implementation. Installed root: `/home/q/.omp/agent/skills/design-taste-frontend/`; if discovery has not refreshed, read its `SKILL.md` directly. Use Taste's subject inventory, argument, idea and composition process as art-direction tools, not a second independent implementation workflow. For an app screen, use its `references/app-screens.md` route rather than landing-page rules.

Existing explicit owner direction, supplied references, brand constraints and the surrounding design system come first. A bounded component, responsive fix or behavior fix reuses that direction; do not redraw the site or reopen settled choices. Taste owns direction; Anti Slop filters execution. Do not add a second frontend-design workflow.

Before using a component as a reference, state the requested direction: what is the destination, what must change and what must remain. A component index is navigation, not approval of a mandatory visual standard. If the owner asks to align inputs and other controls toward new selects, do not roll the selects back toward legacy inputs. Current explicit corrections outrank historical patterns and agent-authored direction sheets; newness alone establishes neither acceptance nor permission for a wider rollout.

Before writing UI code, record the applicable direction: product/audience, primary user action, subject-specific idea, section or screen composition, typography, palette, real imagery, ENERGY/RHYTHM/MOTION, and material assumptions. Include a one-line purpose for the major visual choices. Use the existing local spec, or chat for a bounded change. Proposed choices are not owner-approved merely because the agent wrote them. Follow the task's normal design-approval and autonomy boundaries; once direction is settled, do not restart approval for each choice.

Taste's direction sheet is a proposal constrained by the brief, not permission to copy a template. Do not force content into a dealt composition. Keep the existing framework, routes, forms and behaviors unless changing them is requested.

### Bounded fixes: an observable invariant

For a spacing/alignment fix, state the object, direction and visible boundary
before editing: e.g. the whole child container starts to the right of its parent,
including the selected background, not only its text. Use the owner's exact
distance when given; otherwise reuse the design system. Do not turn a padding
request into a redesign. Record the criterion in the existing task/spec, not a
second ledger; a later concept choice does not remove earlier requirements.

Compare before/after on the same route, fixture, viewport, theme and state.
Inspect the settled final frame after the LAST relevant edit, not only an
intermediate concept. For affected control families check background, borders,
label/value/placeholder color and weight, spacing and applicable hover/focus/
selected/disabled states. Preserve distinctions the owner did not ask to remove.
Native tests/typecheck do not prove geometry or icon readability at actual size.
CSS viewport, device scale and real browser zoom are different observations;
report the requested one unverified if it was not exercised.

### Redesign: reference → before → after, not a component rename

For a requested redesign, inspect the owner's already-redesigned screens in the
same app/layer first. Resolve actual paths/routes from code and recent relevant
history; use supplied references first, not an arbitrary old sibling. Record
the chosen reference revision and why it represents the new language. Inspect
the target page as it exists, including full tables, cell renderers, filters,
row/detail actions and responsive alternatives, not only its outer component.

Before editing, add one matrix to the existing local spec:
`region / before evidence / reference pattern / intended visible delta /
preserved behavior / after evidence / status`.
Cover every requested region. For tables, enumerate each column's real
contents, primary/secondary hierarchy, grouping/order, widths/alignment,
formatters, statuses, links/copy/actions, tooltips, overflow and mobile detail.
Keep required information and API/permission/money semantics; legacy spacing,
old cell composition and incomplete rollout are not preservation invariants.
Name justified unchanged regions. Do not invent/remove domain columns simply
to make the diff bigger or copy another screen's unrelated business fields.

Commit to a concrete visual/interaction delta for the requested scope before
implementation. `TheTable` → `TheTableNext`, changing imports, token plumbing
or wrapping the old cells in new chrome is migration, not a redesign. If the
rows/columns remain the legacy presentation where change was requested, the
criterion fails even when tests pass. No arbitrary pixel-change percentage or
line-count quota: each intended delta must be visible and improve the named job.
If the target already meets the chosen reference, show evidence and name the
scope mismatch instead of silently delivering a no-op as a redesign.

After editing, compare all three: reference ↔ result for design consistency,
before ↔ result for substantive change, and before ↔ result for functional
parity. Use the reviewed owned runtime, comparable routes/data/states, viewport,
theme, permissions and scroll position; note unavoidable differences.
Open the actual screenshots and exercise changed actions at desktop and narrow
widths. Link every matrix row to source and render/driving evidence, and inspect
cell contents rather than claiming success from the table component name.
Missing runtime/reference access stays explicitly blocked/unverified; do not
replace it with a static-review score. Fix mismatches before declaring redesign
complete. Review-only requests still stop at findings.

## 2. Anti Slop during implementation

Read `skill://antislop` and only the relevant modules (`antislop-ui`, `antislop-human`, `antislop-layoutmobile`, `antislop-copywriting`, `antislop-code`). Follow `rule://antislop-workflow` for mode resolution, notices, installed-state handling and task-permission boundaries; do not establish a separate web UI mode policy here.

During implementation, filter unmotivated template sections, irrelevant decoration, generic copy and dead controls. Preserve the recorded design direction and useful code-comment context. Check states, keyboard/focus, responsive reflow and truthful content as part of implementation, not as optional polishing.

## 3. Conflict precedence

Within this flow, current owner requirements and the settled design direction override **taste-only preferences** in Taste, Anti Slop and frontend-design. An intentional gradient, glass treatment, monospace, font, color, layout or punctuation is not a defect merely because an upstream list dislikes it. Record the purpose/exception once; do not silently remove it or repeatedly ask to approve it. This does not waive correctness, accessibility, security, working behavior or truthful claims.

No automatic minimum of four images, eight animated elements, video, a novel interactive feature or a theme toggle. Add these only when the brief or recorded purpose calls for them. A quiet design is valid; removing ornament must not remove required content or hierarchy. Do not add dependencies or features to satisfy a style meter.

Taste's invitation to invent plausible sample prices, names, product details or data does not authorize publishing them as facts. Use real content, or visibly label sample content in an explicitly requested concept/prototype. A report-only disclaimer does not make fabricated production content acceptable.

Use WCAG's actual large-text threshold: 18pt (24 CSS px), or 14pt bold (about 18.7 CSS px), before applying the 3:1 text exception; ordinary 18px text still needs 4.5:1. Neither skill's self-report nor Taste's `0 FAIL` proves accessibility.

## 4. Helpers, artifacts and verification

Upstream Taste files stay unmodified; OMP adaptations live in this rule. Version/commit/file hashes: `/home/q/.omp/agent/skills/design-taste-frontend/INSTALLATION.json`. Re-review helpers before use and after an update; installation is not permission to run browser/model/network workloads.

Taste helper paths are `/home/q/.omp/agent/skills/design-taste-frontend/scripts/draw.mjs`, `assets.mjs`, `lint.mjs`, `inspect.mjs` and `scenes.mjs` in that same scripts directory. Do not assume a relative `scripts/` path belongs to the product repo.

Put direction sheets/specs under the owned worktree's locally ignored `.superpowers/specs/`, audit/inspection results under `.superpowers/research/`, and agent-only media under `.superpowers/assets/`. Do not create project `DESIGN.md`, docs, audit folders or root `.taste-skill/` as an unrequested side effect. Promote only real deliverable assets into product paths. Ensure local ignore before writing working artifacts; do not change project `.gitignore` for agent scratch.

For `draw.mjs`, pass an absolute `--out <worktree>/.superpowers/specs/taste` and set `TASTE_SKILL_HISTORY=<worktree>/.superpowers/specs/taste/history.json` on the command. For other helpers, use their verified output option or an isolated cwd under `.superpowers/` with absolute input paths. Do not silently write history to `~/.taste-skill/`. Keep inspector browser profiles in a unique owned `TASTE_SKILL_TMP` directory, never a personal profile or shared profile-cleanup namespace.

Before browser driving, read `xd://eval/browser` once for the current API.
Its direct helpers and raw page context are not Playwright: do not assume
`getByRole`, mixed role/CSS selectors or array-shaped diagnostics. Read the
actual returned shape; execute DOM predicates in page context. After navigation,
rerender or an action error, re-observe and scope selectors to the current
dialog/state before acting again. Plan a finite scenario and capture the
settled final state within the owned runtime window; no blind extension/retry.

Before claiming a preview is open with the changes, confirm its owned readiness,
actual URL, worktree/source identity and expiry. Opening a URL alone does not
start a server or prove that an expired preview still serves the requested code.

Verification follows `skill://repository-testing`, `rule://no-autotests`, `rule://heavy-jobs-resource-guard` and the owned-surface rules. Use native regressions/typecheck and the reviewed isolated headless runtime; Taste diagnostics do not replace those entrypoints or authorize an extra dev server/browser. Do not run an unsafe helper merely to satisfy an upstream gate. If a required check cannot run, report that check as blocked/unverified, never PASS.

Finish by checking the real authorized UI at relevant widths and exercising the changed actions/states. Record the applicable Anti Slop Delivery Gate with actual evidence, explicit design exceptions and unavailable checks. Do not suppress a failing check or claim a click-through from source inspection. A Taste measurement is diagnostic, not a veto over the approved aesthetic and not proof of behavior.

Self-check: Taste informed direction before code; Anti Slop filtered implementation in the resolved mode; reference/before/after and every intended redesign delta are evidenced; the agreed direction survived; verification claims match the exercised surface.
