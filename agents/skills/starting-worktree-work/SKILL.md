---
name: starting-worktree-work
description: Use when starting feature/project/hotfix work in any repository; when the owner says finalize, to finalize, финализируй, доведи до конца to finish development through an open PR/MR; when choosing branches, resolving linked worktree ownership, synchronizing before commit/push/PR/MR or fixing non-fast-forward; when publishing p2p DEV stands, writing p2p Nuxt env overrides or creating GitLab MRs; when basing work on a release tag.
---

# Worktree-first вход в работу

Прежде чем менять код фичи/проекта/хотфикса — убедись, что ты работаешь в связанном worktree. Worktrunk (pinned 0.77.0) — единственный, кто создаёт и удаляет постоянные linked worktree. Напрямую `mkdir`, `git worktree add` или ручной `cd` в чужой каталог — запрещено.

Перед выбором имени ветки прочитай `/home/q/.omp/agent/rules/branch-naming.md`:
это единая глобальная политика для всех проектов, включая локальные worktree.

## Единственный worktree/delivery workflow

OMP использует этот скилл для worktree, синхронизации и доставки.
Superpowers orchestration/worktree/finishing skills исключены из discovery;
не загружай их как обязательную цепочку. Сохранённые четыре адресных метода
Superpowers не меняют полномочия и порядок Worktrunk. При глобальном finalize
конечная точка — открытый PR/MR без merge/auto-merge; в p2p только §7, не `wt merge`.

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
3. **Опубликованная feature/task-ветка:** в `p2p-frontend` rebase своей текущей
   task-ветки на `origin/dev` заранее разрешён владельцем, без отдельного
   запроса на переписывание при каждой синхронизации. Это относится только к
   owned linked worktree и собственной ветке задачи, не к чужой/общей ветке
   или integration target. До rebase проверь, что исходный remote tip входит
   в локальную историю; неизвестные/чужие коммиты сначала исследуй и сохрани.
   В остальных репозиториях опубликованный rebase требует отдельного
   разрешения именно этой ветки; уже полученный апрув не спрашивай повторно.
4. **Push после разрешённого rebase:** до rebase сохрани проверенный полный SHA
   исходного remote ref. Если нужен non-fast-forward push, используй только
   `--force-with-lease=refs/heads/<task>:<old-sha>`, не `--force` и не неявный lease.
   В p2p выполняй `wt push -- --force-with-lease=refs/heads/<task>:<old-sha> origin <task>`:
   для собственной task-ветки отдельный rewrite-апрув не нужен.
   Отказ lease означает, что remote изменился: исследуй новые коммиты,
   не обновляй lease вслепую и не затирай чужую работу. Сам push/delivery должен
   входить в разрешённый scope задачи (например, finalize); это правило
   снимает дополнительный rewrite-вопрос, но не разрешает постороннюю доставку.
5. **Общая integration-ветка (`dev`, `main`, release):** обновляй локальный
   checkout только fast-forward: для p2p `git pull --ff-only origin dev`.
   При расхождении истории остановись; не rebase/reset/force-push общего ref.
6. **Не заменяй rebase merge-коммитом синхронизации:** не выполняй
   `git merge origin/dev`, `git pull --no-rebase` или `rebase --rebase-merges`
   ради сохранения SHA задачи. Исключение — явный запрос владельца на merge
   для этой синхронизации; назови исключение. Уже доставленные merge-коммиты
   в общем target не удаляй и не переписывай ради линейности.
7. **После rebase:** разреши конфликты с сохранением согласованного поведения,
   повтори релевантные проверки на итоговом состоянии; если CI применим
   по §7, новый SHA требует нового CI-доказательства. Если база снова продвинулась, повтори этот
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



## 6d. p2p: feature finalization до открытого MR

Исполнитель: `/home/q/.config/worktrunk/projects/p2p-frontend/feature-finalize`.
`wt finalize -- --dry-run` — read-only план без модели, install и GitLab.
`wt finalize` — review/refactor, native checks, атомарные commits, push,
создание/обновление MR и exact-SHA CI; остановка на открытом MR, БЕЗ merge.
`wt finalize -- --mr <id>` выбирает существующий MR. Auto-merge выключается
и перепроверяется; source branch/worktree сохраняются для просмотра diff.
Глобальный смысл «to finalize»/«финализируй»/«доведи до конца» задан в
rule://delegation-pipeline для всех репозиториев. Здесь описан только
p2p-исполнитель; вне p2p использовать native PR/MR workflow проекта и §7.
Обычные промежуточные `wt push` не запускают refactor и не разрешают merge.

Только явная просьба merge/смёржить в dev разрешает `wt finalize -- --merge`
или `wt mr -- merge <id>` с теми же gates. Наличие receipt, hook или отчёта
модели не выдаёт полномочий. До вызова helper main сам завершает разрешённые
правки, релевантные проверки и атомарные commits: helper требует clean tree,
это не ручная задача владельцу. Force-push/rewrite и посторонняя работа не включены.

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

Единый review-контракт: `/home/q/.config/worktrunk/projects/p2p-frontend/review-contract.md`.
Main передаёт исходный owner-запрос и последующие поправки, а не только diff:
`wt finalize -- --session <raw-journal>` (повторить для релевантных parents).
Для native read-only review сначала `review_contract.py capture --root <owned>
--session <raw-journal>`, затем `validate --root <owned> --report <review.json>
--paths <changed-paths.json>`. Пути журналов main получает из session/history;
не просит владельца переписывать историю или документировать каждую ячейку.
Context нужен и при skip-sol; явный отказ отключает модель, не owner acceptance.
Сопоставление diff/аналога содержит проверенные paths/revisions/hashes и
решение preserve-reference/adopt-new-flow/keep-local с исходными основаниями.
Возраст сам по себе не определяет победителя. Неявное прежнее согласование
не выдумывать: неизвестность отмечать, устоявшийся референс сохранять.
Новый flow может вытеснить legacy-аналог по конкретному требованию, но не
разрешает глобальную миграцию, не нужную для текущего scope.

Receipt связан с HEAD/tree, origin/dev/merge-base, исходными runtime bytes,
политикой/общим review-контрактом, owner-context и verification report.
Новая owner-поправка, hooks, commit или база могут инвалидировать evidence.
Required tests — конечные выбранные native files, form в обоих skins;
complete app typechecks — по текущему CI. Изменённый UI требует настоящего
owned runtime, nonzero кадра и сценариев для этих source bytes, а не ещё
одного статического review.

Sol-этап ограничен source: terminal `agent_end` с stopReason=stop и полный
`implementation.json` с текущим source_key обязательны. Exit 0 и непустой лог
сами по себе не закрывают этап. Браузер и tests/typecheck не входят в model phase.

Если нужен UI, helper сохраняет `awaiting_ui` и точный run-dir. Main выполняет
штатный `wt ui` на итоговых bytes и передаёт owned JSON:
`wt finalize -- --resume <run-dir> --ui-proof <owned-ui-proof.json>`.
Файл содержит только `ui` и, при необходимости, обновлённый `review`.
Нужны status=verified, актуальный source_key, реальные scenarios и существующие
PNG. Возобновление не запускает Sol снова; source/policy/context/artifact drift
отклоняется. После влияющего hook нужен свежий proof; post-commit resume не
создаёт повторный commit. Failed/OOM/timeout run нельзя возобновлять таким путём.

Доказанный never-started resource admission сохраняет `awaiting_checks`;
продолжение той же ревизии — `wt finalize -- --resume <run-dir>`.
Это не PASS и не replay уже запускавшегося workload. JSON-native assertions
идут в bounded source correction; OOM/timeout/infra failure — нет.

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

### CI перед merge и cleanup — по контракту проекта

Этот раздел применяется к доставке во всех репозиториях, включая GitHub PR,
GitLab MR и разрешённую локальную интеграцию. P2P-гейт выше остаётся обязательным;
его нельзя автоматически переносить на остальные проекты.
Раздел не даёт разрешения на commit/push/merge, изменение настроек проекта,
запуск дополнительных pipeline или отмену чужих jobs.

**Сначала установи применимость CI, не требуй его существования.**

- Источники обязательности: явные критерии задачи, действующая политика доставки
  проекта, required checks/rulesets/branch protection и обязательные native gates.
  Наличие `.github/workflows`, старых runs или CI в upstream само по себе
  не делает Actions обязательными для форка. Проверь применимость к target,
  событию и изменённым paths; GitHub Actions — не единственный CI-провайдер.
- Read-only проверкой различи `required`, `optional`, `not configured` и
  `disabled/unavailable`. Обязательность и доступность — разные факты.
  Пустой список checks не доказывает ни успех, ни обязательность CI.
  API error/недостаток доступа не доказывает отсутствие required checks:
  если это нельзя выяснить из доступного контракта, назови конкретный unknown.
- Если обязательного CI-контракта нет, отсутствие CI, неприменимый workflow
  или отключённые Actions не блокируют уже разрешённый merge и не требуют
  owner-исключения. Продолжи после остальных применимых проверок; укажи
  `CI: not applicable` с основанием либо `CI: unverified — disabled/unavailable`,
  а не PASS. Это не отменяет local tests/typecheck/runtime, hooks и merge permissions.
- Если CI обязателен, missing/skipped/canceled/disabled остаётся блокером
  именно этого требования. Не заменяй его локальным exit 0. Текущее применимое
  pending/running или failed CI также не объявляй отсутствующим ради merge;
  проверь контракт и причину, дождись/исправь по процедуре ниже.
- Не создавай/не меняй workflow, не включай Actions, не меняй permissions,
  billing или branch protection и не делай пустые commits/reopen PR ради CI
  только потому, что checks не появились. Настройка/восстановление CI —
  отдельный явно запрошенный scope, не подразумеваемая часть merge.

Перед merge запиши одной строкой: `CI: <обязательность>; основание:
<policy/required checks>; доступность: <state>; решение: <ждать/блокер/не блокирует>`.
Если CI неприменим/необязателен и отсутствует, пропусти ожидание CI ниже,
но сохрани local verification, проверку target и безопасность cleanup.

1. До доставки выполни релевантные native tests и обязательный локальный
   typecheck по `skill://repository-testing`. Если hooks изменили проверенные
   входы, повтори затронутые проверки на итоговом состоянии.
2. Для применимого CI после авторизованного push получи актуальный PR/MR SHA
   и соответствующий pipeline/check runs через read-only API/CLI провайдера.
   По установленному контракту проверь обязательные jobs/варианты, включая
   typecheck, если он требуется этим контрактом. Старый SHA и пустой набор
   jobs не закрывают обязательный gate; optional/manual jobs определяются
   контрактом. Отсутствие необязательных jobs не создаёт новый gate.
3. Применимый running/pending CI ожидай сам без вопроса «можно ли дождаться?»,
   с конечным deadline и умеренным интервалом API-запросов. Не ожидай появления
   необязательного отсутствующего CI. Если ожидание истекло, сохрани ветку/PR/MR
   и назови pending delivery; не объявляй задачу доставленной.
   Ошибку типов/assertion или исправимый дефект исходника/тестовой конфигурации
   расследуй, исправь в согласованном scope и повтори локальные проверки без
   нового апрува. Push исправления — только в уже авторизованном delivery scope;
   новый SHA требует нового доказательства применимого CI. Инфраструктурный
   сбой обязательного CI — блокер, а не разрешение на слепые retries,
   новые зависимости или обход caps.
4. Непосредственно перед merge снова сверь PR/MR SHA и применимые CI gates.
   Не вызывай немедленный merge при незавершённом/красном применимом CI.
   Native auto-merge допустим лишь при доказанном server-side CI-гейте
   и безопасном cleanup.
   В p2p на 2026-10-09 `only_allow_merge_if_pipeline_succeeds=false`:
   не рассчитывай на серверный барьер без новой проверки настройки.
5. Source branch нельзя удалять, пока pipeline/jobs, использующие её ref,
   ещё могут выполнять checkout: проверь также branch/child pipelines,
   pending/running/delayed jobs и ожидающие запуска обязательные manual jobs.
   Успех MR pipeline сам по себе не доказывает завершение branch pipeline.
   P2P wrapper запрещает server-side delete в самой команде merge, затем сам
   удаляет remote source после проверки потребителей. Неизвестный/активный
   consumer сохраняет ref; `wt mr -- cleanup <id>` заново проверяет его
   и завершает local cleanup. Не обходи guard прямым glab; в других проектах
   используй их native cleanup. Подтверждённое отсутствие consumers не требует
   создания pipeline. Cleanup blocker отделяй от подтверждённой доставки.
6. После merge проверь присутствие доставленных коммитов в согласованном target.
   В отчёте раздели local tests, local typecheck, применимость/доступность CI
   и его pipeline/SHA/jobs, merge/target и cleanup; ни push, ни локальный exit 0
   не означают доставку. Отсутствующий CI не выдавай за успешный.


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
| До открытого MR без merge | `wt finalize` (только в авторизованном scope) |
| Явно разрешённый merge | `wt finalize -- --merge` / `wt mr -- merge <id>` |

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
| 2026-10-28 | P2P: rebase своей опубликованной task-ветки и точный force-with-lease при разрешённой доставке не требуют отдельного rewrite-апрува. Общие/integration refs и чужая работа исключены; ordinary/batch hooks и verification сохраняются. |
| 2026-10-25 | CI merge-gate определяется контрактом проекта, не наличием workflow или привычкой p2p. Отсутствующий/отключённый необязательный CI не блокирует разрешённую интеграцию и не требует owner-исключения; настройка CI не входит в merge автоматически. |
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
- 2026-10-09, sessions `01a12119-b235` и `01a12126-fe6c`: рабочие ветки синхронизировались через локальные merge-коммиты «merge dev before delivery». Fast-forward режим GitLab не запрещает такие коммиты внутри task-ветки. Для синхронизации используется §5a; с 2026-10-28 собственная p2p task-ветка имеет standing rewrite-разрешение, остальные опубликованные ветки требуют отдельного апрува.
- 2026-10-25, session `01a173ea-7001-75fd-a09b-c496e907c5de`: отсутствие Actions на форке Noctalia объявили блокером merge без установленного обязательного CI-контракта; добавили триггеры и пытались включить Actions. Теперь сначала устанавливается применимость/обязательность CI, отдельно от доступности; p2p-гейт не переносится на форки.
