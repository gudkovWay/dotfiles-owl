#!/usr/bin/env bash
# Neovim behavior checks under a private HOME/XDG, with no personal IPC or API keys.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${NVIM_TEST_CONFIG:-$REPO/config/nvim}"
PLUGINS="${NVIM_TEST_PLUGINS:-${XDG_DATA_HOME:-$HOME/.local/share}/nvim/lazy}"
RENDERER="${NVIM_TEST_RENDERER:-$REPO/.superpowers/deps/render-markdown.nvim}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/dotfiles-owl-nvim.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

cases=("${@:-reload}")
for scenario in "${cases[@]}"; do
  case "$scenario" in reload|security|markdown) ;; *) echo "Unknown scenario: $scenario" >&2; exit 2 ;; esac
  home="$TMP/$scenario"
  mkdir -p "$home" "$home/.config" "$home/.local/share/nvim/lazy"
  cp -aL "$CONFIG" "$home/.config/nvim"
  if [[ $scenario != reload ]]; then
    [[ -d "$PLUGINS/lazy.nvim" && ( -d "$PLUGINS/render-markdown.nvim" || -d "$RENDERER" ) ]] || {
      echo 'Missing installed Neovim plugins; prepare the pinned dependencies first' >&2; exit 1;
    }
    for plugin in "$PLUGINS"/*; do
      [[ -d "$plugin" ]] && cp -a "$plugin" "$home/.local/share/nvim/lazy/"
    done
    if [[ ! -e "$home/.local/share/nvim/lazy/render-markdown.nvim" ]]; then
      cp -a "$RENDERER" "$home/.local/share/nvim/lazy/render-markdown.nvim"
    fi
  fi
  env -i HOME="$home" XDG_CONFIG_HOME="$home/.config" \
    XDG_DATA_HOME="$home/.local/share" XDG_STATE_HOME="$home/.local/state" \
    XDG_CACHE_HOME="$home/.cache" PATH="$PATH" TERM=xterm-256color \
    NVIM_TEST_REPO="$REPO" NVIM_TEST_TMP="$home" \
    nvim --clean --headless -l "$REPO/tests/nvim/$scenario.lua"
  printf 'OK (nvim-smoke): %s\n' "$scenario"
done
