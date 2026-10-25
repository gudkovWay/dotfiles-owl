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
cat >"$STUB_BIN/herdr" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$STUB_BIN/herdr"

# An untracked runtime file a fish session may have created inside config/fish.
RUNTIME_FILE="$FAKE_CONFIG/fish/fish_read_history"
mkdir -p "$FAKE_CONFIG/fish"
printf 'runtime marker\n' >"$RUNTIME_FILE"

# Authored workflow installation must preserve the owner's local JEV policy.
PRIVATE_POLICY="$FAKE_HOME/.omp/agent/jev/config.json"
mkdir -p "$(dirname "$PRIVATE_POLICY")"
printf '{"mode":"off"}\n' >"$PRIVATE_POLICY"
chmod 600 "$PRIVATE_POLICY"

PRIVATE_ACCOUNT="$FAKE_HOME/.secrets/payscrow-admin"
mkdir -m 700 "$FAKE_HOME/.secrets"
printf 'fixture-account\nfixture-password\n' >"$PRIVATE_ACCOUNT"
chmod 600 "$PRIVATE_ACCOUNT"
RUNTIME_CACHE="$FAKE_CONFIG/worktrunk/projects/__pycache__/local.pyc"
mkdir -p "$(dirname "$RUNTIME_CACHE")"
printf 'local cache marker\n' >"$RUNTIME_CACHE"
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
  'omp/rules/autonomous-decisions.md:.omp/agent/rules/autonomous-decisions.md' \
  'omp/rules/frontend-design-flow.md:.omp/agent/rules/frontend-design-flow.md' \
  'omp/rules/delegation-pipeline.md:.omp/agent/rules/delegation-pipeline.md' \
  'omp/skills/design-taste-frontend/SKILL.md:.omp/agent/skills/design-taste-frontend/SKILL.md' \
  'omp/skills/design-taste-frontend/INSTALLATION.json:.omp/agent/skills/design-taste-frontend/INSTALLATION.json' \
  'omp/skills/design-taste-frontend/scripts/inspect.mjs:.omp/agent/skills/design-taste-frontend/scripts/inspect.mjs' \
  'agents/skills/antislop/SKILL.md:.agents/skills/antislop/SKILL.md' \
  'agents/skills/antislop-ui/SKILL.md:.agents/skills/antislop-ui/SKILL.md' \
  'agents/skills/antislop-human/contrast-check.py:.agents/skills/antislop-human/contrast-check.py' \
  'agents/skills/antislop-layoutmobile/SKILL.md:.agents/skills/antislop-layoutmobile/SKILL.md' \
  'agents/skills/antislop-copywriting/SKILL.md:.agents/skills/antislop-copywriting/SKILL.md' \
  'agents/skills/antislop-code/SKILL.md:.agents/skills/antislop-code/SKILL.md' \
  'agents/skills/starting-worktree-work/SKILL.md:.agents/skills/starting-worktree-work/SKILL.md'; do
  source="${entry%%:*}"
  destination="$FAKE_HOME/${entry#*:}"
  [[ -L "$destination" && "$(readlink -f "$destination")" == "$REPO/$source" ]] ||
    fail "authored workflow file is not installed: $source"
done

# Current aliases must restore their full Python/runtime dependency closure,
# not just wrappers whose imports happen to exist on the developer's machine.
for relative in \
  config.toml projects/guarded-run projects/resource_guard.py \
  projects/resource_policy.py projects/resource_executor.py \
  projects/project-environment projects/dev_support.py projects/dev-session projects/ui-session \
  projects/p2p-frontend/dev-server projects/p2p-frontend/commit projects/p2p-frontend/batch \
  projects/p2p-frontend/push projects/p2p-frontend/stand projects/p2p-frontend/typecheck \
  projects/p2p-frontend/mr projects/p2p-frontend/mr-guard projects/p2p-frontend/mr-command \
  projects/p2p-frontend/feature-finalize projects/p2p-frontend/feature_finalize.py \
  projects/p2p-frontend/merge_readiness.py projects/p2p-frontend/finalize-prompt.md; do
  destination="$FAKE_CONFIG/worktrunk/$relative"
  [[ -L "$destination" && "$(readlink -f "$destination")" == "$REPO/config/worktrunk/$relative" ]] ||
    fail "workflow dependency is not installed: $relative"
done
for relative in \
  projects/guarded-run projects/project-environment projects/dev-session projects/ui-session \
  projects/p2p-frontend/dev-server projects/p2p-frontend/batch projects/p2p-frontend/feature-finalize; do
  [[ -x "$FAKE_CONFIG/worktrunk/$relative" ]] ||
    fail "workflow entrypoint is not executable: $relative"
done
for entrypoint in projects/dev-session projects/p2p-frontend/feature-finalize; do
  env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$STUB_BIN:$PATH" \
    python3 "$FAKE_CONFIG/worktrunk/$entrypoint" --help >/dev/null 2>&1 ||
    fail "installed CLI cannot resolve its dependencies: $entrypoint"
done
[[ ! -L "$PRIVATE_ACCOUNT" && "$(cat "$PRIVATE_ACCOUNT")" == $'fixture-account\nfixture-password' ]] ||
  fail 'local test credentials were replaced'
[[ "$(stat -c %a "$PRIVATE_ACCOUNT")" == 600 ]] ||
  fail 'local test credential permissions changed'
[[ "$(cat "$RUNTIME_CACHE")" == 'local cache marker' ]] ||
  fail 'local workflow cache was overwritten'
[[ ! -e "$FAKE_CONFIG/worktrunk/.superpowers" && ! -e "$FAKE_HOME/.superpowers" ]] ||
  fail 'agent runtime artifacts were installed'
[[ -L "$FAKE_HOME/.omp/agent/skills/repository-testing/SKILL.md" ]] ||
  fail 'repository testing and DEV grant procedure was not installed'

# The image opener must be installed outside any transient build/worktree.
OPENER="$FAKE_HOME/.local/share/omp/herdr-local-files"
[[ -L "$OPENER" && "$(readlink -f "$OPENER")" == "$REPO/omp/herdr-local-files" ]] ||
  fail 'image opener is not installed from the dotfiles repository'
[[ -f "$OPENER/open-file.ts" && -f "$OPENER/herdr-plugin.toml" && -f "$OPENER/kitty.conf" ]] ||
  fail 'installed image opener is incomplete'

# A subsequent install must keep a real owner-edited skill, not relink it.
OWNER_SKILL="$FAKE_HOME/.agents/skills/starting-worktree-work/SKILL.md"
rm "$OWNER_SKILL"
printf 'owner-specific workflow\n' >"$OWNER_SKILL"
env -i HOME="$FAKE_HOME" XDG_CONFIG_HOME="$FAKE_CONFIG" PATH="$STUB_BIN:$PATH" \
  bash "$REPO/install.sh" >/dev/null 2>&1 ||
  fail 'second installer invocation exited non-zero'
[[ ! -L "$OWNER_SKILL" && "$(cat "$OWNER_SKILL")" == 'owner-specific workflow' ]] ||
  fail 'existing owner-edited workflow was overwritten on reinstall'
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
