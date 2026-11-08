#!/usr/bin/env bash
# Гасит и зажигает мониторы, не трогая раскладку окон.
#
#   monitors.sh off      погасить
#   monitors.sh on       зажечь
#   monitors.sh toggle   переключить (на хоткей)
#   monitors.sh state    печатает on или off
#
# Погашенные экраны будит только пробел. Ловит его wake-on-space.py — клиент
# демона, который читает клавиатуру под отдельным пользователем (см. ниже).
# Если демон не отвечает, скрипт честно откатывается на «будит любая клавиша»
# средствами Hyprland и говорит об этом уведомлением: остаться с тёмными
# экраны, которые нечем зажечь, хуже, чем проснуться не от той клавиши.
#
# Вместе с экранами гасится RGB-подсветка: wake-on-space.py сразу ПЕРЕД dpms
# off ставит маркер-файл (${XDG_RUNTIME_DIR:-/tmp}/screen-off-rgb.lock, путь
# переопределяется SCREEN_OFF_RGB_LOCK) и зовёт обычный sync палитры —
# noctalia-openrgb-sync.sh видит маркер и выдаёт 0%; любой фоновый sync во
# тьме делает то же. При любом пробуждении маркер снимается и делает полный
# ре-синк — цвет заново берётся из палитры, хранить «прежнее» состояние не
# нужно. `on` ниже делает то же самое: ждун убит сигналом и маркер снять не
# успел, поэтому on снимает его сам после `dpms on`. Запасной режим (демон
# молчит, будит любая клавиша) подсветку не трогает: будильщика нет, и
# возвращать яркость было бы некому.
#
# ПОЧЕМУ ДЕМОН, А НЕ БИНД. Пока DPMS выключен, Hyprland не обрабатывает бинды
# вовсе — проверено на живой сессии: сабмап во тьме активен, бинд на пробел в
# нём зарегистрирован, нажатие не делает ничего (ни Lua-колбэк, ни exec_cmd),
# а при зажжённых экранах тот же бинд срабатывает мгновенно. Отсюда и evdev:
# демон читает клавиатуру напрямую, мимо композитора.
#
# ПОЧЕМУ ЮНИТ, А НЕ `setsid &`. Noctalia запускает команды панели в
# transient-юните (launch_apps_as_systemd_services), и по завершении юнита
# systemd вычищает его cgroup целиком — вместе с фоновым ждуном: setsid рвёт
# сессию и группу процессов, но из cgroup не выносит. Оставленный так ждун
# умирал сразу после гашения (экраны тёмные, пробел мёртв), а его предсмертный
# `dpms off` мог прилететь даже после чужого `on`. Поэтому ждун поднимается
# собственным юнитом через systemd-run — он сиблинг вызывающему, а не потомок,
# и cgroup вызывающего его не заберёт. Фолбэк на старый путь — для запуска
# там, где user-менеджер недоступен.
#
# ЧТОБЫ РАБОТАЛ ПРОБЕЛ, нужен доступ к /dev/input/event*, а узлы клавиатур
# лежат root:input. Выдавать этот доступ себе (правилом с uaccess) нельзя:
# тогда читать все нажатия сможет любой процесс, запущенный от твоего имени.
# Поэтому клавиатуру слушает демон под отдельным системным пользователем
# screenwake, а сессия получает от него по сокету одно слово. Ставится один
# раз, из-под root:
#
#   sudo ~/.config/hypr/scripts/wake-on-space-daemon/install.sh
#
# Проверить, отвечает ли демон: `wake-on-space.py --probe` (код 0 — да).
#
# Почему DPMS, а не отключение монитора. `hyprctl keyword monitor …,disable`
# убирает монитор из вывода — Hyprland переносит его рабочие столы на
# оставшийся и перестраивает окна, а при включении обратно раскладка уже не та.
# `dispatch dpms` гасит только сигнал: композитор продолжает считать монитор
# подключённым, окна остаются где были.
#
# Лок-скрин отсюда не запускается: гашение и блокировка — разные вещи, а
# hyprlock/hypridle в системе и не стоят. Свой таймаут простоя (в Noctalia)
# скрипт не трогает — он отсчитывает бездействие и сработает по-своему.
#
# Конфиг здесь на Lua, и старый `hyprctl keyword` на нём не работает вовсе:
# отвечает «keyword can't work with non-legacy parsers. Use eval.» и молча
# ничего не меняет. Всё на лету ставится через `hyprctl eval` тем же
# `hl.config`/`hl.dispatch`, каким написан сам конфиг.
#
# Форма вызова dpms подобрана перебором, и ни одна очевидная не работает.
# `hyprctl dispatch dpms off` на Lua-конфиге падает разбором («')' expected
# near 'off'») — и через сокет напрямую тоже, старый путь тут мёртв целиком.
# `hl.dsp.dpms("off")` отвечает «ok» и НЕ ДЕЛАЕТ НИЧЕГО: это не вызов, а
# конструктор диспетчера, его ещё надо передать в `hl.dispatch`. Ошибка на
# другой команде это и подсказывала — «expected a dispatcher (e.g.
# hl.dsp.window.close())», — но при верном синтаксисе молчаливое «ok» ничем не
# отличается от сделанного, и проверять приходится по `dpmsStatus`.
set -euo pipefail

WAKER="$(dirname "$(readlink -f "$0")")/wake-on-space.py"
RGB_SYNC="$(dirname "$(readlink -f "$0")")/noctalia-openrgb-sync.sh"
# Экстра-переход тьмы (кулеры, сторож, обои) — тот же скрипт, что зовёт клиент
# wake-on-space.py. Здесь он нужен для пути «on без клиента»: ждуна убивают
# сигналом, и его finally не выполняется, поэтому возврат делает кто-то ещё.
EXTRAS="$(dirname "$(readlink -f "$0")")/screen-off-extras.sh"
# Маркер тьмы: тот же путь, что в wake-on-space.py и noctalia-openrgb-sync.sh.
# Существует, пока экраны погашены, и держит подсветку на 0%.
SCREEN_OFF_RGB_LOCK="${SCREEN_OFF_RGB_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/screen-off-rgb.lock}"
 PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/monitors-waker.pid"

# Убиваем именно своего ждуна: pid из файла и только если по этому pid
# действительно он — за время сна номер могли переиспользовать.
stop_waker() {
    local pid
    # Юнит прежде всего: свежий ждун живёт там, а pid в pidfile может быть
    # устаревшим (systemd уже прибрал процесс) или вообще чужим (переиспрольз.
    # pid). stop по отсутствующему юниту безвреден.
    systemctl --user stop monitors-waker >/dev/null 2>&1 || true
    [ -r "$PIDFILE" ] || return 0
    pid=$(cat "$PIDFILE" 2>/dev/null) || true
    if [ -n "${pid:-}" ] && grep -qa "wake-on-space.py" "/proc/$pid/cmdline" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
}

# mouse_move_enables_dpms будит движением и кликом мыши, key_press_enables_dpms
# — любой клавишей. Оба выключены и здесь, и в config/misc.lua: иначе экраны
# загораются от любого шевеления, в том числе от того самого нажатия, которым
# их только что погасили.
wake_by_any_key() {
    hyprctl eval "hl.config({misc = {mouse_move_enables_dpms = false,
                                     key_press_enables_dpms  = $1}})" >/dev/null
}

off() {
    stop_waker
    if "$WAKER" --probe 2>/dev/null; then
        wake_by_any_key false
        # Гасит сам клиент — уже после того, как демон подтвердил, что открыл
        # клавиатуры. Гасить раньше нельзя: в промежутке пробел потерялся бы.
        # Он же и зажигает по пробелу, поэтому `on` ему не нужен.
        #
        # Юнит, а не `setsid &`: см. шапку. PATH передаётся явно — юнит
        # наследует окружение user-менеджера, а не вызывающего скрипта, и
        # ждуну нужны hyprctl и openrgb из PATH.
        if systemd-run --user --unit=monitors-waker --collect \
                -E "PATH=$PATH" \
                "$WAKER" >/dev/null 2>&1; then
            local pid="" i
            for i in 1 2 3 4 5; do
                pid="$(systemctl --user show monitors-waker -p MainPID --value 2>/dev/null)" || true
                if [ "$pid" -gt 0 ] 2>/dev/null; then
                    echo "$pid" > "$PIDFILE"
                    break
                fi
                pid=""
                sleep 0.1
            done
        else
            setsid "$WAKER" >/dev/null 2>&1 &
            echo $! > "$PIDFILE"
        fi
    else
        wake_by_any_key true
        hyprctl eval 'hl.dispatch(hl.dsp.dpms("off"))' >/dev/null
        noctalia msg notification-show "Мониторы" \
            "Демон пробуждения не отвечает — экраны разбудит любая клавиша, не только пробел" \
            >/dev/null 2>&1 || true
    fi
}

# dpmsStatus возвращается в true не мгновенно: мониторам нужно пересинхрониться,
# на этих двух — пара секунд. Так что сразу после `on` проверка `state` ещё
# может честно ответить off; это не ошибка.
on() {
    # Сначала ждуна — насмерть и всему его cgroup. У умирающего ждуна может
    # оставаться в полёте `dpms off`: осиротевший hyprctl-наследник способен
    # отправить его уже ПОСЛЕ чужого `on`, и экраны останутся тёмными.
    # SIGKILL всему cgroup обрывает неотправленное; уже улетевшее прилетит
    # раньше, чем мы зажжём. stop_waker затем синхронно убирает юнит.
    systemctl --user kill --kill-who=all --signal=SIGKILL monitors-waker \
        >/dev/null 2>&1 || true
    stop_waker
    hyprctl eval 'hl.dispatch(hl.dsp.dpms("on"))' >/dev/null
    # Маркер тьмы мог остаться от убитого сигналом (SIGKILL) ждуна, который
    # снять его не успел, — прибираем, иначе восстанавливающий sync выдаст 0%.
    rm -f "$SCREEN_OFF_RGB_LOCK"
    # A separate oneshot survives this caller and does not delay display wake.
    if ! timeout 2 systemctl --user start --no-block night-mode-restore.service; then
        printf 'monitors: could not enqueue night-mode restore\n' >&2
    fi
    # Экстра-переход тот же, что делает клиент при пробуждении: сторож —
    # насмерть, кулеры — под BIOS-кривую, обои — обратно. Сюда мы попадаем
    # вместо клиента (его убили сигналом выше), поэтому возврат делаем сами.
    # Таймаут — чтобы зависший экстра-скрипт не задержал пробуждение.
    timeout 5 "$EXTRAS" wake >/dev/null 2>&1 || true
    # Подсветка погашена до 0% гашением, а ждун только что убит сигналом и сам
    # вернуть её не мог — возвращаем сами. Экран уже горит, поэтому ждать
    # завершения sync можно: секунд до десятков не жалко, зато команда не
    # выйдет раньше восстановления — её transient-юнит/процессная группа
    # при выходе не убьют синк на полпути. Перегон с чужими запусками sync
    # исключён flock'ом в нём.
    "$RGB_SYNC" >/dev/null 2>&1 </dev/null
}

state() {
    # dpmsStatus: true — горит, false — погашен. Хватит первого монитора:
    # гасим всегда все разом.
    hyprctl -j monitors | grep -o '"dpmsStatus": *[a-z]*' | head -1 |
        grep -q true && echo on || echo off
}

case "${1:-toggle}" in
    off)    off ;;
    on)     on ;;
    toggle) [ "$(state)" = on ] && off || on ;;
    state)  state ;;
    *)      echo "monitors.sh [off|on|toggle|state]" >&2; exit 1 ;;
esac
