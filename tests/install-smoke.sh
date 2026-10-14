#!/usr/bin/env bash
# Smoke test: isolated install into a temp HOME/XDG_CONFIG_HOME.
#
# Encodes the public-release contract:
#   1. config/fish remains a REAL directory in the destination.
#   2. Pre-existing untracked runtime files inside it survive unchanged.
#   3. config/fish/config.fish is a symlink to the repository file.
#   4. config/fish/fish_variables is NOT installed.
# Runs entirely under a temp dir; systemctl is stubbed via PATH.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { printf 'FAIL (install-smoke): %s\n' "$1" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/dotfiles-owl-install-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

FAKE_HOME="$TMP/home"
FAKE_CONFIG="$FAKE_HOME/.config"
mkdir -p "$FAKE_CONFIG"

# Stub systemctl so the installer can never reach the real session bus.
STUB_BIN="$TMP/bin"
mkdir -p "$STUB_BIN"
cat >"$STUB_BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$STUB_BIN/systemctl"

# An untracked runtime file a fish session may have created inside config/fish.
RUNTIME_FILE="$FAKE_CONFIG/fish/fish_read_history"
mkdir -p "$FAKE_CONFIG/fish"
printf 'runtime marker\n' >"$RUNTIME_FILE"

# A user's ordinary local rule must not be replaced by the protected integration.
OWNER_RULE="$FAKE_HOME/.omp/agent/rules/owner-rule-authority.md"
mkdir -p "$(dirname "$OWNER_RULE")"
printf 'local owner policy\n' >"$OWNER_RULE"

env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$STUB_BIN:$PATH" \
  bash "$REPO/install.sh" >/dev/null 2>&1 ||
  fail 'installer exited non-zero (stderr not shown: could expose filesystem paths or secret material)'

[[ -d "$FAKE_CONFIG/fish" && ! -L "$FAKE_CONFIG/fish" ]] ||
  fail 'config/fish is not a real directory after install'
[[ "$(cat "$RUNTIME_FILE")" == 'runtime marker' ]] ||
  fail 'untracked runtime file inside config/fish was modified or removed'
[[ -L "$FAKE_CONFIG/fish/config.fish" ]] ||
  fail 'config/fish/config.fish is not a symlink to the repository file'
[[ "$(readlink -f "$FAKE_CONFIG/fish/config.fish")" == "$REPO/config/fish/config.fish" ]] ||
  fail 'config/fish/config.fish symlinks to an unexpected target'
[[ ! -e "$FAKE_CONFIG/fish/fish_variables" ]] ||
  fail 'config/fish/fish_variables was installed but must not be'

[[ ! -L "$OWNER_RULE" && "$(cat "$OWNER_RULE")" == 'local owner policy' ]] ||
  fail 'existing local owner rule was replaced'

OWNER_EXTENSION="$FAKE_HOME/.omp/agent/extensions/owner-approval.js"
if [[ -e "$REPO/omp/extensions/owner-approval.js" ]]; then
  [[ -L "$OWNER_EXTENSION" && "$(readlink -f "$OWNER_EXTENSION")" == /usr/local/lib/omp-owner-approval/extension.js ]] ||
    fail 'owner approval extension points to a mutable checkout instead of protected code'
else
  [[ ! -e "$OWNER_EXTENSION" && ! -L "$OWNER_EXTENSION" ]] ||
    fail 'owner approval was enabled without an installed protected extension'
fi

rm "$OWNER_RULE"
env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$STUB_BIN:$PATH" \
  bash "$REPO/install.sh" >/dev/null 2>&1 ||
  fail 'second isolated install exited non-zero'
if [[ -e "$REPO/omp/rules/owner-rule-authority.md" ]]; then
  [[ -L "$OWNER_RULE" && "$(readlink -f "$OWNER_RULE")" == /usr/local/lib/omp-owner-approval/owner-rule-authority.md ]] ||
    fail 'owner authority rule points to a mutable checkout instead of protected policy'
else
  [[ ! -e "$OWNER_RULE" && ! -L "$OWNER_RULE" ]] ||
    fail 'owner authority was enabled without an installed protected policy'
fi

printf 'OK (install-smoke): all install contract checks passed\n'
