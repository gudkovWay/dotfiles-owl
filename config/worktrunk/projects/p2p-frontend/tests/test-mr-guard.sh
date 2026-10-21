#!/bin/sh
# Tests for mr-guard: pass on clean/unrelated changes, fail on added/removed/
# modified apiBase, fail on untracked nuxt.config.ts with apiBase, and verify
# the dev-stand check. Uses only a temporary git repository.
set -eu

scripts=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

NUXT='export default defineNuxtConfig({
	runtimeConfig: {
		public: {
		%s
		},
});
'
DEV_LINE="apiBase: 'https://api.dev.payscrow-cascade.io',"
DEV_LINE_QUOTED="\"apiBase\": 'https://api.dev.payscrow-cascade.io',"

git_init() {
	git init -q "$tmp/repo"
	cd "$tmp/repo"
	mkdir -p apps/payscrow-admin apps/lucky-merchant apps/payscrow-form
	printf "$NUXT" "$DEV_LINE" >apps/payscrow-admin/nuxt.config.ts
	printf "$NUXT" "$DEV_LINE_QUOTED" >apps/lucky-merchant/nuxt.config.ts
	printf 'export default defineNuxtConfig({\n\t// form app: no apiBase\n});\n' >apps/payscrow-form/nuxt.config.ts
	git add .
	git -c user.email=t@t -c user.name=t commit -qm init
	git branch -m dev
	git checkout -qb feature/x
}

# expect_ok <description> — guard exits 0
expect_ok() {
	sh "$scripts/mr-guard" >/dev/null 2>&1 || { echo "FAIL(should pass): $1"; exit 1; }
}

# expect_fail <description> — guard exits non-zero
expect_fail() {
	sh "$scripts/mr-guard" >/dev/null 2>&1 && { echo "FAIL(should block): $1"; exit 1; }
	# restore pristine tree after a deliberate breakage
	git reset --hard -q HEAD && git clean -qfd apps
}

git_init
export WT_MR_BASE=dev

# 1. Clean branch passes.
expect_ok "clean branch"

# 2. Unrelated nuxt config change passes.
printf '\n// tweak: something unrelated\n' >>apps/payscrow-admin/nuxt.config.ts
expect_ok "unrelated nuxt config change"

# 3. Added apiBase assignment fails.
printf '\t\t\t%s\n' "$DEV_LINE" >>apps/payscrow-admin/nuxt.config.ts
expect_fail "added apiBase"

# 4. Removed apiBase assignment fails.
grep -v "apiBase" apps/lucky-merchant/nuxt.config.ts >tmp.nc && mv tmp.nc apps/lucky-merchant/nuxt.config.ts
expect_fail "removed apiBase"

# 5. Modified apiBase value fails (current tree check).
sed "s|api.dev.payscrow-cascade.io|api-DEV-1.dev.payscrow-cascade.io|" apps/payscrow-admin/nuxt.config.ts >tmp.nc &&
	mv tmp.nc apps/payscrow-admin/nuxt.config.ts
expect_fail "modified apiBase value"

# 6. An ordinary comment line containing the dev URL and "apiBase:" is not
# an assignment: the guard must not block on it.
printf '\t\t\t// %s\n' "$DEV_LINE" >>apps/payscrow-admin/nuxt.config.ts
expect_ok "apiBase dev URL only inside a comment"

# 7. Untracked nuxt.config.ts with apiBase fails.
printf "$NUXT" "$DEV_LINE" >apps/payscrow-admin/nuxt.config.ts.new
mv apps/payscrow-admin/nuxt.config.ts.new apps/payscrow-admin/other.config.ts
mv apps/payscrow-admin/other.config.ts apps/payscrow-admin/nuxt.config.ts &&
	git rm -q --cached apps/payscrow-admin/nuxt.config.ts
expect_fail "untracked nuxt.config.ts with apiBase"

# 8. Added apiBase with a quoted key fails even though an existing
# apiBase line remains (key quoting must not evade the guard).
printf '\t\t\t"apiBase": '"'"'https://evil.example'"'"',\n' >>apps/payscrow-admin/nuxt.config.ts
expect_fail "quoted-key apiBase addition"

# 9. Missing base fails clearly.
WT_MR_BASE=nope/nonexistent sh "$scripts/mr-guard" >/dev/null 2>&1 &&
	{ echo "FAIL(should block): missing base"; exit 1; }

echo "mr-guard tests: all cases behaved as expected"
