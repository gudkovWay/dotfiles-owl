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

# Authored workflow installation must preserve the owner's local JEV policy.
PRIVATE_POLICY="$FAKE_HOME/.omp/agent/jev/config.json"
mkdir -p "$(dirname "$PRIVATE_POLICY")"
printf '{"mode":"off"}\n' >"$PRIVATE_POLICY"
chmod 600 "$PRIVATE_POLICY"

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

[[ "$(cat "$PRIVATE_POLICY")" == '{"mode":"off"}' ]] ||
  fail 'local JEV policy was overwritten'
[[ ! -L "$PRIVATE_POLICY" ]] ||
  fail 'local JEV policy was replaced with a repository link'
[[ ! -e "$FAKE_HOME/.omp/agent/jev/receipts.jsonl" ]] ||
  fail 'runtime JEV receipts were installed from the repository'
[[ -x "$FAKE_CONFIG/worktrunk/projects/guarded-run" ]] ||
  fail 'resource guard is not executable after installation'
for entry in \
  'omp/extensions/jev-shadow.ts:.omp/agent/extensions/jev-shadow.ts' \
  'omp/jev/task-context.ts:.omp/agent/jev/task-context.ts' \
  'omp/rules/no-autotests.md:.omp/agent/rules/no-autotests.md' \
  'agents/skills/starting-worktree-work/SKILL.md:.agents/skills/starting-worktree-work/SKILL.md'; do
  source="${entry%%:*}"
  destination="$FAKE_HOME/${entry#*:}"
  [[ -L "$destination" && "$(readlink -f "$destination")" == "$REPO/$source" ]] ||
    fail "authored workflow file is not installed: $source"
done

# A subsequent install must keep a real owner-edited skill, not relink it.
OWNER_SKILL="$FAKE_HOME/.agents/skills/starting-worktree-work/SKILL.md"
rm "$OWNER_SKILL"
printf 'owner-specific workflow\n' >"$OWNER_SKILL"
env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$STUB_BIN:$PATH" \
  bash "$REPO/install.sh" >/dev/null 2>&1 ||
  fail 'second installer invocation exited non-zero'
[[ ! -L "$OWNER_SKILL" && "$(cat "$OWNER_SKILL")" == 'owner-specific workflow' ]] ||
  fail 'existing owner-edited workflow was overwritten on reinstall'

printf 'OK (install-smoke): all install contract checks passed\n'
