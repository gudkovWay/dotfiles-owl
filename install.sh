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

# Scoped deployment must not relink unrelated desktop configs or restart services.
if [[ ${1:-} == --omp-document ]]; then
  shift
  exec python3 "$REPO/omp/install-document.py" "$@"
fi

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

# ── Тема курсора и совместимый Xcursor fallback ─────────────────────────────
link local/share/icons/Dot-Dark "$HOME/.local/share/icons/Dot-Dark"
link local/share/icons/Dot-Dark "$HOME/.icons/Dot-Dark"

# ── OMP ────────────────────────────────────────────────────────────────────
# Только отслеживаемые расширения и authored workflow-файлы. Базы, сессии,
# receipts, provider config и секреты ~/.omp остаются локальными.
# Skills-only defaults: a real local config (including models/providers) wins.
link omp/config.yml "$HOME/.omp/agent/config.yml"
link omp/SYSTEM_TEMPLATE.md "$HOME/.omp/agent/SYSTEM_TEMPLATE.md"
link omp/lsp.json "$HOME/.omp/agent/lsp.json"
link omp/extensions/statusline-path.ts "$HOME/.omp/agent/extensions/statusline-path.ts"
link omp/extensions/document-markdown "$HOME/.omp/agent/extensions/document-markdown"
link omp/extensions/prompt-card "$HOME/.omp/agent/extensions/prompt-card"
link omp/extensions/image-links.ts "$HOME/.omp/agent/extensions/image-links.ts"
link omp/extensions/jev-shadow.ts "$HOME/.omp/agent/extensions/jev-shadow.ts"
link omp/herdr-local-files "$HOME/.local/share/omp/herdr-local-files"
# Источник апрува — только установленная root-owned копия, не editable checkout.
# До её явной установки эти ссылки пропускаются; парольный диалог здесь не открываем.
link omp/extensions/owner-approval.js "$HOME/.omp/agent/extensions/owner-approval.js"
while IFS= read -r -d '' f; do
  link "$f" "$HOME/.omp/agent/${f#omp/}"
done < <(git -C "$REPO" ls-files -z -- omp/hooks omp/rules omp/skills omp/skill-bundles omp/jev)
while IFS= read -r -d '' f; do
  link "$f" "$HOME/.agents/${f#agents/}"
done < <(git -C "$REPO" ls-files -z -- agents/skills)

$DRY && exit 0

# Register only the integration just linked, without restarting Herdr or OMP.
if [[ -L "$HOME/.local/share/omp/herdr-local-files" ]] && command -v herdr >/dev/null 2>&1; then
  herdr plugin link "$HOME/.local/share/omp/herdr-local-files" --enabled
fi

systemctl --user daemon-reload
cat <<EOF

Осталось руками (нужен root):

  sudo cp $REPO/system/vader5d@.service $REPO/system/wake-on-space.service /etc/systemd/system/
  sudo cp $REPO/system/99-vader5*.rules /etc/udev/rules.d/
  sudo systemctl daemon-reload && sudo udevadm control --reload

Демон пробуждения ставится своим скриптом (заводит пользователя screenwake):

  sudo $REPO/config/hypr/scripts/wake-on-space-daemon/install.sh

Канал подтверждённых исключений OMP (отдельный системный парольный диалог):

  python3 "$REPO/omp/owner-approval/setup.py"
  bash "$REPO/install.sh"

Включить пользовательские юниты:

  systemctl --user enable --now ai-embed.service ai-journal.timer
  systemctl --user enable --now gamepad-gesture.service noctalia-openrgb-sync.path
EOF
