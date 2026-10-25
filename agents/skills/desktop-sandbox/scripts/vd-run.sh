#!/usr/bin/env bash
# vd-run.sh — XDG-песочница для noctalia/hyprland/тем; границы описаны ниже.
#
# Регрессия 2026-09-18: вторая инстанция noctalia (gamescope --backend headless,
# изолированный стейт, но глобальный XDG_CONFIG_HOME) перезаписала живые шаблоны
# темы (~/.config/hypr/noctalia.lua, alacritty, qt6ct, kdeglobals) — цвета
# живой оболочки и OpenRGB-подсветки скакнули посреди боя.
#
# Usage:
#   vd-run.sh <cmd...>         # изолированные XDG-корни + команда (headless/UI)
#   vd-run.sh --hypr <cmd...>  # то же + вложенный Hyprland; готовность сокетов
#                              # НЕ гарантирует готовность выхода для захвата
#
# Изоляция: четыре XDG-корня + NOCTALIA_STATE_HOME; в cmd свой runtime и снятый
# WAYLAND_DISPLAY, в --hypr runtime общий и выбирается сокет своего compositor.
# HOME, session bus, UID и /proc остаются общими: это НЕ security sandbox.
# Копии конфигов материализуют symlink; абсолютные пути внутри всё ещё требуют аудита.
#
# Артефакты: /tmp/vd-*/  — command.log, hyprland.log, скриншоты клади туда же.
# Артефакты сохраняются; чужие или старые песочницы автоматически не удаляются.
set -uo pipefail

MODE=cmd
if [[ "${1:-}" == "--hypr" ]]; then MODE=hypr; shift; fi
if [[ $# -lt 1 ]]; then sed -n '2,20p' "$0" >&2; exit 2; fi

VD_ROOT=$(mktemp -d /tmp/vd-XXXXXX) || exit 1
if ! mkdir -p "$VD_ROOT"/config "$VD_ROOT"/cache "$VD_ROOT"/state "$VD_ROOT"/share "$VD_ROOT"/run \
        || ! chmod 700 "$VD_ROOT"/run; then
    echo "[vd] не удалось подготовить изолированные XDG-корни: $VD_ROOT" >&2
    exit 1
fi
for d in noctalia hypr; do
    [[ -d "$HOME/.config/$d" ]] || continue
    # Не переносим ссылки на живые файлы в writable-копию конфигурации.
    if ! cp -rL -- "$HOME/.config/$d" "$VD_ROOT/config/"; then
        echo "[vd] не удалось материализовать конфиг $d: $VD_ROOT" >&2
        exit 1
    fi
done

LIVE_RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

export VD_ROOT
export XDG_CONFIG_HOME="$VD_ROOT/config" XDG_CACHE_HOME="$VD_ROOT/cache" \
       XDG_STATE_HOME="$VD_ROOT/state" XDG_DATA_HOME="$VD_ROOT/share" \
       NOCTALIA_STATE_HOME="$VD_ROOT/state/noctalia" \
       AGENT=1 OMPCODE=1
unset HYPRLAND_INSTANCE_SIGNATURE

echo "[vd] песочница: $VD_ROOT" >&2

# Уборка строго по своему PID: ни сокеты общего runtime, ни процессы по имени
# не трогаем — рядом живёт человек и могут идти другие песочницы.
cleanup() {
    [[ -n "${HYPRLAND_PID:-}" ]] || return 0
    kill -0 "$HYPRLAND_PID" 2>/dev/null || return 0
    kill "$HYPRLAND_PID" 2>/dev/null
    # Ограниченное ожидание: не подвешиваем выход, если процесс не отдаёт SIGTERM.
    for _ in $(seq 30); do
        kill -0 "$HYPRLAND_PID" 2>/dev/null || break
        sleep 0.1
    done
    kill -0 "$HYPRLAND_PID" 2>/dev/null || wait "$HYPRLAND_PID" 2>/dev/null
    return 0
}
trap cleanup EXIT

if [[ "$MODE" == "hypr" ]]; then
    # Вложенный Hyprland: aquamarine DRM-сессию не отдаст (seat занят живым),
    # поднимается wayland-бэкендом — окно (класс "aquamarine") на живой сессии.
    # Невидимость спавна: silent-правило windowrules.lua рождает его сразу
    # на special:agent-tests, без фокуса и вспышки; AGENT=1 + hypr-agent-guard
    # остаются подстраховкой. Эта реализация подключается к родительскому Wayland
    # через ОБЩИЙ runtime; это не утверждение о невозможности отдельного runtime.
    if [[ -z "${WAYLAND_DISPLAY:-}" || ! -e "$LIVE_RT/${WAYLAND_DISPLAY:-}" ]]; then
        echo "[vd] --hypr нужен живой WAYLAND_DISPLAY (не запускай через ssh/headless)" >&2
        exit 1
    fi
    export XDG_RUNTIME_DIR="$LIVE_RT"
    # По умолчанию — МИНИМАЛЬНЫЙ конфиг: копия живого (плагины, мониторы,
    # exec-once) роняет вложенную инстанцию SEGV'ом (Hyprland 0.56.2).
    # Свой конфиг: VD_HYPR_CFG=<путь>.
    HYPR_CFG="${VD_HYPR_CFG:-$VD_ROOT/hypr-minimal.conf}"
    VD_HYPR_CFG="${VD_HYPR_CFG:-}"
    [[ -n "$VD_HYPR_CFG" ]] || printf 'monitor=,1280x800@60,0x0,1\n' > "$HYPR_CFG"
    Hyprland -c "$HYPR_CFG" >"$VD_ROOT/hyprland.log" 2>&1 &
    HYPRLAND_PID=$!
    # Готовность — по факту, а не по разнице имён в каталоге: переиспользованное
    # имя wayland-2 или чужой параллельный инстанс дают ложный результат.
    # hyprctl -j instances сообщает реальные pid/instance/wl_socket каждой
    # инстансы; берём ровно запись своего HYPRLAND_PID и подтверждаем, что оба
    # её сокета существуют в общем runtime, а процесс ещё жив.
    SIG=""
    WL=""
    for _ in $(seq 150); do
        entry=$(hyprctl -j instances 2>/dev/null \
            | jq -r --argjson pid "$HYPRLAND_PID" \
                '.[] | select(.pid == $pid) | "\(.instance)\t\(.wl_socket)"' 2>/dev/null \
            | head -1)
        if [[ -n "$entry" ]]; then
            SIG=${entry%%$'\t'*}
            WL=${entry##*$'\t'}
            if [[ -n "$SIG" && -n "$WL" \
                  && -S "$XDG_RUNTIME_DIR/hypr/$SIG/.socket.sock" \
                  && -S "$XDG_RUNTIME_DIR/$WL" ]]; then
                break
            fi
            SIG=""
            WL=""
        fi
        kill -0 "$HYPRLAND_PID" 2>/dev/null || break
        sleep 0.1
    done
    if [[ -z "$SIG" || -z "$WL" ]] || ! kill -0 "$HYPRLAND_PID" 2>/dev/null; then
        echo "[vd] вложенный Hyprland (pid $HYPRLAND_PID) не поднялся — смотри $VD_ROOT/hyprland.log" >&2
        exit 1
    fi
    export HYPRLAND_INSTANCE_SIGNATURE="$SIG"
    export WAYLAND_DISPLAY="$WL"
    echo "[vd] вложенный Hyprland pid=$HYPRLAND_PID sig=$SIG WAYLAND_DISPLAY=$WL" >&2
else
    # Без вложенного Hyprland свой runtime и снятый WAYLAND_DISPLAY;
    # HOME, DISPLAY/Xauthority, UID, /proc и session bus этим не изолированы.
    export XDG_RUNTIME_DIR="$VD_ROOT/run"
    unset WAYLAND_DISPLAY
fi

"$@" > >(tee "$VD_ROOT/command.log") 2>&1
rc=$?
echo "[vd] выход=$rc; артефакты в $VD_ROOT" >&2
exit "$rc"
