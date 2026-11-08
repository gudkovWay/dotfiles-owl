---
name: p2p-linear
description: "Use when accepted p2p-frontend implementation creates or resumes a task-worktree, changes accepted outcomes, finishes work, or confirms dev integration. Not for questions, read-only analysis, ordinary branch switching or ecom."
---

# p2p worktree → Linear

## HARD GATE

Only p2p's verified remote and an owned linked task worktree. Existing OMP Linear MCP is the only Linear connection; no owner_id, tokens, CLI or new auth profile. No comments or project creation. Main approves the exact draft; Luna never publishes. This skill does not authorize merge, delivery or unrelated writes. Explicit no-Linear/read-only owner scope wins.

Helper: `/home/q/.config/worktrunk/projects/p2p-frontend/linear_workflow.py`.
Installed project-local copy: `<owned-worktree>/.omp/skills/p2p-linear/SKILL.md`.
Run `wt linear -- <operation> ...` with cwd set to the exact owned worktree, or invoke the helper with `--root <owned-worktree>`. Working files belong only in that worktree's ignored `.superpowers/linear/`.

## Current state

2026-11-02: p2p-only companion; team FRONT, integration dev, all-ready-and-integrated status Deployment. The helper stores durable bindings in shared Git metadata. Main uses the existing mounted `mcp__linear_*` tools. Luna uses the already installed OMP SDK and model login, exact gpt-6-luna/low, `restrictToolNames: true`, an empty tool list and `enableMCP: false`. No new auth profile or connection is created.

## 1. Enter accepted work

1. Ensure the companion after create/reuse: `wt linear -- ensure`. A switch/bootstrap alone never creates an issue. Do not install dependencies, run a model or write Linear from a Worktrunk hook.
2. Read `wt linear -- status`; if not entered, prepare `.superpowers/linear/intake.json`: `{"work_id":"stable-work-name","owner_requests":["accepted request and relevant correction"],"outcomes":[{"id":"stable-id","text":"accepted independent result"}]}`. Derive outcomes from the owner's actual request, not every code edit. Then `wt linear -- enter --input <intake.json>`.
3. For continuation use the same work_id. `status --pending` lists known issue/MR bindings for recovery; do not rediscover the entire backlog. Changing the accepted request invalidates the old approval. IDs retain meaning when reordered; semantic changes invalidate readiness for that outcome.
4. Before creating: use an explicit issue if supplied, then the saved binding, then scoped `list_issues` in FRONT. A matching title alone is not proof of identity. Preserve an existing task-specific project; do not put every task into a generic project. No clear match means main resolves it before any create. Do not invent a successful lookup.
5. Read `/home/q/.omp/agent/linear-identity.json` once per task; use cached workspace/user IDs only where required. One `whoami` refreshes a missing/invalid cache or an explicitly changed connection/account or confirmed identity mismatch. New sessions, compaction and age do not invalidate it; no TTL or routine identity discovery. Ordinary JSON/not-found/401/403 errors are not proof of a changed identity: diagnose access/auth instead of a discovery loop. Store only factual connection/workspace/user, no secrets.
6. New cards use the helper's `assignee: "me"`. Existing cards retain their assignee, including an empty assignee; do not bulk-reassign them. An identity refresh does not authorize moving issues or writing in a different workspace.

## 2. Draft in parallel

Run `wt linear -- editor`. For asynchronous operation use the normal bash async channel with `timeout: 0`; the shared guard uses `--runtime 0` for this managed agent. Completion, explicit cancellation or failure ends the editor, not elapsed working time. Admission, transport and teardown remain bounded independently; goal/grant expiry is not extended. The editor uses exact Luna low, bounded input and no tools. Main continues independent coding/planning. Keep one logical editor per task.

Output gives the draft/receipt paths. Check actual receipt and returned draft, not model self-identification. `outcomes[].id` is private coverage; it must match the accepted set exactly. A later owner correction requires the current input and a new draft/review. Never publish stale scope.

## 3. Public writing rules

- Short title. Description ONLY `- [ ] Result` or `- [x] Result`, one flat line per independent result. No headings, paragraphs, nested lists, extra acceptance/report sections or repeated title.
- Use the owner's language and concrete effect. Small changes can share one card. Do not create one issue/project per checkbox, worktree or session.
- No comments/workpad/start/finish/blocker/test/delivery report, even when done. No automatic project updates. Technical evidence stays in the existing local plan and direct owner response.
- No auxiliary refactor/testing/review/push chores in the checklist unless explicitly requested as standalone outcomes. Preserve-behavior constraints are normally internal conditions, not extra tasks.
- Real scope changes can change the list. Unchanged scope/checks/status means no write. Do not casually rewrite existing text or touch manual metadata.

## 4. Final semantic sync and exact MCP write

1. Main verifies every accepted result is represented, no auxiliary result was invented, and important constraints were not lost. The short private ID→outcome map is not published.
2. Read the bound/candidate issue through MCP. Save only needed fields to a local JSON snapshot: `id,uuid,title,description,status,teamId`. Manual Linear content, status and checkbox changes outrank stale local snapshots/readiness. If the helper detects a conflict, preserve the remote values during main reconciliation; never reset/delete the saved snapshot, omit `--current`, regenerate unchecked text or change status merely to bypass the refusal. A manual tick is the owner's tracker decision, not fabricated code/test/merge evidence. Reversing a manual change requires the owner's explicit instruction.
3. `wt linear -- plan --draft <draft.json> [--current <issue.json>] [--state Todo|In\ Progress|In\ Review] [--ready <outcome-id> ...] --output <plan.json>`. Omit current only after successful duplicate resolution for a genuinely new card. `--ready` is main's confirmation of required checks/results on the actual source, not Luna's opinion. Local readiness alone never ticks a box.
4. Main inspects exact desired title/checklist/status and arguments. `wt linear -- approve --plan <plan.json>` records that exact payload and source revision.
5. Immediately re-read the issue, then `wt linear -- send --plan <plan.json> [--current <fresh-issue.json>]`. Invoke the returned `mcp__linear_save_issue` with exactly its arguments, including the create-only `assignee: "me"`. Do not add comments, labels, assignments on updates, projects or links. Update descriptions with the returned atomic exact-anchor patch, not a blind whole-body overwrite. MCP does not provide a general multi-field compare-and-set; do not claim arbitrary concurrent mutations are impossible.
6. Fetch actual `get_issue` read-back into JSON and run `wt linear -- confirm --current <readback.json>`. Only a matching read-back completes sync. If send returns no_op, do not call save_issue. Unknown write outcome remains pending; reconcile by reading/searching before any retry, especially after create.

## 5. MR and Deployment

- After actual MR creation, bind the exact source and covered outcome IDs: `wt linear -- mr --mr <iid> --outcome <id> ...`. This reads through guarded `wt mr view`, not native Linear–GitLab integration. An open MR is not delivery; use In Review only for actual submitted review, not an internal model review.
- At final sync, after authorized merge, and on resume of a task with pending MRs run `wt linear -- observe [--work-id <known-id>]`. It reads matching MR state, fetches dev and verifies the result SHA's ancestry. Squash result SHA is supported. It never merges, deletes refs or writes Linear.
- Automatic completion requires a ready outcome corresponding to the confirmed delivered source. Partial integration ticks only its IDs. All active results ready and in dev → Deployment. These rules do not override manual Linear checkboxes or status; preserve them when they conflict with local derivation, including Done/QA or a manual reopening/uncheck. Never infer Done, QA or production deployment from local evidence. Re-read/plan/approve/send/confirm the derived update; unchanged results do not need another editor call.
- A skill cannot receive a merge event after OMP exits. A manual external merge is reconciled at the next active p2p sync. No hidden daemon or background polling. Preserve pending bindings beyond worktree deletion.

## Failure modes

| Symptom | Action |
| --- | --- |
| MCP unavailable | Keep local pending sync and continue independent development; never claim Linear is current |
| Unknown result of create/update | Read/search and confirm actual result; do not repeat the mutation blindly |
| Duplicate candidates | Main resolves identity; no speculative create |
| Manual body/state or stale draft | Preserve remote content; reconcile with main before a new approved patch |
| Source changed after approval | Generate/review a current plan; old approval cannot publish |
| Editor/provider/guard failure | Keep evidence and classify; no silent fallback or infrastructure retry |
| No merge/readiness evidence | Keep relevant boxes unchecked; no Deployment |

## Scripts

| Absolute path | Purpose |
| --- | --- |
| `/home/q/.config/worktrunk/projects/p2p-frontend/linear_workflow.py` | Enter, restore, draft, plan, approve, prepare exact MCP payload, confirm and observe MR |
| `/home/q/.config/worktrunk/projects/p2p-frontend/linear-editor.md` | Bounded Luna editorial contract, loaded by helper |
| `/home/q/.config/worktrunk/projects/p2p-frontend/linear_editor.mjs` | Restricted session on the installed OMP SDK; checks actual empty tool inventory before dispatch |

## Session mistakes

The earlier proposal added progress comments and technical reports; those are superseded. A Luna trial invented a preservation checkbox and confused outcome IDs. Exact accepted IDs and main semantic sync are mandatory. MCP access in a child is not assumed; main owns MCP calls.

Native CLI `--no-tools` disables built-ins but does not disable MCP discovery. Do not substitute it for the restricted SDK session. The editor must return a host capability receipt with zero registered tools and MCP disabled; a quiet transcript alone is not proof.

Self-check: correct p2p work item, no duplicate, only outcome checkboxes, no comments, no unsupported ticks, current main-approved bytes, actual read-back. Tests/runtime/delivery remain separate from tracker sync.
