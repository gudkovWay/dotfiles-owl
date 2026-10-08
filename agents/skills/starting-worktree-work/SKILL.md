---
name: starting-worktree-work
description: Use when choosing a new working branch in any repository; when starting any feature, project, or hotfix work, or any change to feature/project/hotfix code; when a linked worktree may already exist or an integration DEV-* branch is occupied by a live agent; when the current worktree has uncommitted changes; when writing p2p Nuxt env overrides; when creating a GitLab MR via wt mr or glab; when basing a branch on a release tag.
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

## 7. MR: GitLab p2p

- p2p-интеграция — только GitLab MR; `wt merge` для p2p не предписывать.
- `wt mr ...` перед делегированием `glab mr ...` обязан проверить diff apiBase
  против `origin/dev` (guard). Напрямую `glab` без guard — обход защиты, нельзя.
- GitLab MR не может целиться в тег — MR только в ветку (`dev` / DEV-*).
- CI-гейт в этом скилле отсутствует.

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
| MR | `wt mr` (guard apiBase) → `glab mr` |

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
| 2026-10-08 | Reuse по связанной задаче, полный delivery scope; backend независим от frontend branch; готовность/подготовка через guarded профили. [OVERSIZE: 202 lines - ownership, branch/env и MR-контракт должны читаться вместе] |
| 2026-10-04 | Именование новых веток вынесено в глобальный branch-naming. Разделены продолжение и независимая задача; посторонние DEV-ветки не создают approval gate. |
| 2026-09-29 | Уточнён бизнес-процесс: branch-стендовые env-override (`NUXT_PUBLIC_API_BASE`) — только для Payscrow LK приложений (admin, merchant, provider). `payscrow-form` работает через другой form-gateway контракт (`NUXT_PUBLIC_API_URL`/`WS_URL`/`REDIRECT_URL`) и override не получает. Lucky по умолчанию не провижнится в linked worktree/branch-стендах — проверяется на общем dev-стенде после merge и только по запросу. OCK выведен из эксплуатации, setup не получает. Тот же список зашит в pre-start хуке Worktrunk (`~/.config/worktrunk/projects/p2p-frontend/pre-start-env`). |
| 2026-09-29 | Зафиксировано, что создание/переиспользование linked worktree остаётся дешёвым: для правки не ставятся зависимости и не запускается `nuxt prepare`; материализация зависимостей — только явное on-demand действие (профили репозиториев упомянуты концептуально, их конфиги — вне этого скилла). Добавлен раздел 6a; hotfix-быстрый путь из `rule://delegation-pipeline` опирается на этот штатный вход. |
| 2026-09-14 | Добавлен раздел «Приоритет над общими скиллами»: `using-git-worktrees` и `finishing-a-development-branch` из superpowers заявляют тот же триггер, дедуп по имени их не схлопывает, а отфильтровать `using-git-worktrees` нельзя — на него ссылаются `executing-plans`, `subagent-driven-development` и `writing-plans`. Поэтому приоритет разрешён текстом здесь, а не фильтром в конфиге. |
| 2026-09-15 | Убран `/wt`-гейт: трижды за день агент останавливался и просил человека ввести `/wt <branch>` — а slash-команды TUI агенту недоступны. Дефолтный путь теперь полностью агентский: `wt switch --create <branch> --base <base> --format json` → работа в той же сессии по абсолютному пути из JSON (`cwd`/абсолютные пути, прежний каталог не трогать). `/wt` понижен до опции удобства человека; `-x omp` — только по явной просьбе. |

## Session mistakes

- 2026-09-14 (найдено 09-15): «Таже сессия: … затем пользователь `/wt <branch>` переносит live session» — модель честно ждала человека, 3 остановки за день. Правило меняло поведение не в ту сторону: способность агента работать через абсолютный путь не зависит от якоря сессии. Заменено агентским путём; старый запрет «НЕ редактируй код, пока пользователь не выполнит `/wt`» удалён как вредоносный.
- 2026-10-04: в p2p-сессиях создавались `agent/inter-app-font` и `agent/shadcn-label-regular` после чтения этого скилла: он описывал базу и переиспользование DEV-веток, но не именование новых. Теперь перед выбором имени загружается единая глобальная политика.
