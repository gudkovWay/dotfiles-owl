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
# экранами, которые нечем зажечь, хуже, чем проснуться не от той клавиши.
#
# ПОЧЕМУ ДЕМОН, А НЕ БИНД. Пока DPMS выключен, Hyprland не обрабатывает бинды
# вовсе — проверено на живой сессии: сабмап во тьме активен, бинд на пробел в
# нём зарегистрирован, нажатие не делает ничего (ни Lua-колбэк, ни exec_cmd),
# а при зажжённых экранах тот же бинд срабатывает мгновенно. Отсюда и evdev:
# демон читает клавиатуру напрямую, мимо композитора.
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
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/monitors-waker.pid"

# Убиваем именно своего ждуна: pid из файла и только если по этому pid
# действительно он — за время сна номер могли переиспользовать.
stop_waker() {
    local pid
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
        setsid "$WAKER" >/dev/null 2>&1 &
        echo $! > "$PIDFILE"
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
    hyprctl eval 'hl.dispatch(hl.dsp.dpms("on"))' >/dev/null
    stop_waker
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
