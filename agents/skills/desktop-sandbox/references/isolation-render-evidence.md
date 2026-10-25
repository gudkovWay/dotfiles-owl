# Isolation/render evidence — 2026-10-02

Это статический аудит, не инструкция запустить проверки. Текущая авторизация
запрещает новые tests/build/lint, compositor, grim, browser и live checks.
Успех старой операции не разрешает повтор и не доказывает работу нового wrapper.

## Источники и обозначения

- **P** — исходный JSONL `/home/q/.omp/agent/sessions/-storage-projects-workflow/2026-10-02T10-24-58-071Z_01a0fc25-4cd7-71ad-8d9b-fe49f806a770.jsonl`.
- **E** — связанный исходный JSONL `/home/q/.omp/agent/sessions/-storage-projects-workflow/2026-09-30T08-47-13-015Z_01a0f17f-1677-7564-b26e-d09cb29efaad.jsonl`.
- `P:3297 → 3299` означает оригинальный toolCall и toolResult, не пересказ compaction.
  Один JSONL message может содержать несколько calls.
- Подробные metadata, hashes, comparisons, provenance и отчёт:
  `/home/q/dev/qol/.worktrees/kitty-skins/feature/kitty-skins/.superpowers/research/2026-10-02-system-isolation-audit/`.
- Сведения 09-18–21 ниже унаследованы из ранее установленного skill; их исходные
  сессии в этом аудите не переисполнялись и не переаудировались.

## XDG, HOME, overrides, runtime и bus

**Доказанная граница wrapper:** четыре XDG-корня и `NOCTALIA_STATE_HOME`
перенаправлены в новый `/tmp/vd-*`. HOME/UID/процессы/session bus не изолированы.
`cmd` получает собственный runtime и снимает WAYLAND_DISPLAY/Hypr signature,
но не снимает DISPLAY/Xauthority. В `--hypr` runtime общий с parent Wayland;
signature/socket выбираются по PID запущенного дочернего compositor.
Это конкретная реализация, а не доказательство невозможности private runtime.

**Absolute destinations:** P:488 sandbox install задавал назначения
`WALLPAPER_CONTEXT_SCRIPTS=$VD_ROOT/context-scripts`,
`WALLPAPER_STUDIO_LAUNCHER=$VD_ROOT/bin/wallpaper-studio`,
`WALLPAPER_STUDIO_DATA_DIR=$VD_ROOT/share/wallpaper-context`.
XDG сам по себе не меняет глобальный skill root, `~/.local/bin`, `~/.local/lib`
или абсолютный `--profile`. Live deployment P:1771 и P:2319 действительно писал
именно глобальные назначения; это отдельные операции, не sandbox side effect.

**Копия fixture:** E:4021 и следующие результаты — PermissionError при
перезаписи копии sealed JSON. После нового разрешения E:4063 меняет chmod
только copied capture JSON, remap абсолютных ссылок и `auto_apply=false`.
P:618 и далее использовали remapped old/new fixture для headless pipeline.
Это не доказательство успешного screenshot или принятого качества renderer.
Нельзя chmod оригинал, оставлять live pack/capture paths или auto_apply в fixture.

**Bus boundary:** private bus должен охватывать нужные процессы явно.
`dbus-run-session` внутри wrapper охватывает команду, но не уже запущенный
compositor; снаружи wrapper — оба. Он не изолирует /proc и systemd user manager.
Живой Hypr autostart содержит `dbus-update-activation-environment --systemd --all`:
копия полного дерева могла бы импортировать sandbox paths в живой менеджер.
В рассмотренных текущих запускаx использовался минимальный config; такого импорта
не найдено. Не переносить autostart/source/includes в стенд.

**Symlink:** старый wrapper `cp -r` сохранял ссылки; новая копия `cp -rL`
материализует targets. В обследованных live hypr/noctalia config trees symlink
не обнаружены: здесь это hardening потенциальной утечки, не доказанная причина
инцидента Zen. References внутри текста всё ещё требуют отдельного анализа.

## Zen: новый профиль не равен удалению исходного

Два самостоятельных regular roots, без symlink-переадресации:

- Исходный `/home/q/.config/zen/92ohqv5u.Default (release)` существует.
  `profiles.ini` и `installs.ini` имеют mtime/ctime 2026-08-13;
  `user.js`, `userChrome.css` и blossom CSS — до начала P (2026-10-01).
  Три blossom CSS byte-identical текущим `integrations/zen-theme/` sources;
  userContent/zen-themes/mod CSS совпадают с сохранённым pre-change backup.
- `/home/q/.zen/o3he6739.Default (release)` зарегистрирован
  2026-10-02 19:15:10 UTC; user.js/userChrome/userContent/blossom CSS там отсутствуют.
  Этот новый HOME-профиль не заменяет исходный XDG-профиль.
- Preexisting `zen-blossom-home.service` явно указывает `--profile`
  на исходный XDG-профиль; desktop launcher и hypr autostart профиль явно не задают.
  Какая launch environment выбрала новый профиль — **не установлено**.
- В original parent/child tools не найдено удаления/reset/copy/write этих двух
  profile roots, их registrations или browser launch. Это ограниченный вывод
  по протоколам, не утверждение об отсутствии внешних запусков.

**Восстановлено: ничего.** Нет подтверждённого повреждённого файла.
`zen-reference-before` и `zen-2k-scale-before` — config-only candidate backups;
старый userChrome/CSS не равен последующим легитимным правкам 10-01.
Bulk restore уничтожил бы эти правки. Browser databases, sessions, cookies,
пароли, токены и browsing contents не читались и не переносились.
Не запускать browser с auto-profile: нужен явный disposable profile и отсутствие
remote forwarding к живому browser, поддерживаемые параметры известны заранее.

## Nested startup, parser и class — отдельные контракты

P:464 → 466: FrameQualityComparison действительно стартовал;
owned wrapper PID 103266, compositor PID 103289, root `/tmp/vd-wvX32q`.
P:2217 → 2221: SilverPearlNativePreview стартовал с compositor PID 3585254,
root `/tmp/vd-JnjGUO`. P:3270 → 3272: FlowerJoinedSandbox стартовал с PID 3662409,
root `/tmp/vd-s5vpiw`. Эти ready события подтверждают startup/socket, не capture.

P:2231 → 2233: `hyprctl eval` в минимальном legacy config ответил
`eval is only supported with the lua config manager`.
P:2237 → 2239: legacy dispatchers меняют geometry, но plugin preview отвергает
`agent-test`: `is not a "kitty-skin-preview" window; refusing to preview in it`.
P:2240 создаёт нужный dedicated class ВНУТРИ owned compositor;
P:2246 → 2248 preview dispatchers получают `ok`.
Решение для заранее разрешённого запуска: выяснить config manager и API/class
до запуска. Не ломать class guard и не считать batch exit code доказательством
успеха каждой команды. Lua live manager и минимальный legacy manager различаются.
Dedicated nested class не разрешает такое окно на активном живом столе.

## Capture: фактические исходы

### Скрытый flow утром — failed

P:516 запускает grim в FrameQualityComparison; capture зависает.
P:532 → 534 `output create headless` возвращает `0 ok`.
P:545 → 547 monitor keyword тоже `0 ok`.
**P:548 → 550:** HEADLESS-1 всё равно width=0, height=0,
несмотря на advertised 1920×1080 mode. Ready output не доказан.
P:557 → 559 останавливает owned service;
P:572 → 574 все четыре известных owned PID exited, baseline screenshot отсутствует.
P:453/560/821 и текущий file hash подтверждают сохранность `noctalia.lua`;
P:572 → 574 live panel совпадает с сохранённым baseline.
Это preservation двух конкретных файлов, не всех живых настроек.

### Видимый nested flow — capture succeeded, но не hidden solution

P:2249 → 2251 скрытый grim не завершился; P:2252 → 2254 PNG отсутствовал.
P:2256 → 2258 находит aquamarine host по owned PID 3585254 на hidden workspace.
P:2259 → 2261 перемещает его на живой workspace 11 в рамках отдельного live-preview
разрешения. P:2262 → 2264 grim завершается за 0.08 s;
P:2285 → 2287 ещё capture за 0.06 s;
P:2291 → 2293 две фазы с sleep 4 завершаются за 4.13 s.
Этот опыт доказывает capture после видимого размещения; причина hidden stall
не установлена. Он НЕ разрешает toggle/move/show host ради hidden tests,
не гарантирует художественную приемку и не доказывает новый flow 18:36.

### Последний hidden flow — failed

P:3285 запускает grim; P:3300 → 3304 показывает owned заблокированный PID 3663112.
P:3294 → 3296 output create возвращает `ok`.
**P:3297 → 3299:** WAYLAND-1 1800×1100, HEADLESS-1 **0×0**, enabled, DPMS-on,
scale 1, availableModes 1920×1080. Эти flags не заменяют real geometry.
P:3300 → 3303 monitor keyword `ok` не доказывает последующий ненулевой output.
P:3305 → 3307 останавливает именно owned stalled grim.
P:3309 запускает `grim -o HEADLESS-1`; сохранённый
`/tmp/vd-s5vpiw/command.log:131`:

> supplied geometry did not intersect with any outputs

`CAPTURE_COMPLETE` отсутствует. P:3318 закрывает owned kitty/session.
Статусы: compositor started; renderer loaded; output not ready;
capture failed; animation/owner acceptance этим запуском **unverified**.

### Старые протокольные данные — allocation failure, не неподдерживаемый mode

E:4161 содержит named headless output, monitors и bounded grim protocol capture.
Сохранённый `.superpowers/research/hyprland.log:706–717`:

> GBM: Allocating with modifiers failed, falling back to modifier-less allocation
> GBM: Failed to allocate a GBM buffer: bo null
> Couldn't allocate a gbm buffer with size [Vector2D: x: 1440, y: 960] and format XR24
> Swapchain: Failed acquiring a buffer

Та же ошибка присутствует для **1920×1080** (lines 714–717 и далее).
Advertised mode и keyword `ok` не доказывают allocation. Low-level причина
не установлена; «всего лишь неподдерживаемый 1440×960 mode» не подтверждена.
Новые backend/flags/modifier experiments не запускались этим аудитором.

## Discovery и private IPC — узкий успешный результат

E:2814 → 2819: `sway --get-socketpath` не обнаружил private socket.
E:2821 → 2823 directory glob пропустил Unix sockets; отсутствие в listing
не доказало отсутствия endpoint. E:2827 → 2829 `os.scandir` + socket stat
обнаружили `sway-ipc.1000.287078.sock` и `wayland-1` внутри своего runtime.
E:2830 → 2836 явный owned SWAYSOCK дал IPC и два выхода 1280×800.
Это доказанный успех discovery/IPC/output, не приемка Hyprland renderer или
самостоятельное доказательство завершения grim. E:2839 остановил owned Sway;
E:2843 проверил targets созданных ссылок, E:2846 → 2848 удалил только эти
добавленные links/runtime. Они сейчас отсутствуют. Sway не установлен как fallback.

## Linked live migrations и риск следующего login

Ранние original sessions 09-29 действительно меняли Kitty include, Hypr
windowrules/monitor gaps/autostart, native DSOs и Gothic pack. Попытка заменить
root-owned HyprWindowShade cache (session `01a0ee8f`, call 1234 → result 1236)
остановилась на Permission denied ДО swap; user-owned deployment 1295 → 1297 прошёл.
В следующей сессии `01a0ef56:7` владелец сообщил blank Kitty после reboot;
это доказанная пользовательская проблема, не повод повторить reboot для проверки.
Позднее `01a0f17f:617` владелец сообщил «Окей, это работает».
Нельзя откатывать современный renderer на старый precompose backup вслепую.

E:3254 → 3258 live Studio installer/migration prepare завершились с exit 0,
сохранив выбранные DP-2/DP-3 сцены. E:3259 передал ownership от W-Engine;
E:3278 поменял picker bind и bar widgets, E:3287 → 3289 активировал новых
consumers. E:3533 → 3535 явно сравнил preferences/jobs/variants/mappings/
design_profiles/last_applied и playback после schema-3 migration: preserved.
Это историческая осознанная миграция, не current sandbox reset.

P сейчас оставляет persistent canonical DSO `fee5acc…`, CLI 16:03 и часть
backend нового поколения при старых studio/frame_preview/panel; последний live
renderer был загружен из `/tmp/frieren-pearl-live-*`, а не persistent canonical.
Автостарт использует canonical path. Свежий login/ABI/mixed deployment и новый
wrapper не упражнялись аудитором: **unverified**, не «ребут безопасен».

## IPC/plugin identity и cleanup

P:3042 → 3044 unload resolved digest path: `plugin not loaded`.
P:3045 → 3047 unload canonical registered path: `ok`.
P:3051 swaps canonical symlink; P:3055 → 3057 canonical load: `ok`.
На диске resolved library, canonical symlink, registered plugin path и runtime
mapping — разные состояния. Reload live plugin не нужен для isolated capture.

Старый skill предписывал global `pkill -f 'tee /tmp/vd-.*/command.log'`;
старый wrapper удалял ВСЕ `/tmp/vd-*` старше суток в фоне.
Это могло задеть чужие/ещё работающие стенды; подтверждённого такого удаления
в этом аудите нет. Оба предписания убраны. Нужны точные owned PID, start-time,
родство/root и scoped service; wrapper EXIT знает только свой compositor,
не гарантирует уборку каждого grim/noctalia/tee. Не трогать shared sockets.
Age/mtime не доказательство завершённости. TMP prune не объясняет Zen roots.

## Исторические lessons и текущий hardening

Унаследованные записи старого skill: 09-18 state-only noctalia переписала
живые theme templates/LED; 09-20 silent aquamarine rule убрала видимый spawn;
09-21 tmusd cleanup сверкой полного собственного socket перестал матчить чужие
mpv. Это узкие решения конкретных причин, не HOME/bus/process isolation.
Палитру по умолчанию нельзя применять как восстановление без точного baseline.

2026-10-02 wrapper изменён только bounded образом:
root/mkdir/chmod/copy errors fail-closed, materialized symlink copies,
нет фонового age-based global prune; комментарии убирают ложные гарантии.
HOME/bus/UID/process isolation и новый capture backend НЕ добавлены.
Новый wrapper **runtime unverified**: запрещённые владельцем прогоны не делались.
