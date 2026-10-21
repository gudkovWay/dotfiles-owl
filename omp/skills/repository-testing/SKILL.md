---
name: repository-testing
description: "Use when implementing or changing behavior, updating tests, selecting or running native tests or local typecheck, or preparing verification for delivery in OMP. Discover the repository's test stack and affected CI typecheck projects; do not invent a runner or smoke script."
---

# Repository-aware testing

## HARD GATE

Read `rule://no-autotests` and `rule://heavy-jobs-resource-guard` before deciding what to write or run. These rules own authorization and host limits. This skill owns repository discovery and test/typecheck selection, not another set of resource limits.

OMP-global root: `/home/q/.omp/agent/skills/repository-testing/`. No helper scripts or installation step in a repository.

## Current state

2026-10-21: p2p dev/UI reuses ready inputs or prepares audited missing prerequisites in one capped/exclusive scope; native test profiles cover common/admin/form/merchant/provider. Minimal DEV grants use the exact test account, existing UI and persisted-state verification below. Ecom retains explicit preparation. Local typecheck keeps its fixed-budget native CI profile. [OVERSIZE: 249 lines - native discovery, typecheck, readiness, credentials, DEV grants and UI isolation form one verification contract]

## 1. Discover the actual test contract

1. Resolve the target repository/worktree and changed behavior. Do not use the session's original cwd when work is in another worktree.
2. Use `glob` to locate manifests, lockfiles, runner configs, existing tests, workspace definitions and CI workflows. Read only relevant sections. Do not search for extra agent/context files.
3. Follow the existing authoritative entrypoint: package/task script, Make target, language manifest or CI command. Read nested scripts and pre/post hooks before executing them; a command named `test` may install dependencies, prepare/build apps, start services or launch multiple suites.
4. Identify the package manager and locally installed runner/version from the manifest, lockfile and available environment. No network-resolving `npx`, auto-installing `uv`, package-manager bootstrap or alternate runner as a convenience.
5. Record required cwd, configuration/root, setup fixtures, environment variables, variants and service dependencies. Existing examples and configuration outrank a generic command table.
6. If no test stack is configured, report `no configured test stack`. Do not install one or copy another repo's conventions without approval.

End condition: each affected behavior has an identified test home/entrypoint; changed typed inputs have identified typecheck projects/entrypoints, or a named missing prerequisite.

## Readiness follows the proof

- CSS/geometry/focus: exercise the changed screen in a real browser; happy-dom
  or asserting class names is not layout evidence. Logic/money/permissions:
  retain relevant native regressions; a screenshot is not a contract test.
- For bounded fixes, no separate plan file or repeated approval of explicit
  “fix it”. Record the chosen proof briefly in chat.
- p2p/ecom: `/home/q/.config/worktrunk/projects/project-environment` is read-only
  by default (`wt env -- --profile admin-ui|admin-tests`). p2p admin tests need
  common + admin prepare; p2p UI needs common + selected role + selected app prepare.
  This three-root dev prerequisite was observed on p2p; it is not a full layer build.
- `--install --prepare` materializes only missing/stale prerequisites under
  the shared guard; per-root stamps reuse common/admin across profiles.
  Readiness checks every required output, including the app ESLint config.
  Test-ready is not hook-ready: p2p uses strict `wt commit` or an explicitly
  installed batch mode (`wt batch -- begin`, atomic commits, cumulative
  `verify`, checked fixes and cheap `check`), see starting-worktree-work §6b.
  Hook proof is not native-test/typecheck/UI/CI proof. Run affected checks after
  autofix on final content; no heavy verification on every atomic commit.
  No full build or shared writable output.
- Лимиты local jobs и общий adaptive RAM/CPU budget задаёт только
  `rule://heavy-jobs-resource-guard`; число детей — отдельный лимит.
  Environment mutation claims the canonical worktree for the whole scope;
  readiness is refreshed after admission. Native test runners stay serial,
  and batch children do not run integrated tests or typecheck. Scoped tool
  bootstrap/build permission is not test permission.
- ecom `admin-ui` uses its own backend. `admin-tests` is intentionally refused
  until its native test entrypoint is established; do not borrow p2p scripts.
- Installed `node_modules` without matching lockfile/Node/workspace evidence
  is unverified, not ready. No arbitrary reflink/copy fallback.
- Production build and Nuxt dev are different routes. Confirm the smallest
  working profile once; keep required steps, do not guess them away.
- `wt ui -- --app payscrow-admin --seconds 480` запускает конечный headless профиль;
  `--app payscrow-merchant|payscrow-provider` выбирает другое p2p-приложение.
  Без `--app` остаётся admin; ecom поддерживает только admin и не использует p2p-секреты.
  Readiness/prepare: `wt env -- --profile admin-ui|merchant-ui|provider-ui`;
  каждый UI-профиль готовит common + слой роли + выбранное приложение.
  `wt ui` и `wt dev -- --app=payscrow-admin` автоматически переиспользуют готовое
  окружение или выполняют только недостающие audited install/prepare перед
  запуском, в одном guarded/exclusive scope. Для merchant/provider выбрать
  соответствующее приложение. Создание worktree не запускает подготовку.
  Не запускать голый `npm ci` или `npm run dev` мимо этих entrypoints.
  Это reviewed owned headless профиль проверки UI-исправления по
  `rule://no-autotests`, а не ручной запуск личного desktop; sandbox/caps и
  проверка backend/fixture обязательны. Отдельный dev server вне профиля
  и видимые окна этим не разрешаются.
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
- Авторизация p2p: источник ровно `/home/q/.secrets/<app>` —
  `payscrow-admin`, `payscrow-merchant`, `payscrow-provider`. Каталог `0700`,
  файл `0600`, принадлежат пользователю, без symlink. UTF-8, ровно две
  непустые строки: логин, затем пароль; конечный перевод строки допустим.
  Пустые файлы созданы для заполнения владельцем: не подставлять буквальные
  `login`/`password`, не перезаписывать существующую учётку.
  Launcher проверяет файл и выводит только `authentication.credentials_file`,
  `state` (`ready`/`empty`/`missing`) и флоу, никогда сами значения.
  `ready` означает только корректный формат, не проверенный пароль.
  До заявления «нет тестового доступа» проверить этот источник через `wt ui -- --dry-run`.
  После attach читать файл внутри локального eval без print/display/log,
  передавать строки непосредственно в browser fill `#username` и `#password`,
  нажать кнопку «Войти» один раз и дождаться ухода с `/login` И целевого
  screen selector. Не читать секрет через `read`/shell cat, не вставлять
  значения литералами в tool arguments, чат, environment или команды.
  Не сохранять auth request bodies, cookies, tokens, input values и DOM
  заполненной формы; не снимать скрин до ухода с login. При 2FA назвать
  недостающий второй фактор; при CORS/сети не объявлять пароль неверным.
  Сам launcher НЕ выполняет вход: его выполняет агент в owned CDP-браузере.
  `--capture` остаётся без авторизации. Empty/missing — конкретный prerequisite,
  не повод искать личные cookies или обходить auth.
- `wt ui -- --capture --seconds 480` — синхронный finite capture входной страницы
  без авторизации. Проверить screenshot/DOM на error overlay или пустой экран:
  Chromium exit 0 сам по себе не доказывает рендер. Такой capture не проверяет
  защищённый History, mobile details, tooltip или HMR.
- Для интерактивной dev/HMR проверки предпочитать CDP-профиль без `--capture`:
  ecom CLI capture упёрся в 120s timeout, тогда как owned CDP позволил увидеть
  login, desktop/mobile geometry и focus. Точная причина CLI timeout неизвестна;
  не повторять его вслепую и не объявлять общий capture надёжным для всех apps.
- At task start, use `jev_context` for the existing acceptance and known delivery
  target; update only semantic facts missing from automatic observation.
  Todo results supply fallback criteria/blockers; known readiness/test results
  and commit/ancestry results populate scoped observations automatically.
  Task-branch push is not delivery, and observed tests do not imply verified UI.
  Unknown remains unknown; neither agent claims nor tool text grant permission.

### p2p DEV permissions

Отсутствующее право у тестовой учётки — сначала штатная процедура через UI,
не автоматический запрос владельцу и не повод снимать PermissionGuard.

1. Scope: только backend DEV-стенда, разрешённого для текущей задачи, и учётка
   из `/home/q/.secrets/<app>`. Production, другой пользователь и глобальное
   редактирование пермишена этим не разрешены. Для LK merchant/provider выдачу
   выполнять через admin UI с её отдельными credentials, целевая учётка —
   email именно проверяемого LK, не admin по умолчанию.
2. До записи сверить backend и exact email/UUID/membership выбранного пользователя.
   Email брать приватно из credential source; не печатать пароль, токены или
   содержимое login-формы. Если логин не email, установить email через профиль
   вошедшей учётки; не угадывать пользователя по похожему имени.
3. Из проверяемой фичи определить точные permission keys; в разделе управления
   пользователями/ролями найти пользователя по email, открыть его доступы
   (в новом UI — карточка пользователя, вкладка `#permissions`), найти каждый
   ключ поиском. Доступна старая страница ролей — использовать её штатные controls.
4. Добавить только отсутствующие keys, необходимые сценарию. Не выбирать всё
   дерево, не выдавать wildcard/родительское право вместо точного, не копировать
   чужой полный набор. Не отзывать существующие права и не менять membership.
   Не путать выдачу с EditPermissionModal: active/description/2FA глобальны.
5. Сохранить штатной кнопкой, дождаться подтверждения; заново открыть доступы
   и подтвердить persisted keys. Частичный сбой не является успехом:
   перечитать состояние и не повторять уже подтверждённую выдачу вслепую.
6. Обновить контекст целевой учётки (штатный refresh/relogin при необходимости),
   затем повторить исходный сценарий. Изменение checkbox не доказывает доступ.
7. Отчёт без секретов: backend, приложение, добавленные keys, подтверждение
   сохранения и исходного сценария; user identifier маскировать.

Разовая авторизация задачи включает эти минимальные DEV grants без вопроса
на каждый ключ. Если управляющая учётка не имеет `permission.grand-revoke`,
backend отказал, требуется недоступная 2FA, право не существует/не подходит
membership или нельзя однозначно установить учётку/DEV backend — назвать
конкретный prerequisite. Не подменять отказ API-прямым запросом, auth bypass,
локальным mock доступа, отключением 2FA или изменением глобальной политики.


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

## 3a. Select the native local typecheck

1. Map changed typed code, tests and type-affecting configuration to affected projects using manifests, references and current CI. Check each selected project completely with its native tsconfig/includes; do not substitute a layer-only config or a file list that drops project context or tests.
2. Use the same authoritative entrypoint, flags and error criterion as CI. Shared code can require several or all CI projects; project count alone is not an approval gate. Mandatory relevant local typecheck and corrected reruns are authorized by `rule://no-autotests`; unrelated projects remain out of scope.
3. Compare local and CI Node/tool versions, lockfile, generated inputs and required environment. Reuse a compatible available environment; do not silently change global versions, dependencies or lifecycle. Record differences: the same command alone does not prove identical CI results.
4. Reuse existing prepared outputs. Necessary addressed prepare through an already reviewed profile is part of the authorized typecheck; a full build is not a substitute or automatic prerequisite.
5. Inspect nested scripts: compiler failures must reach the entrypoint's result. A wrapper that drops a nonzero compiler exit or reports zero counted diagnostics after a failed compiler run is a verification defect, not green typecheck. Fix only within the authorized scope; otherwise report the exact blocker.
6. P2P CI uses `./scripts/typecheck-app.sh <app> 0`, with Payscrow admin/form/merchant/provider representatives. Re-read current `.gitlab-ci.yml` and the script before selecting apps; do not replace the selected projects with the broader eight-app root command.
   Local executor: `wt typecheck -- <app>` from the owned worktree; `/home/q/.config/worktrunk/projects/p2p-frontend/typecheck` runs that native script under the shared guard with a fixed 6 GiB maximum, 4 GiB MemoryHigh, environment lock and kernel outcome metrics. It neither installs dependencies nor changes the checked file set. `--dry-run` proves only the plan.
   Avoid the adaptive default for this p2p compiler: historical 600s timeouts stalled near its 2 GiB MemoryHigh; the fixed profile plus corrected router plugin completes without high/oom events. Historical 2048 MiB Node heaps also OOMed. Reserved maximum is not measured usage. Keep OOM, timeout, admission/75 and actual TS diagnostics distinct; none means a source type error without compiler evidence.

End condition: an exact command matrix covers affected CI typecheck projects, with required preparation and any known environment/entrypoint discrepancy recorded.

## 4. Guard, execute, report

1. Read and follow `rule://heavy-jobs-resource-guard`: current memory/registered-job admission, short shared lock, unique capped scope inside the aggregate slice and fail-closed verification. Use the common launcher; do not independently reproduce its budget or caps.
2. Select readiness before invoking a runner/compiler. Use only the task-authorized, reviewed install/prepare profile; preserve tracked config. Addressed prepare for relevant typecheck needs no new approval. Unreviewed lifecycle, new dependencies, full build, unrelated typecheck or browser install require a separate decision.
3. Execute the selected command in the resolved worktree. Preserve actual exit code and output, including compiler status through wrappers. Report no-tests-found as missing coverage, not success.
4. Classify the cause under `rule://no-autotests` §7. Fix assertions, type errors and fixable source/import/transform/fixture/mock configuration errors within scope, then rerun affected checks without another permission question. Resource or infrastructure failures stop the attempt; an error during module loading/prepare is not automatically infrastructure failure.
5. Verify owned scope teardown and reservation release. Busy/75 is bounded deferral before workload, not an instruction to ask the owner to free RAM. Use `--wait 60`; if it expires, report the precise resource blocker without repeated launches or an uncapped fallback. Other registered jobs may continue.
6. Report tests, typecheck, UI/runtime and CI/delivery separately. Tests passing do not prove type correctness, rendering or native unload; green local typecheck does not replace CI of the final SHA. Changed checked inputs, including hook mutations, invalidate the affected prior results.

Required decision record in the conversation/report (no repository docs required):

- Repository/worktree and changed behavior.
- Test files/fixtures written or updated, or why not applicable.
- Discovered test entrypoint/configuration/variants and selected complete typecheck projects; exact commands and CI correspondence.
- Guard/preflight outcome; actual exits and test counts/type diagnostics separately, checked revision/state, or `unverified` with the blocker.
- Environment differences, CI/delivery status and remaining runtime/UI limits; no claim that resource caps prevent every kernel/driver failure.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| No command/config/tests found | Repo has no established test stack | Report prerequisite; do not install a runner |
| A file filter runs everything | Composite script/root/filter mismatch | Inspect native leaf command before running; do not guess |
| Worker wants to run red/green | TDD conflicts with batch ownership | Worker writes; orchestrator runs after integration |
| OOM, infrastructure scope/setup failure, timeout or tracked config mutation | Guard/environment blocker | Stop this attempt, preserve unrelated edits, report; no cosmetic retries |
| Assertions, type errors or fixable source/test-configuration failure | Behavior, types or local test contract defect | Investigate, fix within scope and rerun affected checks with unchanged stack/limits; no new approval |
| Scope/budget/environment busy | Guard cannot admit the job now | Bounded `--wait 60`, then report the specific blocker; no demand to free RAM or hidden retries |

## Session mistakes

- 2026-10-07: the old rule was interpreted as forbidding new tests because it explicitly did. Separate authoring permission from execution and resource safety; do not copy old “no tests” boilerplate into worker briefs.
- 2026-10-09, session `01a12075-9146-77c9-9234-438fb572aab9`: fixable test-module import failures were treated as bootstrap permission gates; green Vitest runs were delivered without initial local typecheck. Distinguish causes and proof types, not command names.

## Scripts

Shared launcher: `/home/q/.config/worktrunk/projects/guarded-run -- <native command>`.
Environment profile: `/home/q/.config/worktrunk/projects/project-environment`.
Finite UI supervisor: `/home/q/.config/worktrunk/projects/ui-session` (`wt ui`).
No custom test runner, repository installation or load generator.

Self-check before yielding: changed behavior and typed inputs are accounted for; native test/typecheck commands and affected CI projects are discovered, not guessed; runs obey both rules; tests, types, runtime and CI evidence are separate; unchecked surfaces remain unverified.
