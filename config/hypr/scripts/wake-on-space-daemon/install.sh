#!/usr/bin/env bash
# Ставит демон пробуждения по пробелу. Запускать из-под root:
#
#   sudo ~/.config/hypr/scripts/wake-on-space-daemon/install.sh
#
# Идемпотентно: повторный запуск обновляет файлы и перезапускает службу. Он же
# единственный способ обновить живой демон — файл в /usr/local/lib
# принадлежит root намеренно, чтобы процессы сессии не могли его переписать.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "нужен root: sudo $0" >&2; exit 1; }

SRC=$(dirname "$(readlink -f "$0")")

# Системный пользователь без дома и шелла: всё, что у него есть, — ACL на
# чтение клавиатур.
id -u screenwake >/dev/null 2>&1 ||
    useradd --system --no-create-home --shell /usr/bin/nologin \
            --comment "wake-on-space daemon" screenwake

install -Dm755 "$SRC/daemon.py"              /usr/local/lib/wake-on-space/daemon.py
install -Dm644 "$SRC/99-wake-on-space.rules" /etc/udev/rules.d/99-wake-on-space.rules
install -Dm644 "$SRC/wake-on-space.service"  /etc/systemd/system/wake-on-space.service

# К уже подключённым устройствам правило применяется только по trigger.
udevadm control --reload
udevadm trigger --subsystem-match=input --action=change

systemctl daemon-reload
systemctl enable --now wake-on-space.service
systemctl restart wake-on-space.service

echo
echo "--- клавиатуры, доступные демону ---"
for dev in /dev/input/event*; do
    getfacl -p "$dev" 2>/dev/null | grep -q "^user:screenwake:r--" && echo "  $dev"
done

echo
echo "--- служба ---"
systemctl --no-pager --full status wake-on-space.service | head -12
