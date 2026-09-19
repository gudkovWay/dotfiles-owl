#!/usr/bin/env bash
# Симлинкует конфиги из репозитория в ~/.config и остальные места.
#
# Идемпотентно: гонять можно сколько угодно. Настоящий файл на месте ссылки
# никогда не затирается — про такой печатается WARN, и разбираешься руками.
# Системные юниты и udev-правила не ставятся: они требуют root, для них
# печатается список команд.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
DRY=false
[[ ${1:-} == --dry-run ]] && DRY=true

link() {                       # link <источник в репе> <куда>
  local src="$REPO/$1" dst="$2"
  if [[ ! -e $src ]]; then
    echo "skip  $1 — нет в репозитории"; return
  fi
  if [[ -e $dst && ! -L $dst ]]; then
    echo "WARN  $dst — настоящий файл, не ссылка; пропускаю, разберись руками"
    return
  fi
  $DRY && { echo "link  $dst -> $src"; return; }
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "link  $dst"
}

# ── ~/.config ──────────────────────────────────────────────────────────────
while IFS= read -r -d '' f; do
  link "$f" "$CONFIG/${f#config/}"
done < <(git -C "$REPO" ls-files -z -- config)

# ── плагины и скрипты из отдельных публичных реп ───────────────────────────
# Подтягиваются сабмодулями: git submodule update --init
link vendor/noctalia-gamepad-launcher/plugin \
     "$CONFIG/hypr/noctalia-plugins/gamepad-launcher"
for s in gamepad-gesture games-open games-sync pad-sniff; do
  link "vendor/noctalia-gamepad-launcher/scripts/$s.py" "$CONFIG/hypr/scripts/$s.py"
done
link vendor/noctalia-openrgb-sync/noctalia-openrgb-sync.sh \
     "$CONFIG/hypr/scripts/noctalia-openrgb-sync.sh"

# ── systemd --user ─────────────────────────────────────────────────────────
for u in "$REPO"/systemd/user/*; do
  link "systemd/user/$(basename "$u")" "$CONFIG/systemd/user/$(basename "$u")"
done
link vendor/noctalia-gamepad-launcher/systemd/gamepad-gesture.service \
     "$CONFIG/systemd/user/gamepad-gesture.service"
for u in path service; do
  link "vendor/noctalia-openrgb-sync/systemd/noctalia-openrgb-sync.$u" \
       "$CONFIG/systemd/user/noctalia-openrgb-sync.$u"
done

# ── ~/.local/bin и ~/.claude ───────────────────────────────────────────────
for b in "$REPO"/local/bin/*; do
  link "local/bin/$(basename "$b")" "$HOME/.local/bin/$(basename "$b")"
done
link claude/settings.json "$HOME/.claude/settings.json"
link claude/CLAUDE.md     "$HOME/.claude/CLAUDE.md"
link claude/hooks         "$HOME/.claude/hooks"

$DRY && exit 0

systemctl --user daemon-reload
cat <<EOF

Осталось руками (нужен root):

  sudo cp $REPO/system/vader5d@.service $REPO/system/wake-on-space.service /etc/systemd/system/
  sudo cp $REPO/system/99-vader5*.rules /etc/udev/rules.d/
  sudo systemctl daemon-reload && sudo udevadm control --reload

Демон пробуждения ставится своим скриптом (заводит пользователя screenwake):

  sudo $REPO/config/hypr/scripts/wake-on-space-daemon/install.sh

Включить пользовательские юниты:

  systemctl --user enable --now ai-embed.service ai-journal.timer
  systemctl --user enable --now gamepad-gesture.service noctalia-openrgb-sync.path
EOF
