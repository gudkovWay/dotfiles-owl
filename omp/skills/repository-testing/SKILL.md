---
name: repository-testing
description: "Use when implementing or changing behavior, updating existing tests, choosing a repository test command, or running project tests in OMP. Determine the current repo's native test stack and smallest relevant run; do not invent a runner or a smoke script."
---

# Repository-aware testing

## HARD GATE

Read `rule://no-autotests` and `rule://heavy-jobs-resource-guard` before deciding what to write or run. These rules own authorization and host limits. This skill owns repository discovery and test selection, not another set of resource limits.

OMP-global root: `/home/q/.omp/agent/skills/repository-testing/`. No helper scripts or installation step in a repository.

## Current state

2026-10-08: task-driven readiness, targeted preparation and finite UI profiles. Native tests remain authoritative; no full suite/build on every edit. Verify profile currency against the worktree manifest/CI before use.

## 1. Discover the actual test contract

1. Resolve the target repository/worktree and changed behavior. Do not use the session's original cwd when work is in another worktree.
2. Use `glob` to locate manifests, lockfiles, runner configs, existing tests, workspace definitions and CI workflows. Read only relevant sections. Do not search for extra agent/context files.
3. Follow the existing authoritative entrypoint: package/task script, Make target, language manifest or CI command. Read nested scripts and pre/post hooks before executing them; a command named `test` may install dependencies, prepare/build apps, start services or launch multiple suites.
4. Identify the package manager and locally installed runner/version from the manifest, lockfile and available environment. No network-resolving `npx`, auto-installing `uv`, package-manager bootstrap or alternate runner as a convenience.
5. Record required cwd, configuration/root, setup fixtures, environment variables, variants and service dependencies. Existing examples and configuration outrank a generic command table.
6. If no test stack is configured, report `no configured test stack`. Do not install one or copy another repo's conventions without approval.

End condition: each affected behavior has an identified test home/entrypoint, or a named missing prerequisite.

## Readiness follows the proof

- CSS/geometry/focus: exercise the changed screen in a real browser; happy-dom
  or asserting class names is not layout evidence. Logic/money/permissions:
  retain relevant native regressions; a screenshot is not a contract test.
- For bounded fixes, no separate plan file or repeated approval of explicit
  “fix it”. Record the chosen proof briefly in chat.
- p2p/ecom: `/home/q/.config/worktrunk/projects/project-environment` is read-only
  by default (`wt env -- --profile admin-ui|admin-tests`). p2p admin tests need
  common + admin prepare; UI needs common + admin + the selected app prepare.
  This three-root dev prerequisite was observed on p2p; it is not a full layer build.
- `--install --prepare` materializes only missing/stale prerequisites under
  the shared guard. Respect rule://no-autotests and scoped user refusals.
  Reuse ready owned environments; never share writable generated output.
- ecom `admin-ui` uses its own backend. `admin-tests` is intentionally refused
  until its native test entrypoint is established; do not borrow p2p scripts.
- Installed `node_modules` without matching lockfile/Node/workspace evidence
  is unverified, not ready. No arbitrary reflink/copy fallback.
- Production build and Nuxt dev are different routes. Confirm the smallest
  working profile once; keep required steps, do not guess them away.
- `wt ui -- --seconds 480` запускает конечный headless профиль payscrow-admin:
  server + Chromium + private HOME/XDG/bus в общем scope. Подключить browser API
  только к напечатанному `app.cdp_url`, не к личному relay/default managed browser.
  Записать напечатанный stop_file, закрыть owned tabs и дождаться teardown
  до другой тяжёлой проверки. `--dry-run` только показывает профиль.
  При CDP attach явно применить `tab.emulate({viewport: ...})` и сверить
  observe/geometry: initial open viewport при attach может не примениться.
  Ожидать реальный screen selector, а не networkidle в dev/HMR приложении.
- Пользовательский URL p2p dev — `http://localhost:<port>`, хотя owned listener
  привязан к 127.0.0.1. Backend preflight допускает localhost:3000, но не
  127.0.0.1:3000. Для другого порта проверять CORS, не отключать browser security
  и не считать сетевой отказ доказательством неверного пароля.
- Launcher readiness не доказывает экран: нужен конкретный сценарий, geometry,
  screenshot, console/network evidence и HMR после изменения. Без тестового
  доступа к защищённому экрану — именно этот экран `unverified`, без auth bypass.
- `wt ui -- --capture --seconds 480` — синхронный finite capture входной страницы
  без авторизации. Проверить screenshot/DOM на error overlay или пустой экран:
  Chromium exit 0 сам по себе не доказывает рендер. Такой capture не проверяет
  защищённый History, mobile details, tooltip или HMR.
- Для интерактивной dev/HMR проверки предпочитать CDP-профиль без `--capture`:
  ecom CLI capture упёрся в 120s timeout, тогда как owned CDP позволил увидеть
  login, desktop/mobile geometry и focus. Точная причина CLI timeout неизвестна;
  не повторять его вслепую и не объявлять общий capture надёжным для всех apps.
- При наличии `jev_context` обновить bounded срез результатов/блокера из
  фактического отчёта. Agent-reported claim не становится независимым proof;
  разрешения и caps остаются в правилах, а требования — в текущем todo/плане.


## 2. Write the relevant tests

1. For a new feature, cover its consumer-visible behavior and meaningful boundary/error cases. For a bugfix, encode the regression. For an existing feature, update the existing relevant tests and fixtures when its contract changes.
2. Reuse the repo's runner, fixtures, isolation and naming. Do not add parallel test infrastructure, giant datasets, performance tests or artificial stress loops.
3. Name the production defect each test would detect. Assert outputs, state transitions and observable side effects, not source text, mock echoes or incidental wiring. Keep tests deterministic and safe for the repository suite.
4. Do not weaken assertions, skip failing cases or automatically accept snapshots to make a run green. Keep real test assertions separate from test-adapter migration.
5. In a delegated batch, workers write tests but do not run them. Give test-file ownership explicitly; the orchestrator integrates and executes the combined relevant set once after the batch.
6. TDD/verification skills remain subordinate to the two rules. If execution is blocked, retain useful test/code changes and report them unverified; do not delete the implementation to satisfy a red-first ritual.

End condition: changed behavior has relevant tests or an explicit reason why none are applicable/configurable, not a blanket claim that tests are forbidden.

## 3. Select a finite, narrow run

1. Map changed behavior to exact test files/cases and required configuration variants. Include directly affected existing tests; do not silently skip a required variant or change the environment being tested.
2. Choose the smallest authoritative entrypoint which accepts that selection. A broad composite command may not forward a file filter to its children: use its existing leaf entrypoints, preserving their environment/configuration, and run them sequentially.
3. Keep the repo's command and append only supported one-shot, filter and concurrency arguments. Verify options in installed-version help/docs before use; never guess flags for an unfamiliar runner.
4. Default to one worker and serial test execution where the runner supports it, and disable automatic retries. Never change the runner's process pool or substitute a DOM/runtime environment to reduce memory after a failure.
5. Full-suite, coverage, watch/UI/debug, snapshot acceptance, stress and benchmark modes are not a default scoped run; apply the authorization rule instead of expanding scope silently.
6. Repository-managed local headless E2E is eligible only if all server/setup processes stay in the guarded cgroup, use an isolated test environment and cannot affect production or the live desktop. Inspect `webServer`, setup/teardown and nested commands first. Do not reuse a live shared server or a remote browser/container daemon outside the cap.
7. If the entrypoint cannot express a relevant bounded selection, or escapes the guarded cgroup, stop and report the exact blocker. Do not invent a temporary verifier.

Illustrations, not a fixed allowlist:

| Detected native runner | Selection/concurrency approach; verify installed version |
|---|---|
| Vitest | Existing script + file/case filter, `run`, `--maxWorkers=1 --no-file-parallelism --maxConcurrency=1 --retry=0` when supported |
| Playwright Test | Existing script + file/title/project filter, headless, `--workers=1 --retries=0`; no UI/debug server |
| Jest | Existing script + test-path/name filter, `--runInBand`; no watch/coverage |
| pytest/unittest | Existing repo command + file/node-id or test module; no xdist/multiprocess fanout |
| Cargo/Go/other stacks | Existing manifest/CI command + native test filter; bound build/test concurrency using that tool's documented flags |

End condition: a command matrix covers the relevant behavior and variants without invoking unrelated suites.

## 4. Guard, execute, report

1. Read and follow `rule://heavy-jobs-resource-guard` exactly: preflight, shared lock, synchronous capped scope and fail-closed behavior. Use its canonical command template; do not duplicate or relax limits here.
2. Select readiness before invoking a runner. Use only the task-authorized, reviewed install/prepare profile; preserve tracked config. Unreviewed lifecycle, new dependencies, full build/typecheck or browser install require a separate decision.
3. Execute the selected command in the resolved worktree. Preserve actual exit code and output. Report no-tests-found as missing coverage, not success.
4. After ordinary assertion failures, fix the cause within scope and rerun only the affected set under the same limits. Resource/bootstrap failures use the rule's fail-fast branch, not this loop.
5. Check owned scope teardown before another run; never kill foreign services or erase the lock. Default busy refusal; bounded synchronous lock waiting only via the resource rule, no hidden queue.
6. Test results prove only exercised scenarios. Tests passing do not establish desktop rendering, native browser unload or every API failure path. Separate test evidence from unexercised runtime/UI surfaces.

Required decision record in the conversation/report (no repository docs required):

- Repository/worktree and changed behavior.
- Test files/fixtures written or updated, or why not applicable.
- Discovered entrypoint, configuration/variants and exact filtered command(s).
- Guard/preflight outcome; actual exit code and test counts, or `unverified` with the blocker.
- Remaining runtime/UI limits; no claim that resource caps prevent every kernel/driver failure.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| No command/config/tests found | Repo has no established test stack | Report prerequisite; do not install a runner |
| A file filter runs everything | Composite script/root/filter mismatch | Inspect native leaf command before running; do not guess |
| Worker wants to run red/green | TDD conflicts with batch ownership | Worker writes; orchestrator runs after integration |
| OOM, scope/setup failure, timeout or tracked config mutation | Guard/environment blocker | Stop this attempt, preserve unrelated edits, report; no cosmetic retries |
| Normal assertion failure | Behavior or test contract defect | Fix cause and rerun the narrow set with unchanged limits |
| Scope/lock busy | Another host workload exists | Report conflict; do not start another heavy job |

## Session mistakes

- 2026-10-07: the old rule was interpreted as forbidding new tests because it explicitly did. Separate authoring permission from execution and resource safety; do not copy old “no tests” boilerplate into worker briefs.

## Scripts

Shared launcher: `/home/q/.config/worktrunk/projects/guarded-run -- <native command>`.
Environment profile: `/home/q/.config/worktrunk/projects/project-environment`.
Finite UI supervisor: `/home/q/.config/worktrunk/projects/ui-session` (`wt ui`).
No custom test runner, repository installation or load generator.

Self-check before yielding: every changed behavior is accounted for; the native command is discovered, not guessed; any run obeyed both rules; evidence and unverified surfaces are reported separately.
