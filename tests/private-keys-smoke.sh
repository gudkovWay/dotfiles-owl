#!/usr/bin/env bash
# Smoke test for config/fish/conf.d/api-keys.fish (dummy values only).
#
# Contract:
#   - readable non-empty keys/deepseek and keys/zai files export
#     DEEPSEEK_API_KEY / ZAI_API_KEY with the file's exact contents;
#   - missing or empty key files must NOT create the variable;
#   - sourcing the loader prints nothing on stdout or stderr.
# Uses an isolated temp HOME/XDG_CONFIG_HOME; never prints key contents.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOADER="$REPO/config/fish/conf.d/api-keys.fish"

fail() { printf 'FAIL (private-keys-smoke): %s\n' "$1" >&2; exit 1; }

command -v fish >/dev/null 2>&1 ||
  { printf 'SKIP (private-keys-smoke): fish is not installed, cannot exercise api-keys loader\n'; exit 0; }
[[ -f $LOADER ]] || fail "loader not found at $LOADER"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/dotfiles-owl-keys-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

FAKE_HOME="$TMP/home"
FAKE_CONFIG="$FAKE_HOME/.config"
mkdir -p "$FAKE_CONFIG"

# Run the loader under fish with a chosen private-dir layout; capture
# stdout, stderr and a requested assertion. All diagnostics avoid printing
# values: the runner reports only which assertion failed.
run_case() {  # run_case <assert-script> ; key files prepared by caller
  local asserts="$1"
  local out err rc
  out="$TMP/out" err="$TMP/err"
  env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$PATH" \
    fish --no-config -c "
      source '$LOADER'
      $asserts
    " >"$out" 2>"$err" && rc=0 || rc=$?
  [[ $rc -eq 0 ]] || fail "fish assertion failed (rc=$rc)"
  [[ ! -s $out ]] || fail 'loader produced stdout output; contract says silent'
  [[ ! -s $err ]] || fail 'loader produced stderr output; contract says silent'
}

KEYS="$FAKE_CONFIG/dotfiles-owl-private/keys"
mkdir -p "$KEYS"
printf 'dummy-deepseek-value\n' >"$KEYS/deepseek"
printf 'dummy-zai-value'      >"$KEYS/zai"

run_case '
  test (count $DEEPSEEK_API_KEY) -eq 1; or exit 11
  test "$DEEPSEEK_API_KEY" = "dummy-deepseek-value"; or exit 12
  test (count $ZAI_API_KEY) -eq 1; or exit 13
  test "$ZAI_API_KEY" = "dummy-zai-value"; or exit 14
'

rm "$KEYS/deepseek" "$KEYS/zai"
run_case '
  set -e ZAI_API_KEY
  not set -q DEEPSEEK_API_KEY; or exit 21
'
run_case '
  not set -q ZAI_API_KEY; or exit 22
  not set -q DEEPSEEK_API_KEY; or exit 23
'

: >"$KEYS/deepseek"
run_case '
  not set -q DEEPSEEK_API_KEY; or exit 24
'

printf 'OK (private-keys-smoke): all api-keys loader contract checks passed\n'
