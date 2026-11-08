#!/usr/bin/env bash
# Same installed OMP/Bun fixture convention as the document extension checks.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUN="$(command -v bun)"
if [[ -z "${OMP_MODULES:-}" ]]; then
  OMP_CLI="$(readlink -f "$(command -v omp)")"
  case "$OMP_CLI" in
    */packages/coding-agent/dist/cli.js) OMP_MODULES="${OMP_CLI%/packages/coding-agent/dist/cli.js}/node_modules" ;;
    *) OMP_MODULES="${OMP_CLI%/@oh-my-pi/pi-coding-agent/dist/cli.js}" ;;
  esac
fi
TMP="$(mktemp -d "${TMPDIR:-/tmp}/omp-inbox-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home" "$TMP/config" "$TMP/agent" "$TMP/project/tests" "$TMP/project/omp/extensions"
export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_DATA_HOME="$TMP/data"
export XDG_STATE_HOME="$TMP/state" XDG_CACHE_HOME="$TMP/cache" PI_CODING_AGENT_DIR="$TMP/agent"
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
cp -R "$REPO/omp/extensions/inbox" "$TMP/project/omp/extensions/"
cp "$REPO/tests/omp-inbox-checks.ts" "$REPO/tests/omp-inbox-host.ts" "$TMP/project/tests/"
ln -s "$OMP_MODULES" "$TMP/project/node_modules"
export OMP_INBOX_EXTENSION="$REPO/omp/extensions/inbox/index.ts"
"$BUN" run --no-install "$TMP/project/tests/omp-inbox-checks.ts"
"$BUN" run --no-install "$TMP/project/tests/omp-inbox-host.ts"
if [[ "${1:-}" == "--runtime-only" ]]; then exit 0; fi
# Narrow install must not invoke systemctl or replace any unrelated link.
mkdir -p "$HOME/.omp/agent/extensions" "$TMP/bin"
printf '#!/bin/sh\nexit 97\n' > "$TMP/bin/systemctl"
chmod +x "$TMP/bin/systemctl"
ln -s "$TMP/existing-provider" "$HOME/.omp/agent/extensions/provider"
PATH="$TMP/bin:$PATH" bash "$REPO/install.sh" --omp-inbox-only
[[ $(readlink "$HOME/.omp/agent/extensions/inbox") == "$REPO/omp/extensions/inbox" ]]
[[ $(readlink "$HOME/.omp/agent/extensions/provider") == "$TMP/existing-provider" ]]
[[ ! -e "$XDG_CONFIG_HOME/fish" ]]
rm "$HOME/.omp/agent/extensions/inbox"
mkdir "$HOME/.omp/agent/extensions/inbox"
printf 'local extension' > "$HOME/.omp/agent/extensions/inbox/local.ts"
PATH="$TMP/bin:$PATH" bash "$REPO/install.sh" --omp-inbox-only
[[ ! -L "$HOME/.omp/agent/extensions/inbox" ]]
[[ $(cat "$HOME/.omp/agent/extensions/inbox/local.ts") == 'local extension' ]]
bash "$REPO/tests/install-smoke.sh"
printf 'omp-inbox scoped smoke checks passed\n'
