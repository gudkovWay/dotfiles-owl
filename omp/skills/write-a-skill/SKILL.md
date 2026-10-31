---
name: write-a-skill
description: "Use when asked to create, improve, or audit a skill - OMP-global, cross-harness global, or project-local. Picks the right install root so a project skill never lands in a global one, and decides how spawned agents reach it: nothing, autoload, or a rule."
---

# Writing a Skill

A skill wrangles determinism out of a stochastic system. The root virtue is **predictability** -
the agent taking the same *process* every run. Phases gate each other; the Craft section is what
makes the result actually good. (Craft vocabulary adapted from Matt Pocock's writing-great-skills.)

## HARD GATE

- Phase 0 before a single line of content: the root is chosen first, and a project skill never
  lands in a global root.
- NEVER hand-write into `~/.omp/agent/managed-skills/` (see Phase 0).
- The `description` says WHEN the skill fires, never WHAT it contains - the skills list is the
  router, and a skill that never fires does not exist.
- An install is finished only after a session restart proves discovery (Phase 4, step 4).
- Scope boundary: this skill owns authoring, install and audit. Only for an explicitly
  requested skill evaluation, read the cold reference at
  `/home/q/.agents/shared/anthropics-skills/skills/skill-creator/SKILL.md` after checking
  that it exists. It is not a globally discovered skill or a required authoring stage.

## Phase 0 - Scope: which root?
Decide the blast radius FIRST — it fixes WHERE the skill lives and HOW it installs. Three roots, never mixed:

- **OMP-global** — `~/.omp/agent/skills/<name>/`. Reusable across ALL your work but meaningful only inside OMP: it leans on OMP tools (`task`, `hub`, `xd://`, `skill://`), OMP paths, or OMP-only concepts. Provider `native`, priority 100 - the highest, nothing shadows it.
- **Cross-harness global** — `~/.agents/skills/<name>/`. Reusable AND harness-agnostic: plain files, shell, git, personal storage layout. One copy is read by OMP (provider `agents`, priority 70), Claude Code, Codex and opencode. Pick this when the skill must also work in a session that is not OMP.
- **Local (project)** — `<repo>/.omp/skills/<name>/`. Tied to ONE repo; meaningless outside it (a project's deploy workflow, its bespoke conventions, its repo-specific tooling). Scanned for every ancestor of the cwd up to the repo root/home boundary.

Two tests, in order:
1. "If this repo vanished, would the skill still mean anything?" No → local, stop here.
2. "Does it call OMP-only tools or OMP-only paths?" Yes → OMP-global. No → cross-harness global.

One name, one root. Dedup is by skill name and the first match wins by provider priority, so the same name in two roots is a silent shadow, never a fallback.

**NEVER hand-write into `~/.omp/agent/managed-skills/`.** That is the `omp-managed` auto-learn root: priority 5, dead last, always deferring to a same-named skill from any other root. Its only writer, the `manage_skill` tool, exists solely when `autolearn.enabled = true`, emits a lone `SKILL.md` with tool-generated frontmatter, and cannot create `scripts/` - unusable for any skill that ships files.

## Phase 1 - Understand
1. Read external docs (web_search + context7). Never rely on memory.
2. Live-enumerate the system. Docs lie, live state is truth. Cross-check: every running service has a skill entry.
3. Read all skills touching this domain. Fix contradictions before adding new ones.
4. List dangerous ops (widest blast radius) and repetitive ops (done manually several×/week).

## Phase 2 - Experiment
1. Scout scripts first (read-only, safe anytime). JSON via `jq -n` (bash) or `json.dumps` (python). `set -uo pipefail`, never `-e`. Must work degraded - every field populated or null.
2. Test scouts live in degraded state. No silent omissions.
3. Action scripts second: backup -> mutate -> verify -> rollback. NEVER auto-restart services (print "run X to apply"). Restart-capable = HARD GATE marker. Must have `--dry-run` or read-only equivalent.
4. Test actions: `bash -n` isn't enough. Test dry-run, rollback, degraded.

Conventions: `scripts/` subdir; scout = `scout-` prefix, never mutates; action = descriptive verb; pick the right language (bash+jq for SSH/parse, python for API/complex); JSON to stdout only.

## Phase 3 - Write SKILL.md
**Operational rules, NOT reference.** Required frontmatter (name + **trigger-first description**: answers "when do I reach for this skill?", not "what is it"). Required sections: HARD GATE · Current state (dated table; a single dated line suffices for procedural skills) · Failure modes (symptom->cause->fix) · Session mistakes (ALWAYS present, empty = none yet) · Scripts table. Budget: 150 lines. Over budget, first push reference behind pointers or split by branch; if the body genuinely stays longer, its Current state MUST carry the line `[OVERSIZE: <n> lines - <reason the content cannot be split>]`. An untagged over-budget skill is sprawl, not an exception.

## Phase 4 - Install (path follows Phase 0)
One procedure for all three roots - `write` the files yourself, no tool installs them:
1. `write` the SKILL.md, frontmatter `name:`+`description:` inline, to `<root>/<name>/SKILL.md`.
2. `write` the scripts to `<root>/<name>/scripts/`, then `chmod +x`.
3. Discovery runs at session start ONLY. `read skill://<name>` answering `Unknown skill` right after install is expected, not a bug - restart the session.
4. Smoke AFTER the restart: `read skill://<name>` returns the body and the name is present in the system-prompt skills list. An install is not done until this passes.

## Phase 4.5 - Spawn binding
Subagents are NOT blank: a child session carries over the workspace tree, the skills list and
the context files - only conversation history is lost. So a skill needs no mirror copy; it needs
a decision about how a spawned agent reaches it. Pick exactly one, right after install:

1. **Nothing** (default). The skill is in the skills list of every child session; a
   trigger-first `description` is the whole routing mechanism. Correct for anything the agent
   picks up situationally.
2. **Autoload into an agent.** The skill is a procedure a given agent must follow on EVERY run
   (worker regulations, a lane's format). Add its name to `autoloadSkills` in
   `~/.omp/agent/agents/<agent>.md`; the body is injected before the child's first prompt.
   Unknown names are ignored silently - verify the spelling against the skills list.
3. **Promote to a rule.** The content is not a procedure to reach for but a law that must ride
   every turn. Write `~/.omp/agent/rules/<name>.md` with `alwaysApply: true` and target it with
   `agents:` (`main` for the orchestrator only, `["flash*"]` for the worker pool, omit for all).
   A rule costs context on every request - use it only for laws, never for reference.

Never duplicate a skill's body into a rule or a second file: one authoritative place per
meaning. If a rule must point at a skill, it points with `skill://<name>`, it does not copy.

## Research preservation
When the user ran research and asks to keep it (e.g. "сохрани ресерч", "положи в скилл"), and the topic maps to an existing skill:
- Update that skill or create a `researches/` folder inside it; add ONE pointer line in SKILL.md naming the folder; write an index `researches/README.md` (topic table, `NN-topic.md` files).
- SKILL.md states that research exists (pointer), so future work loads the fact sheet instead of re-searching.

Research files are a HARD GATE distillate:
- Dry facts only: one fact = one verbatim quote from one source; no opinions, conclusions, or recommendations.
- Authority stated explicitly per claim (official vendor / community measurement / aggregator); extrapolations marked as such.
- SEO/scam/spam sources never enter; fabricated or unverifiable facts never enter (mark [unverified]/[estimate] or omit).

## Craft - what makes a skill predictable
**Invocation = the description - say WHEN, not WHAT.** OMP surfaces every skill's description in the system-prompt skills list - that list IS the router. The description MUST answer "when do I reach for this skill?" - NOT "what does this skill contain?". Lead with the trigger (the situation that makes the agent pick this skill); follow with a compact hint of what it covers. BAD: `Audit and control the metamio dev stand` (describes WHAT). GOOD: `Use when the stand is down or needs bringing up, after a reboot, or to free ports + RAM` (says WHEN). Do NOT build a router skill; one trigger per branch (synonyms renaming one branch are *duplication* - collapse them); cut identity already in the body.

**Completion criteria.** Each step ends on a checkable, and where it matters *exhaustive*, condition ("every modified file accounted for", not "produce a change list"). A vague criterion invites *premature completion*.

**Information hierarchy.** In-skill step (ordered action) > in-skill reference (on-demand fact) > external reference (linked file, loaded by pointer). Push down via *progressive disclosure* only when the top bloats; keep a concept's definition + rules + caveats *co-located*.

**Leading words.** A compact pretrained concept (_tight_ loop, _red_ signal, _relentless_) anchors a region of behaviour in the fewest tokens and sharpens invocation when the same word recurs in prompts/docs. Collapse restatements into one leading word.

**Single source of truth.** One authoritative place per meaning - a one-place edit.

**Absolute paths.** State every script's absolute path — `~/.omp/agent/skills/<name>/scripts/<script>` (OMP-global), `~/.agents/skills/<name>/scripts/<script>` (cross-harness) or `<repo>/.omp/skills/<name>/scripts/<script>` (local) — both in the Scripts table and in a prominent line near the top of the body. The agent invokes it directly; it never searches, computes, or guesses the path. A relative `scripts/foo` in a skill body is a bug.

**Artifact-producing procedures.** Encode a standing rule as an ordered procedure that ends in a forced observable artifact - a one-line decision record, a filled template, a checklist the session must contain. Advice without output is ignored under load; artifacts are checkable by the model itself (self-check) and by the user. This sharpens the no-op test: a rule that produces no output is a no-op.

**Escape valves.** An absolute rule with no listed exceptions trains the model to rationalize ignoring it (it "knows" *always* can't be true). Ship exception tags/conditions with the rule and require the tag to be stated explicitly when invoked. No tag = no exception.

**Top-and-tail the load-bearing rule.** HARD GATE as the first line of the body; echo the check as the final line ("self-check before yielding: ..."). Conflicting instructions resolve toward the ends of the context - occupy both ends with the same rule.

**Dated catalogs verify at use.** Any list of named tools/libraries/formats carries "defaults; verify currency at use time" - catalogs age silently and a stale catalog is worse than none.

## Failure modes (diagnose a struggling skill)
- **Premature completion** - step ends before genuinely done; attention slips to "being done". Fix: sharpen the completion criterion first (cheap, local); only if irreducibly fuzzy *and* you observe the rush, split the sequence.
- **Duplication** - same meaning in >1 place. Collapse to one source.
- **Trigger collision** - two or more skills claim the same situation. Name-based dedup does
  NOT collapse them: different names all stay in the list and the router picks by description.
  Resolve by procedure, never by reflex: grep the other skill roots for inbound references to
  the duplicate (session logs excluded); none -> filter it via `skills.ignoredSkills` in
  `~/.omp/agent/config.yml` (files stay on disk, only discovery is cut); references exist ->
  filtering dangles them, so keep it loaded and resolve precedence IN TEXT in your own skill,
  stating which repo or condition makes yours win and that the foreign pointers are to be read
  as pointers to yours. If the duplicate owns a capability yours lacks, split the meaning
  instead of the skill and name the boundary in both journals.
- **Sediment** - stale layers nobody prunes; the default fate without a pruning habit.
- **Sprawl** - too long even if every line is live. Cure: disclose reference behind pointers, split by branch/sequence.
- **No-op** - a line the model obeys by default. Test: does it change behaviour vs the default? If not, delete the whole sentence.
- **Trigger miss** - the skill exists but did not fire in the situation it was written for. The description lacks the situation's leading words; rewrite the description from the observed miss, do not pile up synonyms.

## Scripts

None - this skill is pure procedure. A skill of your own that ships helpers states their
absolute paths here (see Craft, "Absolute paths").

## Current state

| Date | Note |
|---|---|
| 2026-10-31 | OMP-global authoring remains here. Anthropic evaluation tooling is a cold, task-specific reference; Superpowers orchestration is not part of OMP's active workflow. Native discovery in a separate new session proves installation without restarting the owner's live process. |

## Session mistakes

None yet.

Self-check before yielding: the root was chosen in Phase 0 and matches where the files actually
landed; the `description` states a trigger; discovery was proven after a restart.
