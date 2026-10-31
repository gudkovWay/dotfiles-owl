---
alwaysApply: false
description: Общий buffered/elastic resource guard всех OMP-сессий: безопасный допуск, очередь, мягкое давление и scoped goal jobs.
---
# Общий ресурсный исполнитель

Все тяжёлые локальные команды запускаются через `/home/q/.config/worktrunk/projects/guarded-run`. Авторизация tests/typecheck/подготовки — rule://no-autotests и skill://repository-testing. Этот контракт не даёт самостоятельного разрешения на новые расходы, production build или desktop.

Обычный конечный запуск: `guarded-run --need 3G --wait 60 -- <native command>`. `--need` означает ожидаемый пик до дополнительного запаса. Legacy `--memory 6G` — точный fixed hard maximum без второго автоматического запаса. Отсутствие размера использует небольшой стартовый expected peak, НЕ весь свободный остаток. Для известных workloads использовать measured peaks; не занижать потребность ради допуска.

PID-профиль: default `--tasks 256`, Nuxt preview/owned UI — `--tasks 512`.
Считать процессы и потоки вместе; сумма обещанных caps не выше общего parent
`TasksMax=2048`. Недостаток PID-бюджета — deferred, не запуск с заниженным cap.
Nested job переиспользует свой профиль и не вправе расширять его.

`--elastic --ceiling SIZE` явно разрешает контроллеру повышать MemoryMax живого дерева до этого ceiling после каждого нового допуска. Ceiling не резервируется заранее. Fixed jobs не изменяются. Нельзя обходить guard ручным systemctl/cgroup write, менять pool после OOM или делегировать uncapped выполнение.

## Общий accounting

- Один стабильный `/run/user/<uid>/omp-heavy-jobs.lock`, один реестр `omp-heavy-jobs/registry.json`; lock только на admission/reconciliation/publication, не на workload. Не удалять lock и не заменять inode.
- Свежий A=MemAvailable, не MemFree/total RAM/swap. Цель host floor=1GiB плюс динамический jitter J на недавние внешние падения и время реакции.
- H — сумма неиспользованных обещаний MemoryMax, включая launching и pending growth. Reclaimable file cache не считать гарантированно потреблённой частью резерва. F=max(0,A-1GiB-J-H).
- Новый полный r или дельта расширения должны помещаться в F. Publish reservation ДО запуска/расширения, затем readback реальных caps. Не обещать одни байты двум jobs.
- Запас задачи динамический, зависит от expected peak/истории/роста/доступной ёмкости и очереди. Максимума дополнительного запаса 2GiB нет. Не отдавать весь остаток первой задаче и не запускать заведомо недообеспеченную.
- Общий бюджет может увеличиваться для свежих admissions; старый малый epoch не замораживает доступную память на всю ночь. Не уменьшать живые caps при внешнем давлении или одном падении RSS.
- Проверять PID вместе со start-time, launcher и populated cgroup. Живой scope сохраняет reservation после смерти одного PID. Unknown scope/corrupt registry/missing accounting — fail closed.
- До 8 local jobs как backstop; число сабагентов регулируется отдельно. Parent pids=2048, admission учитывает сумму обещанных child caps, а не только текущий pids.current. CPU делится весами в общем ceiling max(1,nproc-2) логических CPU; CPUWeight/IOWeight=20, nice=10, swap=0. Это не новая квота на каждый агент поверх общей.
- Внутри реального scope проверить cgroup v2 CPU/memory/pids, systemd и реестр до exec. Nested commands переиспользуют резерв; не создают второй job и не увеличивают его самостоятельно. Canonical writable environment блокируется на весь job; общие writable deps/generated outputs запрещены.
- Старые живые scopes сначала естественно завершаются; cutover не меняет их caps. Unmanaged процесс по имени сам по себе не запрещает весь ПК: внешняя RAM уже входит в A, CPU конкурирует по weights. Не трогать чужие процессы.

## Мягкая реакция на внешнюю нагрузку

Падение MemAvailable ниже цели НЕ означает kill-all, остановку всех полезных jobs или агрессивное снижение MemoryMax. Сначала не допускать новые jobs/необязательный рост. Логический запас — не физически занятые страницы: снятие обещания само не увеличивает MemAvailable.

Ядро возвращает page cache. Допускается ограниченный best-effort memory.reclaim только своего cgroup, только в пределах наблюдаемого file cache, с swappiness=0, малыми порциями и cooldown. EAGAIN/unsupported/permission failure не превращать в повторное добивание или убийство jobs. Нельзя глобальный drop_caches, принудительный GC/kill чужих программ или отбор анонимной памяти. Нет возвращаемого cache — сохранять мягкое ожидание/pressure.

1GiB — целевой admission floor, не абсолютная гарантия против любой внешней программы. MemoryHigh даёт reclaim/throttle, но не гарантированную паузу; MemoryMax может привести к OOM. Не обещать «никогда не упадёт».

## Эластичное расширение

Контроллер вне job наблюдает working memory, memory.events и pressure и действует ДО исчерпания emergency headroom. Одно заполнение cache не доказывает потребность роста. При расширении повторно проверить authority/ownership и общий accounting, publish pending delta, увеличить parent при необходимости, затем child MemoryMax, подтвердить kernel values, скорректировать MemoryHigh и commit новую revision.

При сбое pending/уже применённая дельта остаётся зарезервированной до reconciliation. Слепой rollback hard cap вниз опасен. Чужие резервы не отбирать. Если дельты нет, новые admissions ждут; checkpoint/degrade только если программа поддерживает. Расширение не продлевает runtime или goal и не является retry после OOM.

Для fixed Node heap<=75% hard maximum; сохранить меньший пользовательский heap и остальные NODE_OPTIONS. Для explicit elastic Node heap ceiling заранее рассчитывается от разрешённой границы роста, с native headroom. Это не выделяет всю память и не резервирует ceiling. Несколько процессов делят общий cgroup; cgroup growth сам по себе не меняет уже установленный V8 heap. Нулевой heap и CLI override выше разрешённого запрещены.

## Очередь и lifecycle

Занятость RAM/environment/GPU/слотов — queued/deferred с конкретной причиной. Обычный CLI ждёт конечный --wait 60; не повторять эквивалентный workload после infrastructure/OOM/timeout. Для долгого ожидания использовать resource_job с действующим broker-issued goal ticket, а не бесхозный nohup.

Для той же неизменённой команды разрешены до двух admission-окон по 60 секунд
в ОДНОМ queued job: `--wait 60 --admission-windows 2`. Default остаётся одним
окном. Это не повтор workload: до exec reservation и запуска ещё нет.
После исчерпания нужен машинный `event=deferred, phase=admission,
admitted=false, workload_started=false`; один exit 75 не доказывает never-started.
Не пересоздавать job бесконечно, не снимать caps и не просить владельца
«освободить RAM». Deferred сохраняет pending и точный prerequisite.
`event=workload_start`, admitted/completed, unknown accounting или настоящий
OOM/timeout/infra failure не допускают этого продолжения.

Deferred exit 75 проходит через launcher без превращения в успешный запуск.
При teardown сначала остановить populated owned scope, затем ограниченно
дождаться/reap своего launcher, проверяя PID/start-time. Резерв снимать только
после подтверждённого empty scope. Уже inactive и собранный systemd cgroup —
нормальное завершение; исчезнувший accounting живого scope — fail closed.
PID peak/events сохранять отдельно от memory peak, если они реально наблюдались.

Goal job имеет устойчивый job_id, submit/status/wait/cancel, проверяемого owner и автоматический cleanup. RPC timeout не отменяет запрос и не требует нового submit. Main делает независимую работу либо ждёт события. ETA — прогноз, НЕ срок отказа: ошибка ETA не вызывает owner approval. Для неизвестного workload ETA unknown. Deadline goal/runtime/cleanup остаётся действительным пределом.

Fairness — между goal, с aging крупных запросов. Все необходимые locks получать согласованно; ожидание своего lock — dependency error для перепланирования. Принципиально невозможный запрос не держать в вечной очереди. GPU/VRAM отдельно от RAM: game/GPU lease не запрещает CPU-only typecheck.

Обычный runtime 600s. `--approved-double` только для явно согласованной повторной попытки удваивает fixed memory и runtime; no-timeout только для прямо запрошенной конкретной сборки. Флаг не доказывает approval. Long wait/runtime требуют broker ticket, соответствующего cwd, parent PID/start, scope и expiry; текст/brief/JSON без проверки broker не авторизуют.

Внешний deadline обязан покрыть admission+runtime+cleanup: не менее 700s для одного окна 60s/runtime600, не менее 800s для двух окон. UI/game/browser только в разрешённой owned поверхности, не на личном desktop по умолчанию. Неупражнённый runtime — unverified. OOM/resource kill/timeout/infra failure прекращают попытку; допустимая конечная retry ladder должна быть согласована заранее в goal, а не выдумана после сбоя.
