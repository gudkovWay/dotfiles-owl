#!/usr/bin/env bash
# Permanent scoped shell-smoke test, using the installed OMP/Bun interpreter.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUN="$(command -v bun)"
OMP_CLI="$(readlink -f "$(command -v omp)")"
OMP_MODULES="$(dirname "$OMP_CLI")"
while [[ ! -f "$OMP_MODULES/@oh-my-pi/pi-tui/package.json" ]]; do
  if [[ -f "$OMP_MODULES/node_modules/@oh-my-pi/pi-tui/package.json" ]]; then
    OMP_MODULES="$OMP_MODULES/node_modules"
    break
  fi
  if [[ $OMP_MODULES == / ]]; then
    echo "Cannot locate installed OMP modules from $OMP_CLI" >&2
    exit 1
  fi
  OMP_MODULES="$(dirname "$OMP_MODULES")"
done
export FORCE_COLOR=3
TMP="$(mktemp -d "${TMPDIR:-/tmp}/omp-document-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_DATA_HOME="$TMP/data"
export XDG_STATE_HOME="$TMP/state" XDG_CACHE_HOME="$TMP/cache" PI_CODING_AGENT_DIR="$TMP/agent"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$PI_CODING_AGENT_DIR"
# Bun does not resolve these global host packages through NODE_PATH. Use an
# isolated fixture tree linked to the already installed modules, never npm.
mkdir -p "$TMP/project/tests" "$TMP/project/omp/extensions/document-markdown"
cp "$REPO/tests/omp-document-checks.ts" "$TMP/project/tests/"
cp "$REPO/omp/extensions/document-markdown/render.ts" "$TMP/project/omp/extensions/document-markdown/"
ln -s "$OMP_MODULES" "$TMP/project/node_modules"
"$BUN" run --no-install "$TMP/project/tests/omp-document-checks.ts"
python3 "$REPO/tests/omp-document-install-checks.py"
