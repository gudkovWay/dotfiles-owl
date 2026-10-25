---
name: desktop-sandbox
description: Используй при изменении desktop-инструмента, GUI-проверке, exposed=0, screen off, устаревшем capture, вложенном Hyprland, второй noctalia или аудите изоляции. Выбирай отдельный экземпляр и диагностируй переход на виртуальный output; read-only аудит не разрешает запуск.
---

# Desktop-проверка отдельного экземпляра

## HARD GATE

Авторизацию определяют правила текущего harness. В OMP запрос на изменение
desktop-поведения включает конечный запуск, тестовый конфиг, owned UI и capture
по `rule://no-autotests`, §6а: не проси отдельного разрешения на эти штатные шаги.
Без такого разрешения нужен явный запрос на запуск; read-only аудит и явный
«без запуска» его не дают. Изменение правил само по себе не проверка приложения.

Не останавливай, не заменяй и не перенастраивай живой процесс ради теста.
Скрытый workspace разделяет окна, не HOME/профили/IPC/ввод/сервисы. XDG-wrapper
тоже не filesystem/PID/UID/security sandbox. Нет безопасного отдельного экземпляра —
исследуй overrides, затем укажи конкретный блокер, не переходи на живую сессию.

## Выбери достаточный режим сам

| Изменённая поверхность | Способ проверки |
|---|---|
| CLI без GUI | Конечный нативный entrypoint с нужными test config/IPC; compositor не нужен |
| TUI или обычное GUI-окно | Отдельный экземпляр на скрытом special workspace, явный test config/profile при необходимости |
| Web | Штатный owned headless профиль репозитория, не личный браузер |
| Noctalia/layer-shell, Hyprland/plugin, независимый ввод | Отдельный compositor с минимальным конфигом и отдельным тестируемым экземпляром |
| OpenRGB/звук/Bluetooth/живой демон | Mock/fixture, если есть в штатном стеке; реальная интеграция только в явно разрешённом scope |

Не строй общий реестр окружений или восстановление процессов ради одного запуска.
Для XDG-стенда/вложенного Hyprland — существующая обёртка
`/home/q/.agents/skills/desktop-sandbox/scripts/vd-run.sh`.
Обычному окну nested compositor только ради сокрытия не нужен; config/profile/IPC
выбираются по приложению. Не добавляй новый runner вместо нативных тестов.

## Перед запуском

1. Разреши owned worktree, выбери конечный native сценарий изменённого поведения. Проверяй новые bytes; нужная целевая штатная сборка — по правилам harness, без установки/замены live binary или plugin.
2. Прочитай config и поддерживаемые config/profile/socket/instance параметры.
   Проверь singleton lock, D-Bus activation, remote forwarding и replace/restart:
   новая команда может передать действие старому процессу вместо создания нового.
   Подготовь минимальный конфиг с изменённым поведением или remapped копию.
3. Определи writable-пути и IPC; разделяй конфликтующие данные. Stateless терминалу отдельный HOME не обязателен.
   Для stateful daemon/shell проверь четыре XDG-корня, HOME-профили, absolute paths, symlink/includes; не копируй live writable references.
   Baseline затрагиваемых живых файлов: resolved target, mtime/ctime, checksum, без чтения секретов/истории.
4. В wrapper CONFIG/DATA/STATE/CACHE_HOME и NOCTALIA_STATE_HOME ведут внутрь `$VD_ROOT`;
   права sealed fixture меняй только у копии. Переназначь не-XDG destinations:
   WALLPAPER_CONTEXT_SCRIPTS, WALLPAPER_STUDIO_LAUNCHER, WALLPAPER_STUDIO_DATA_DIR,
   KITTY_SKINS_ROOT и test plugin/CLI. Не устанавливай в `~/.local/bin`/глобальный skill.
5. Для каждого GUI/daemon запуска запиши bus-policy: private по умолчанию; без bus — только если он не нужен; live bus — только для названной разрешённой интеграции.
   Переназначь HOME/XDG до старта private bus; контролируй activation service dirs. Внешний `dbus-run-session` до remap запускает сервисы со старым окружением; bus внутри wrapper не охватывает compositor.
   Это не изолирует UID, /proc или user manager. Запрещены `dbus-update-activation-environment --systemd --all`,
   `systemctl --user import-environment` и импорт sandbox paths в живой manager.
6. Обычное окно запускай через `/home/q/.local/bin/agent-app -- <cmd…>` внутри resource guard; launcher не уводит процессы в uwsm/systemd scope.
   OMP hook передаёт `OMP_GUI_KEY` на каждый bash-вызов: session ID + agent registry ID → `special:omp-<key>`. Ключ — маршрутизация, не право убивать процессы.
   В старой сессии без hook: `agent-app --session <текущий-ID> --agent <registry-ID; main=Main> -- <cmd…>`; не придумывай ID и не перезапускай сессию ради этого.
   Сначала `agent-app --dry-run …`; при запуске launcher проверяет загрузку персональной маршрутизации в целевом compositor, иначе отказывает до открытия окна.
   Kitty: отдельный `--class agent-test`, без `--single-instance`; nested host — `aquamarine`. Без ключа старые окна идут в общий `special:agent-tests`.
   Основной маршрут — `window.open_early` с временным запретом map-focus; guard — подстраховка. Не делай `kitten @ launch` в живой Kitty, не перезагружай живой compositor ради проверки.
7. Запуск и потомки — в общем capped scope по resource guard harness; запиши свои PID/start-time, socket/profile/root.
   Ввод — в owned приложение/вложенный compositor, не глобальный uinput/wtype или фокус человека.

## Границы существующего wrapper

| Режим | Изолировано | Общее |
|---|---|---|
| `vd-run.sh <cmd…>` | четыре XDG-корня, NOCTALIA_STATE_HOME, runtime `$VD_ROOT/run`; WAYLAND_DISPLAY/signature сняты | HOME, UID, /proc, bus без явного отделения; DISPLAY/Xauthority не сняты |
| `vd-run.sh --hypr <cmd…>` | те же XDG-корни; свой compositor PID/signature/Wayland socket | HOME, UID, /proc, `/run/user/<uid>`, bus без явного отделения |

`--hypr` требует parent WAYLAND_DISPLAY; в ssh/headless может быть недоступен.
Общий runtime — свойство этой реализации, не техническая неизбежность.
`cp -rL` материализует symlink, но не исправляет absolute references внутри.
`VD_HYPR_CFG` — прочитанный минимальный config без live autostart/source, plugins
и monitor scripts. Копия полного Hypr config ранее приводила к SEGV.
Не показывай host и не toggle workspace ради разблокировки capture.

## Профили, instance и проверяемый сценарий

1. Zen/Firefox — явный disposable profile без forwarding к живому browser.
   HOME реален: XDG не скрывает `~/.zen`, `~/.mozilla` и `--profile`. Не переносить
   cookies, пароли, токены, sessions/историю. Новый default profile не доказывает
   удаления старого; восстановление только из доказанного backup точных файлов,
   не bulk reset/слияние профилей.
2. Nested compositor выбирай по запущенному PID: `hyprctl -j instances` связывает
   его с signature/wl_socket; `wayland-2`/HEADLESS-1 переиспользуются. Внешний IPC —
   `hyprctl -i <owned-signature>`, клиенты/grim — его socket/runtime. Без выбора
   instance не мутируй. Обычный скрытый клиент остаётся на live compositor:
   это не разрешает захват монитора или глобальный ввод в пользовательскую сессию.
3. Test plugin загружай только в owned compositor. Сборка, файл, регистрация пути
   и loaded библиотека — разные состояния. `plugin not loaded` для resolved пути
   не доказывает отсутствия canonical registration.
4. Выполни выбранное действие и проверь наблюдаемый результат. Capture требует
   width/height > 0, enabled/DPMS-on, верные scale/transform/position, monitor клиента
   и полные extents. Socket ready, `ok` и availableModes — не кадр.
   Целый owned output — `grim -o <output>`, без `-g`; bounded geometry пересекает
   его реальные координаты, не geometry живого стола. У обычного скрытого окна
   нет отдельного output: нужен поддерживаемый capture именно клиента, иначе
   capture blocked, не `grim` живого монитора.
5. Source/config/assertion-ошибку исправляй и перепроверяй в scope под теми же
   лимитами без вопроса. Недоступную поверхность обрабатывай через display fallback
   ниже; OOM/timeout/infra/bootstrap failure и crash — по resource policy harness.

## Завершение и evidence

Останови только свои процессы по проверенному PID/start-time/родству или owned scope.
Не делай global pkill/killall, не удаляй общие sockets, не останавливай live service.
Wrapper cleanup не гарантирует остановки потомков; проверь teardown отдельно.
Логи/кадры wrapper — `$VD_ROOT` (`/tmp/vd-*/`); нужное сохрани в ignored worktree
`.superpowers/**`. Удаляй лишь свой точный root после выхода процессов, не каталоги
по возрасту. Сравни baseline затрагиваемых живых файлов.
Отчёт: режим/конфиг, source/build, отдельный процесс, действие/результат,
output/capture/animation, live preservation и teardown; каждому статусу —
verified/unverified/blocked либо неприменимость с причиной. Запуск не доказывает
действие, кадр — взаимодействие, установка — активацию.

## Failure modes

- `exposed=0`, DPMS off, hidden stall, старый буфер, HEADLESS-1 0×0 или отсутствие screencopy → **display fallback**: выполни `references/display-fallback.md`, не показывай host и не останавливай всю задачу.
- `supplied geometry did not intersect` → проверь output/координаты по display fallback; причина не доказана одним сообщением.
- Смена display-среды требует сохранения native runner, критериев и caps; отдельный crash/OOM не списывай на screen off.
- Снимок live desktop → не просматривай/не публикуй, останови owned capture.
- Live цвета/профиль изменились → останови свой стенд, установи источник по baseline;
  не применяй default палитру, не восстанавливай всё из случайной копии.
- Нет independent config/socket или есть singleton forwarding → runtime blocked,
  не убивай singleton; остальные независимые проверки продолжай.

## Scripts

| Скрипт | Назначение |
|---|---|
| `/home/q/.agents/skills/desktop-sandbox/scripts/vd-run.sh` | XDG-wrapper, опционально nested Hyprland; не security sandbox |
| `/home/q/.local/bin/agent-app` | Персональная маршрутизация; `--dry-run`, явный session/agent для старых сессий; сохраняет cgroup |
| `/home/q/.agents/skills/desktop-sandbox/scripts/check-workspaces.py` | Конечный native GUI-сценарий; `--headless` — Gamescope parent с private runtime/bus; совместимость backend проверять до запуска |
## Current state

| Дата | Состояние |
|---|---|
| 2026-10-26 | Headless Gamescope стартует без live display, но установленный Hyprland/Aquamarine требует wl_compositor v6 при server max v5 и падает до кадра. `--headless` runtime blocked; свежий render/driving не доказаны. |
| 2026-10-02 | Исторический аудит: hidden capture failed, wrapper runtime unverified; запрет прогонов относился к тому аудиту, не всем будущим задачам. Zen source profile сохранён, причина нового HOME-profile неизвестна. |

Подробные quotes/исходы: `references/isolation-render-evidence.md`, читать при диагностике.

## Session mistakes

- 2026-10-25: разрешение автономного запуска не заменяет рабочую маршрутизацию; uwsm может вывести процесс из resource scope. Bus-policy нужна каждому GUI/daemon сценарию.
- 2026-10-02/09-30: socket/`ok` приняли за capture; hidden stall/GBM failures не доказали неподдерживаемый mode.
- 2026-09-18–21: XDG/state-only не защитили live конфиги/LED/mpv; проверять HOME, bus, paths и process ownership.

Self-check: при недоступной поверхности выполнена диагностика display fallback; отдельный экземпляр/bus/IPC, capture/interaction/preservation и teardown доказаны либо названы точные блокеры; независимая работа продолжается.
