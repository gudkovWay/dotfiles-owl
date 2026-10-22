---
name: starting-worktree-work
description: Use when choosing a new working branch in any repository; when starting any feature, project, or hotfix work, or any change to feature/project/hotfix code; when publishing a p2p DEV branch or planning its automatic Payscrow stand; when synchronizing branches before commit, push, or MR delivery, including pull, rebase, or a non-fast-forward rejection; when a linked worktree may already exist or an integration DEV-* branch is occupied by a live agent; when the current worktree has uncommitted changes; when writing p2p Nuxt env overrides; when creating a GitLab MR via wt mr or glab; when basing a branch on a release tag.
---

# Worktree-first вход в работу

Прежде чем менять код фичи/проекта/хотфикса — убедись, что ты работаешь в связанном worktree. Worktrunk (pinned 0.77.0) — единственный, кто создаёт и удаляет постоянные linked worktree. Напрямую `mkdir`, `git worktree add` или ручной `cd` в чужой каталог — запрещено.

Перед выбором имени ветки прочитай `/home/q/.omp/agent/rules/branch-naming.md`:
это единая глобальная политика для всех проектов, включая локальные worktree.

## Приоритет над общими скиллами

Триггер «начинаю фичу — нужна изоляция» заявляют ещё два скилла superpowers, и дедуп по
имени их не схлопывает. Правило разрешения:

- `using-git-worktrees` — общий фолбэк «native tools или `git worktree add`». В репозитории,
  где есть worktrunk (`git config --local worktrunk.default-branch` отвечает) или политика
  `DEV-*`, побеждает ЭТОТ скилл: `git worktree add` руками здесь запрещён. Указатели
  «use superpowers:using-git-worktrees» внутри `executing-plans`,
  `subagent-driven-development` и `writing-plans` в таких репозиториях читать как указатель
  сюда.
- `finishing-a-development-branch` — общий разбор «как интегрировать готовую работу». Его
  варианты с локальным merge неприменимы к p2p: там интеграция только через GitLab MR
  (`wt mr` с guard по apiBase, см. §7), `wt merge` не предписывается. Вне p2p его варианты
  законны.

## 1. Определи существующий worktree

1. Сначала проверь текущий linked worktree и его владельца. Последовательные
   уточнения той же задачи/экрана с той же базой и delivery target — продолжение,
   даже если сообщение новое. Оставайся в owned worktree, не создавай новое.
2. `git worktree list` — если подходящего текущего нет, найди целевую ветку.
3. Найден и свободен — переиспользуй `wt switch <branch> --format json`.
4. Занят live-агентом — handoff (§4), не совместное редактирование: индекс и
   генераторы общие даже при разных файлах.
5. Создай новый (§3) только для независимой задачи, другой базы/релиза,
   параллельного владельца или риска смешивания неизвестных изменений.
6. После merge reuse требует чистого owned дерева и безопасной синхронизации;
   не подразумевает rewrite/force-push. Отдельные темы = отдельные коммиты,
   но не обязательно отдельные worktree.

## 2. Разрешение ветки и базы (контракт, порядок точный)

Сначала различи продолжение работы в целевой ветке и новую самостоятельную задачу.

**Продолжение / integration:** разрешай целевую ветку в таком порядке:
1. Явное указание пользователя/агент-контекста.
2. Linear-проект: секция `## Delivery`, поле integration.
3. Legacy: ветка в описании задачи.
4. Единственный кандидат, подтверждённо относящийся к этой задаче.
5. Несколько подходящих кандидатов для этой задачи — уточнить целевую ветку.
   Само наличие нескольких DEV-веток в репо не является неоднозначностью задачи.

**Новая самостоятельная задача:** имя генерируй из темы задачи по глобальной
политике `/home/q/.omp/agent/rules/branch-naming.md`, без отдельного апрува имени.
Не заимствуй постороннюю DEV-ветку и не откладывай owner-префикс до push.
До `wt switch --create` сообщи имя и базу, проверь имя через
`git check-ref-format --branch <branch>` и наличие целевой ветки/worktree;
существующую целевую ветку переиспользуй, не создавай дубликат.

Только для p2p: backend stand выбирается независимо от frontend-ветки.
Явно известный backend stand приоритетен; для frontend-only исправления
по умолчанию `https://api.dev.payscrow-cascade.io`. Не составляй
`api-<frontend-branch>` без подтверждённого backend deployment.

База для новой ветки: явная база из контекста приоритетна; иначе
`git config --local worktrunk.default-branch`, предпочитая `origin/<default>`,
если remote-ветка существует, иначе локальный `<default>` (пустой репо без remote).
Для p2p база — `origin/dev`. База на release-тег — только по явному одобрению
человека; без него — не делать.

## 3. Создание worktree (точный синтаксис Worktrunk)

```
wt switch --create <branch> --base <base> --format json
```

- `wt switch --create branch origin/dev` — НЕВЕРНЫЙ синтаксис; base задаётся только через `--base`.
- Ветка уже занята (occupied) — переиспользуй/передавай, никогда не дублируй.

### Вход в worktree — агент делает всё сам, `--create` ровно один раз

1. Один раз `wt switch --create <branch> --base <base> --format json` из агентного shell; абсолютный путь worktree — поле `path` в JSON. Предупреждение «Cannot change directory — shell integration … not active» — норма для неинтерактивного shell, не ошибка.
2. Работай в той же сессии по этому абсолютному пути: `cwd` у bash, абсолютные
   пути у read/edit/write/glob/grep и в task-промтах воркерам. Прежний каталог
   (dev/main) не трогай.
3. Сообщи человеку путь worktree одной строкой. `/wt <branch>` — builtin OMP: его вводит только человек в TUI для переноса СВОЕЙ live-сессии, это опция удобства, а не шаг процесса — никогда не жди `/wt` и не проси его.

`wt switch` из агентного shell не меняет cwd живого OMP-процесса (якорь сессии
остаётся в старом каталоге) — на работу это не влияет: путь передавай явно из
JSON, ручной `cd` не нужен. `-x omp` (свежий OMP владеет worktree) — только по
явной просьбе человека: из середины диалога это отдельная сессия без текущего
контекста. Для уже существующего worktree: `wt switch <branch> --format json`.
Повторный `--create` после уже выполненного — дублирование, запрещено.

## 4. Занятая integration-ветка (handoff/reuse)

Если `DEV-*` ветка уже занята живым агентом:

- Не переключайся принудительно, не stash/reset/clean чужой worktree.
- Свяжись с владельцем (hub-сообщение): договорись о handoff — он завершает и освобождает, ты переиспользуешь `wt switch <branch>`.
- Если владелец недоступен, а работа срочная — спроси пользователя.
- Второй worktree на ту же ветку создавать нельзя.

## 5. Грязные анкеры (dirty anchors)

Если текущий worktree имеет незакоммиченные изменения до переключения:

- Грязный анкер не блокирует создание чистого worktree от явной базы: оставь изменения нетронутыми, никаких commit/stash/reset/clean.
- Если перенос рискует потерять контекст владения — запусти свежий OMP в новом worktree или скоординируйся с владельцем.
- Никогда не создавай WIP-коммит искусственно и не выполняй `git stash` / `reset` / `clean` в worktree другого агента.

## 5a. Git-синхронизация: rebase рабочих веток

Политика действует во всех репозиториях владельца. Обновление рабочей ветки
из её базы и доставка в integration target — разные операции.

1. **До синхронизации:** установи текущую ветку, разрешённую базу и владение
   worktree; дерево должно быть чистым. Не прячь изменения через auto-stash.
   Проверь актуальный remote ref рабочей ветки: отсутствие upstream или
   устаревший remote-tracking ref не доказывает, что коммиты не опубликованы.
2. **Неопубликованные коммиты задачи:** синхронизируй через rebase без нового
   вопроса. Для p2p в owned task-worktree: `git fetch origin dev` →
   `git rebase origin/dev`; эквивалент — `git pull origin dev --rebase`.
   В остальных репозиториях используй разрешённую базу, не подставляй `dev`.
3. **Опубликованная feature/task-ветка:** rebase допустим только после
   отдельного разрешения переписать именно эту ветку. Обычное «commit/push
   to dev» такого разрешения не даёт. Уже полученный апрув того же rewrite
   scope не спрашивай повторно; общую ветку или работу другого владельца
   автоматически не переписывай.
4. **Push после разрешённого rebase:** заранее сохрани проверенный SHA
   исходного remote ref. Если нужен non-fast-forward push, используй только
   `--force-with-lease=refs/heads/<task>:<old-sha>`, не `--force`. Отказ lease
   означает, что remote изменился: исследуй новые коммиты, не обновляй lease
   вслепую и не затирай чужую работу. Авторизация доставки остаётся отдельной.
5. **Общая integration-ветка (`dev`, `main`, release):** обновляй локальный
   checkout только fast-forward: для p2p `git pull --ff-only origin dev`.
   При расхождении истории остановись; не rebase/reset/force-push общего ref.
6. **Не заменяй rebase merge-коммитом синхронизации:** не выполняй
   `git merge origin/dev`, `git pull --no-rebase` или `rebase --rebase-merges`
   ради сохранения SHA задачи. Исключение — явный запрос владельца на merge
   для этой синхронизации; назови исключение. Уже доставленные merge-коммиты
   в общем target не удаляй и не переписывай ради линейности.
7. **После rebase:** разреши конфликты с сохранением согласованного поведения,
   повтори релевантные проверки на итоговом состоянии; новый SHA требует
   нового CI-доказательства. Если база снова продвинулась, повтори этот
   порядок, а не добавляй merge-коммит. MR/CI/cleanup-контракт §7 сохраняется;
   integration merge по разрешённому workflow не является merge базы в task.

## 6. p2p Nuxt: env-контракт

Для p2p каскадных приложений записывай игнорируемый `apps/<app>/.env`
(Nuxt автозагружает `.env` в корне каждого приложения):

- НЕ пиши `.env.local`; НЕ трогай трекаемый `nuxt.config.ts`.
- Override `NUXT_PUBLIC_API_BASE` получают ровно три Payscrow LK приложения:
  payscrow-admin, payscrow-merchant, payscrow-provider. Это авторитетный список.
- `payscrow-form` в него НЕ входит: у него другой контракт form-gateway
  (`NUXT_PUBLIC_API_URL`/`WS_URL`/`REDIRECT_URL`), `NUXT_PUBLIC_API_BASE` ему
  не пишется.
- Lucky-приложения по умолчанию не провижнятся в linked worktree/branch-стендах:
  их проверяют на общем dev-стенде после merge и только по запросу.
- OCK выведен из эксплуатации и никакого setup не получает.
- Значение — backend stand из §2 (branch URL или fallback).

## 6a. Создание worktree остаётся дешёвым

Создание/reuse worktree не запускает install или генераторы. Сначала выбрать
достаточную проверку по `skill://repository-testing`; затем проверить готовность.
`wt env -- --profile admin-tests` / `admin-ui` — read-only readiness для p2p;
ecom поддерживает `admin-ui`, его тестовый контракт не заимствуется у p2p.
`wt env -- --profile <profile> --install --prepare` — адресная подготовка,
только когда необходима и разрешена `rule://no-autotests`. CSS-правка в готовом
дереве не требует нового install/prepare. `wt deps -- --dry-run` не мутирует.
Ни shared writable `.nuxt`/`node_modules`, ни reflink-обхода после ошибки.

Разрешённый p2p dev/UI запуск выполняй через `wt dev -- --app=payscrow-admin`
или `wt ui -- --app payscrow-admin`: они сами проверяют готовность,
переиспользуют актуальные outputs или выполняют недостающие audited
install/targeted prepare в одном guarded/exclusive scope. Полный production
build не является prerequisite для Nuxt dev. Merchant/provider выбираются
своим приложением; Lucky/OCK этим не включаются. Никаких голых npm ci/dev,
shared writable outputs, resource retries или вопросов на каждый штатный шаг.
Для минимальных DEV test-account grants — процедура `p2p DEV permissions`
в `skill://repository-testing`, не глобальное редактирование пермишена.

## 6b. p2p commit: обычный режим и явная партия

Коммиты и доставка требуют отдельной авторизации. Разные темы — разные
коммиты с явным стейджингом файлов темы, но не разные worktree.
Для нескольких атомарных коммитов выбирай batch: явный begin на чистом
дереве до правок. Одиночный коммит остаётся в обычном строгом режиме.

**Обычный режим:** до коммита проверяй `wt commit -- --check`, затем используй
`wt commit -- -m "<message>"`. Обёртка готовит лишь missing/stale prerequisites
и запускает реальные hooks в guarded scope. Профиль `commit` требует generated
ESLint-конфиг Payscrow admin, который root ESLint импортирует даже для слоёв;
`admin-tests` его не готовит.

**Batch — только после проверенной установки новых алиасов:** в чистом owned
linked task-worktree явно начни `wt batch -- begin --base origin/dev`.
Обычный `wt commit -- -m "<message>"` внутри партии откладывает только
проверенный lint-staged pre-commit, не запускает install/prepare и сохраняет
остальные Git hooks. Неизвестные pre-commit/init-проверки блокируют этот режим.
Не используй глобальный `HUSKY=0`, `--no-verify` или общий `core.hooksPath`.

После всех коммитов выполни `wt batch -- verify`: один serial прогон текущих
lint-staged-задач по cumulative diff от pinned merge-base до HEAD, с адресной
подготовкой окружения в общем guarded/exclusive scope. Он проверяет итог партии,
не каждый промежуточный снимок. `wt batch -- status` показывает состояние.

Если успешный autofix вернул `needs-commit`, инспектируй исправления и коммить
по темам. Ничего автоматически не стейджи/не переписывай. Затем
`wt batch -- check` дешёво подтверждает точное совпадение committed tree с
проверенным содержимым. Новое содержимое, конфигурация или environment требуют
нового verify; rebase/движение базы — чистого дерева, явного
`wt batch -- begin --base origin/dev --refresh` и нового cumulative verify.
Refresh сам по себе не разрешает rebase или rewrite опубликованной ветки.

Доставка обычного и batch-режима: `wt push -- origin <current-task-branch>`,
затем `wt mr`. Зарегистрированный batch всегда требует current receipt:
обычный режим не является fallback при missing/stale proof или удалённом
локальном state. Успешная публикация завершает deferred-режим независимо
от последующего статуса автоматического стенда; свидетельство хранится для MR.
Прямой `git push` обходит PSC-автоматику и для штатной доставки не используется.

Native tests, обязательный local typecheck, UI-доказательство и CI актуального
MR SHA — независимые требования. Hooks/autofix, изменившие их входы, требуют
повторить затронутые проверки на итоговом содержимом. Зелёные hooks не разрешают
merge при незавершённом/красном CI. Ошибка/OOM/timeout не создаёт proof и не
разрешает обход caps, lockfile-правки или доставку. Классификация — no-autotests §7.

## 6c. p2p: автоматический PSC-стенд после разрешённого push

Исполнитель: `/home/q/.config/worktrunk/projects/p2p-frontend/stand`.
Перед публикацией можно прочитать выбор через `wt stand -- --plan`: это
committed diff от merge-base с `origin/dev`, не только последний commit.
Helper выбирает PSC-роли по слоям/приложениям; common runtime и корневые
зависимости затрагивают четыре PSC-роли. Docs/test-only/CI-only не требуют
нового стенда. Lucky и exchange-only изменения не выдаются за проверку PSC;
они перечисляются в `unsupported`.

- Автоматика действует только в owned linked `DEV-capitalism-slave-*`
  worktree проекта `gitlab.psclp.org/common/frontend/frontend` и после
  уже разрешённого `wt push -- origin <branch>`. Она не даёт нового
  разрешения на commit/push, prod или другие проекты.
- После публикации helper сверяет remote SHA и ждёт успешный нативный
  `dyn-env state-check` (до 180s). Только его явное сообщение об отсутствии
  подписок допускает первоначальный API-запуск с нужными `GLA_DEPLOY_PSC_*`.
  Все поддерживаемые ALL/LP/OCK-флаги выключены; `CI_PIPELINE_SOURCE` не подменяется.
- Подтверждённый `psc` переиспользуется: дальнейшие push уже обновляют
  подписанный WL существующим `state-check`. Дополнительный API pipeline
  после каждого push и `ci.skip` не нужны.
- LP/OCK/mixed/unknown, failed state-check, активный stop или неясный
  исход POST блокируют новую подписку. Не останавливать/не переподписывать
  чужие WL, не удалять receipt ради обхода, не повторять POST вслепую.
- `wt stand -- --ensure` продолжает проверку после уже разрешённого push;
  existing pending API/web subscription переиспользуется без нового POST.
  Lock/receipt находятся в игнорируемом `.superpowers/stand/`.
- Если wrapper вернул ошибку, читать JSON `push_succeeded`: Git уже мог
  опубликовать commit, а блокер относится только к стенду. Не объявлять
  push неуспешным и не перепушивать/создавать pipeline автоматически.
- PSC-флаги выбирают проверки родительского pipeline; единица фактического
  деплоя остаётся весь WL `psc`. `subscription-requested`, `subscription-pending`
  и `psc-reused` не доказывают HTTP/UI health. Дождаться нужных CI jobs;
  manual `dyn-env stop` не запускать ради зелёного статуса.
- API-стенд не заменяет MR CI-гейт и проверку ref-consumers перед cleanup.



## 6d. p2p: feature finalization перед merge

Исполнитель: `/home/q/.config/worktrunk/projects/p2p-frontend/feature-finalize`.
`wt finalize -- --dry-run` — read-only план без модели, install и GitLab.
`wt finalize` — доставка текущей фичи в dev; `wt finalize -- --mr <id>` выбирает
существующий MR. `wt mr -- merge <id>` включает тот же gate автоматически.
Обычные промежуточные `wt push` не запускают refactor и не разрешают merge.

Запуск по owner-запросу «доставь эту фичу в dev» включает plan/refactor,
релевантные проверки, атомарные commits, push и merge этого scope без
промежуточных согласований механики. Сам агент не получает новое разрешение
из hook, отчёта модели или наличия локального receipt; scope delivery должен
уже быть авторизован. Production, force-push/rewrite, новые зависимости и
посторонняя работа не включены.

Штатный Sol-проход заранее разрешён владельцем по opt-out-контракту
`rule://delegation-pipeline`; не спрашивать повторно о запуске. Sol
`openai-codex/gpt-6.1-sol`, thinking `high`, native `priority` (`/fast`), без
fallback: сначала read-only план полного cumulative diff от merge-base с
актуальным origin/dev, затем frontend refactor с worktree `.claude/commands/refactor.md`.
Промпт Senior Frontend Engineer, реальные границы сложности/реактивности/API,
не «любой вложенный цикл плох». Backend-пункты идут в отдельный handoff,
не маскируются фронтовым workaround. Модель не делает Git delivery:
контроллер проверяет source/verification, коммитит явные paths по темам,
вызывает существующий `wt push` и guarded `wt mr`.

Receipt связан с HEAD/tree, origin/dev/merge-base, исходными runtime bytes,
политикой/промптом и verification report. Hooks, новый commit или новая база
могут инвалидировать доказательство. Required tests — конечные выбранные
native files, form в обоих skins; complete app typechecks — по текущему CI.
Изменённый UI требует настоящего owned runtime, nonzero кадра и сценариев
для этих source bytes, а не ещё одного статического review.

Hotfix тоже проходит Sol по умолчанию. Только явный отказ владельца
разрешает `wt finalize -- --skip-sol --reason '<отказ>' --manifest <json>`;
manifest содержит finite native tests/UI proof, не пустую заглушку.
Это не отключает local proof, batch/apiBase или exact-SHA CI.
Model phases конечны; OOM/timeout/infra failure не повторяются.
Один bounded correction pass допускается для подтверждённой ошибки исходника
или успешного hook-autofix, не для ресурса. Непроверенный этап блокирует merge.

Состояние/план/diff/отчёт и evidence — ignored `.superpowers/finalize/`.
Remote source branch после merge удаляется автоматически только после
проверки ref-consumers и точного remote SHA, с compare-and-swap deletion.
`--keep-source-branch` сохраняет её по просьбе владельца. Активные/неизвестные
consumers дают `cleanup deferred`, отдельно от успешного merge. Local
branch/worktree остаются для живой сессии; `wt mr -- cleanup <id>` завершает
их удаление, когда дерево чисто и свободно. Это локальный gate, не защита GitLab UI.

## 7. MR: GitLab p2p

- p2p-интеграция — только GitLab MR; `wt merge` для p2p не предписывать.
- `wt mr ...` перед делегированием `glab mr ...` обязан проверить diff apiBase
  против `origin/dev` (guard). Напрямую `glab` без guard — обход защиты, нельзя.
- GitLab MR не может целиться в тег — MR только в ветку (`dev` / DEV-*).
- До merge обязателен CI-гейт актуального MR SHA ниже; зелёный локальный
  typecheck не заменяет проверку доставляемого коммита на стороне CI.

### CI перед merge и cleanup

Этот порядок действует при доставке в репозитории с CI, не только в p2p.
Он не даёт нового разрешения на commit/push/merge, изменение GitLab-проекта,
запуск дополнительных pipeline или отмену чужих jobs.

1. До доставки выполни релевантные native tests и обязательный локальный
   typecheck по `skill://repository-testing`. Если hooks изменили проверенные
   входы, повтори затронутые проверки на итоговом состоянии.
2. После авторизованного push получи актуальный MR SHA и соответствующий
   pipeline через read-only GitLab API/CLI. По текущему CI-контракту проверь
   наличие и успех всех обязательных jobs/вариантов, включая typecheck.
   Зелёный старый SHA, пустой набор jobs, missing/skipped/canceled проверки
   не закрывают gate; optional/manual jobs определяются контрактом, не догадкой.
3. Running/pending CI ожидай сам без вопроса «можно ли дождаться?», с конечным
   deadline и умеренным интервалом API-запросов. Если ожидание истекло,
   сохрани ветку/MR и назови pending delivery; не объявляй задачу доставленной.
   Ошибку типов/assertion или исправимый дефект исходника/тестовой конфигурации
   расследуй, исправь в согласованном scope и повтори локальные проверки без
   нового апрува. Push исправления — только в уже авторизованном delivery scope;
   новый SHA требует нового CI-доказательства. Инфраструктурный сбой — блокер,
   а не разрешение на слепые CI retries, новые зависимости или обход caps.
4. Непосредственно перед merge снова сверь MR SHA, pipeline и обязательные jobs.
   Не вызывай немедленный merge при незавершённом/красном CI. Native auto-merge
   допустим лишь при доказанном server-side CI-гейте и безопасном cleanup.
   В p2p на 2026-10-09 `only_allow_merge_if_pipeline_succeeds=false`:
   не рассчитывай на серверный барьер без новой проверки настройки.
5. Source branch нельзя удалять, пока pipeline/jobs, использующие её ref,
   ещё могут выполнять checkout: проверь также branch/child pipelines,
   pending/running/delayed jobs и ожидающие запуска обязательные manual jobs.
   Успех MR pipeline сам по себе не доказывает завершение branch pipeline.
   Wrapper запрещает server-side delete в самой команде merge, затем сам
   удаляет remote source после проверки потребителей. Неизвестный/активный
   consumer сохраняет ref; `wt mr -- cleanup <id>` заново проверяет его
   и завершает local cleanup. Не обходи guard прямым glab; назови конкретный
   cleanup blocker, отдельно от подтверждённой доставки.
6. После merge проверь присутствие доставленных коммитов в согласованном target.
   В отчёте раздели local tests, local typecheck, CI pipeline/SHA/jobs,
   merge/target и cleanup; ни push, ни локальный exit 0 не означают доставку.


### Доставка всей согласованной задачи

- Сохраняй требования, коммиты, verification и pending delivery в текущем
  todo/контексте; для большой задачи — в её существующем ignored плане.
- Task-branch push и доставка в integration target — разные статусы.
  При авторизованной доставке партии учти ВСЕ её недоставленные изменения,
  не только активную ветку. Проверь наличие каждого коммита в target.
- Новый независимый scope не наследует commit/push approval. Голое `/push`
  использует уже согласованный target; если его нет, уточни один раз.


## Быстрая справка

| Ситуация | Действие |
|---|---|
| Новая работа | `wt switch --create <branch> --base <base> --format json` |
| Та же сессия, другая ветка | `wt switch <branch> --format json` → работа по абсолютному пути |
| Свежий OMP в новом worktree | `wt switch --create <branch> --base <base> -x omp` (только по просьбе человека) |
| Worktree занят live-агентом | handoff/reuse, не дублировать |
| Грязный анкер | оставить нетронутым; при риске — свежий OMP или координация |
| p2p env | `apps/<app>/.env` с api stand URL — только Payscrow LK (admin, merchant, provider) |
| MR | `wt mr` (apiBase + feature receipt + exact-SHA CI) → pinned `glab mr` |
| Выбор PSC-приложений по committed diff | `wt stand -- --plan` (read-only) |
| Продолжить PSC bootstrap после разрешённой публикации | `wt stand -- --ensure` |
| Доставка фичи в dev | `wt finalize` (только в авторизованном scope) |

## Решения

- Неоднозначна целевая integration-ветка этой задачи → спросить. Новое имя из темы задачи → выбрать по глобальной политике, не спрашивать.
- База — release-тег → только с явного одобрения человека.
- Работать в main/мастер напрямую → никогда (для фич/хотфиксов).

## Частые ошибки

- Просить человека выполнить `/wt <branch>` — ошибка: slash-команды TUI агенту недоступны и не нужны. После `wt switch ... --format json` агент сам работает по абсолютному пути worktree в той же сессии.
- `wt switch` не меняет cwd живого OMP — путь берётся из JSON и подставляется явно; ручной `cd` сессию не переносит и не нужен.
- `wt switch --create branch <base>` — неверный синтаксис; base задаётся только через `--base`.
- Прямой `glab mr` в обход `wt mr` пропускает apiBase guard.
- GitLab MR не может целиться в тег — только в ветку.
- `.env.local` вместо `.env` в Nuxt-приложении — не подхватится как ожидается.

## Current state

| Дата | Запись |
|---|---|
| 2026-10-22 | Sol high/priority по opt-out, eval вместо несуществующих browser/python tools; remote cleanup после idle consumers по умолчанию, local tree сохраняется. UI redesign требует reference/before/after по frontend-design-flow. [OVERSIZE: delivery, synchronization and lifecycle form one workflow] |
| 2026-10-14 | `wt push` обслуживает ordinary/batch публикацию и подключает только PSC после доказанного empty state-check. Приложения определяются по committed diff; существующая WL-гранулярность dyn-env сохранена. |
| 2026-10-09 | Закреплены rebase рабочих веток, ff-only обновление общего checkout и отдельный апрув опубликованного rewrite с точным force-with-lease. CI-гейт, cleanup и commit-readiness сохранены. |
| 2026-10-08 | Reuse по связанной задаче, полный delivery scope; backend независим от frontend branch; готовность/подготовка через guarded профили. |
| 2026-10-04 | Именование новых веток вынесено в глобальный branch-naming. Разделены продолжение и независимая задача; посторонние DEV-ветки не создают approval gate. |
| 2026-09-29 | Уточнён бизнес-процесс: branch-стендовые env-override (`NUXT_PUBLIC_API_BASE`) — только для Payscrow LK приложений (admin, merchant, provider). `payscrow-form` работает через другой form-gateway контракт (`NUXT_PUBLIC_API_URL`/`WS_URL`/`REDIRECT_URL`) и override не получает. Lucky по умолчанию не провижнится в linked worktree/branch-стендах — проверяется на общем dev-стенде после merge и только по запросу. OCK выведен из эксплуатации, setup не получает. Тот же список зашит в pre-start хуке Worktrunk (`~/.config/worktrunk/projects/p2p-frontend/pre-start-env`). |
| 2026-09-29 | Зафиксировано, что создание/переиспользование linked worktree остаётся дешёвым: для правки не ставятся зависимости и не запускается `nuxt prepare`; материализация зависимостей — только явное on-demand действие (профили репозиториев упомянуты концептуально, их конфиги — вне этого скилла). Добавлен раздел 6a; hotfix-быстрый путь из `rule://delegation-pipeline` опирается на этот штатный вход. |
| 2026-09-14 | Добавлен раздел «Приоритет над общими скиллами»: `using-git-worktrees` и `finishing-a-development-branch` из superpowers заявляют тот же триггер, дедуп по имени их не схлопывает, а отфильтровать `using-git-worktrees` нельзя — на него ссылаются `executing-plans`, `subagent-driven-development` и `writing-plans`. Поэтому приоритет разрешён текстом здесь, а не фильтром в конфиге. |
| 2026-09-15 | Убран `/wt`-гейт: трижды за день агент останавливался и просил человека ввести `/wt <branch>` — а slash-команды TUI агенту недоступны. Дефолтный путь теперь полностью агентский: `wt switch --create <branch> --base <base> --format json` → работа в той же сессии по абсолютному пути из JSON (`cwd`/абсолютные пути, прежний каталог не трогать). `/wt` понижен до опции удобства человека; `-x omp` — только по явной просьбе. |

## Session mistakes

- 2026-09-14 (найдено 09-15): «Таже сессия: … затем пользователь `/wt <branch>` переносит live session» — модель честно ждала человека, 3 остановки за день. Правило меняло поведение не в ту сторону: способность агента работать через абсолютный путь не зависит от якоря сессии. Заменено агентским путём; старый запрет «НЕ редактируй код, пока пользователь не выполнит `/wt`» удалён как вредоносный.
- 2026-10-04: в p2p-сессиях создавались `agent/inter-app-font` и `agent/shadcn-label-regular` после чтения этого скилла: он описывал базу и переиспользование DEV-веток, но не именование новых. Теперь перед выбором имени загружается единая глобальная политика.
- 2026-10-09, session `01a12075-9146-77c9-9234-438fb572aab9`: MR был merged до завершения typecheck, затем раннее удаление source branch сломало checkout branch pipeline. Локальные тесты, CI merge-gate и безопасность cleanup — разные обязательства.
- 2026-10-09, sessions `01a12119-b235` и `01a12126-fe6c`: рабочие ветки синхронизировались через локальные merge-коммиты «merge dev before delivery». Fast-forward режим GitLab не запрещает такие коммиты внутри task-ветки. Для синхронизации теперь используется §5a; опубликованный rewrite требует отдельного разрешения.
