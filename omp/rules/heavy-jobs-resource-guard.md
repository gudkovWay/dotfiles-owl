---
alwaysApply: true
description: Один тяжёлый запуск между всеми OMP-сессиями: атомарный flock, обязательный systemd scope с CPU/RAM/swap/time caps, preflight и fail-closed. Защита от повторения desktop-freeze, не гарантия отсутствия kernel/driver panic.
---

# Heavy jobs: one host-wide slot, CPU and memory caps

Действует во всех OMP-сессиях, репозиториях, worktree и агентах на машине.
Право запустить тест определяется `rule://no-autotests`; это правило
определяет только безопасный способ разрешённого запуска.

1. **Тяжёлые задания:** любой test runner, test collection с импортами,
   typecheck, prepare, build, bundler, dev/test server, browser E2E и установка
   зависимостей/браузеров. Примеры, не allowlist: Vitest, Playwright, Jest,
   pytest, Cargo/Go tests, vue-tsc/tsc, Nuxt, esbuild, npm/pnpm/yarn/bun install.
   Все дочерние процессы и setup/teardown относятся к тому же заданию.
2. **Preflight перед каждым запуском:** `free -h`, `/proc/meminfo`, `nproc`,
   `pgrep -af 'vitest|playwright|jest|pytest|vue-tsc|nuxt|esbuild|tsc|cargo|go test|npm.*(install|ci)|pnpm.*install|yarn.*install|bun.*install'`
   плюс фактический раннер/сервер/компилятор, обнаруженный в репе, и
   `systemctl --user list-units --all 'omp-heavy-job.scope'`.
   Код 1 у pgrep означает отсутствие совпадений, не сбой bootstrap.
   Исключать только доказанно собственный preflight-процесс, не реальные
   задания других сессий. При уже работающем тяжёлом задании — не запускать
   новое, не останавливать чужое; сообщить конфликт.
3. **Порог RAM:** `MemAvailable` не меньше 10 GiB (10485760 KiB):
   6 GiB hard cap + минимум 4 GiB резерва. Проверять текущее значение, не
   полагаться на total RAM, свободный swap или прежний вывод.
   При недостатке памяти — сообщить измерение и остановиться.
4. **Атомарная сериализация:** все сессии владельца используют один
   `/run/user/1000/omp-heavy-jobs.lock` и один `omp-heavy-job.scope`.
   По умолчанию `flock --exclusive --nonblock --conflict-exit-code 75`
   удерживается весь запуск. Допустимо явно выбрать ограниченное синхронное
   ожидание до 60 секунд; это не retry и не фоновая очередь. После захвата
   lock выполнить свежий preflight; чужие неконтролируемые нагрузки блокируют.
   Не удалять lock-файл: это создаёт другой inode и обход блокировки.
   Если scope остался активным после выхода команды, новый запуск запрещён.
5. **Обязательные caps всего дерева процессов:** CPUQuota=200% (время двух
   CPU, не 200% всей машины), CPUWeight=20, MemoryHigh=4G, MemoryMax=6G,
   MemorySwapMax=0, TasksMax=256, IOWeight=20, RuntimeMaxSec=10min,
   OOMPolicy=kill. `nice -n 10` снижает приоритет; сам по себе caps не заменяет.
   Для Node сохранить нужные NODE_OPTIONS, ограничив V8 heap максимумом
   2048 MiB на процесс; меньший существующий лимит не повышать. Heap cap
   не заменяет общий MemoryMax. Не менять постоянные конфиги репы ради caps.
6. **Канонический запуск** из cwd целевого worktree; заменить только
   `<native-command-and-filtered-args>` на обнаруженную штатную команду:

   ```sh
   flock --exclusive --nonblock --conflict-exit-code 75 /run/user/1000/omp-heavy-jobs.lock \
     systemd-run --user --scope --unit=omp-heavy-job --collect --expand-environment=no \
       -p CPUQuota=200% -p CPUWeight=20 \
       -p MemoryHigh=4G -p MemoryMax=6G -p MemorySwapMax=0 \
       -p TasksMax=256 -p IOWeight=20 -p RuntimeMaxSec=10min -p OOMPolicy=kill \
       -- nice -n 10 <native-command-and-filtered-args>
   ```

   Обычный запуск выполнять синхронно; без `&`, nohup, async, нескольких
   agent sessions или параллельных batch runs. Исключение — явно разрешённая
   конечная owned UI-сессия ниже. Deadline инструмента не короче scope lifetime
   + время завершения. Все потомки остаются в том же capped scope:
   без remote daemon, другого systemd unit или внешнего контейнера.
7. **Fail closed:** нет user bus, flock, cgroup v2 с cpu/memory/pids
   controllers, применяемых caps или доступного scope — остановиться и
   сообщить блокер до запуска workload. Нет uncapped fallback, sudo-обхода,
   тихой смены backend или повышения лимитов.
8. **Fail-fast:** OOM/resource kill, таймаут, сбой установки/подготовки/scope
   прекращает попытку до новой явной просьбы человека. Не повторять
   эквивалентный запуск с большим heap/RAM/time cap или другим test pool.
   Обычные assertion failures обрабатываются по `rule://no-autotests`.

## Установленный общий исполнитель

`/home/q/.config/worktrunk/projects/guarded-run -- <native command>` применяет
этот контракт. `--dry-run` печатает команду без workload; `--wait 0..60`
ограничивает ожидание lock. Для deps/env/dev использовать штатные Worktrunk
aliases; caps не копировать в каждый launcher. Перед workload исполнитель
проверяет реальные cgroup caps control-plane командой. Lock удерживается до
завершения scope; краткое наблюдение teardown не повторяет workload.

UI-профиль держит server и browser в одном scope весь конечный сценарий.
Для многоходового CDP допускается только явно разрешённый owned supervisor,
с тем же lock/caps/deadline и остановкой всего своего дерева. Не оставлять
общий dev/browser daemon, не выполнять рядом другие тяжёлые проверки;
сначала закрыть UI-сессию и освободить slot.


Caps проверяются штатными systemd/cgroup-инструментами на лёгкой
control-plane команде, без нагрузочного/OOM-эксперимента. Caps уменьшают риск
resource contention; не гарантируют защиту от всех kernel/GPU/driver сбоев
и не ограничивают процессы, сознательно запущенные вне guarded scope.
