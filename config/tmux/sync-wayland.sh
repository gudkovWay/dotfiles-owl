#!/bin/sh
# Синхронизация WAYLAND_DISPLAY (и XDG_RUNTIME_DIR) в окружении tmux.
#
# Сервер стартует continuum'ом при логине — ещё без Wayland-переменных, а
# update-environment при SSH-attach (пульт remote-ai-manage) вдобавок вычищает
# WAYLAND_DISPLAY из окружения сессии. Без неё omp не читает картинку из
# клипборда: arboard не находит Wayland-бэкенд, X11-путь мёртв, и Ctrl+V
# отвечает «Clipboard is empty».
#
# Скрипт находит свежий wayland-сокет и прописывает переменные в глобальное
# окружение сервера и во все сессии. Запускается из tmux.conf: при загрузке
# конфига и на каждый client-attached (переживает рестарт Hyprland — сокет
# ищется заново, а не зашит в конфиг).

uid="$(id -u)"
runtimedir="${XDG_RUNTIME_DIR:-/run/user/$uid}"

# Свежий сокет первым: после краша Hyprland в /run/user может остаться мёртвый
# wayland-N, живой создастся позже.
wl=""
for d in $(ls -t "$runtimedir"/wayland-* 2>/dev/null); do
	[ -S "$d" ] && wl="${d##*/}" && break
done

if [ -n "$wl" ]; then
	tmux set-environment -g WAYLAND_DISPLAY "$wl" 2>/dev/null
	tmux list-sessions -F '#S' 2>/dev/null | while IFS= read -r s; do
		tmux set-environment -t "$s" WAYLAND_DISPLAY "$wl" 2>/dev/null
	done
fi

# На случай сервера, стартованного вовсе без XDG_RUNTIME_DIR (arboard и
# wl-клиенты без него не найдут сокет даже с WAYLAND_DISPLAY).
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$uid" ]; then
	tmux set-environment -g XDG_RUNTIME_DIR "/run/user/$uid" 2>/dev/null
fi
