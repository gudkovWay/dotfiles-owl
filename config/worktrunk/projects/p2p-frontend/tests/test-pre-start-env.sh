#!/bin/sh
# Native temporary-Git regressions: backend selection is independent of the
# frontend branch; only three present Payscrow LK apps receive the override.
set -eu
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
unset WT_P2P_API_BASE

scripts=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
TARGETS='payscrow-admin payscrow-merchant payscrow-provider'
EXCLUDED='payscrow-form lucky-admin lucky-merchant lucky-form ock-admin ock-merchant ock-form'
branch=DEV-capitalism-slave-env-fixture
shared=https://api.dev.payscrow-cascade.io
confirmed=https://api-confirmed.dev.payscrow-cascade.io

git init -q "$tmp/repo"
cd "$tmp/repo"
printf '**/.env\n' >.gitignore
for app in $TARGETS $EXCLUDED; do
	mkdir -p "apps/$app"
	touch "apps/$app/nuxt.config.ts"
	git add "apps/$app/nuxt.config.ts"
done
for app in $TARGETS; do
	printf 'SOME_OTHER_VAR=1\nNUXT_PUBLIC_API_BASE=https://stale.example\nANOTHER=2\nNUXT_PUBLIC_API_BASE=https://duplicate.example\n' >"apps/$app/.env"
done
printf 'NUXT_PUBLIC_API_URL=https://form.example.invalid\n' >apps/payscrow-form/.env
printf 'LOCAL_SETTING=preserve\n' >apps/lucky-merchant/.env
git add .gitignore
git -c user.email=test@example.invalid -c user.name=Test commit -qm fixture

check_targets() {
	for app in $TARGETS; do
		file="apps/$app/.env"
		[ "$(grep '^NUXT_PUBLIC_API_BASE=' "$file")" = "NUXT_PUBLIC_API_BASE=$1" ] || {
			echo "wrong backend in $app" >&2; exit 1;
		}
		[ "$(grep -c '^NUXT_PUBLIC_API_BASE=' "$file")" = 1 ] || exit 1
		grep -q '^SOME_OTHER_VAR=1$' "$file" || exit 1
		grep -q '^ANOTHER=2$' "$file" || exit 1
	done
}

check_excluded() {
	[ "$(cat apps/payscrow-form/.env)" = 'NUXT_PUBLIC_API_URL=https://form.example.invalid' ] || exit 1
	[ "$(cat apps/lucky-merchant/.env)" = 'LOCAL_SETTING=preserve' ] || exit 1
	for app in lucky-admin lucky-form ock-admin ock-merchant ock-form; do
		[ ! -e "apps/$app/.env" ] || { echo "excluded app received env: $app" >&2; exit 1; }
	done
}

# A frontend branch never implies that a matching backend deployment exists.
sh "$scripts/pre-start-env" "$branch" >/dev/null
check_targets "$shared"
check_excluded
sh "$scripts/pre-start-env" "$branch" >/dev/null
check_targets "$shared"
check_excluded

# An explicitly selected backend wins regardless of frontend branch name.
WT_P2P_API_BASE="$confirmed" sh "$scripts/pre-start-env" "$branch" >/dev/null
check_targets "$confirmed"
check_excluded
WT_P2P_API_BASE="$confirmed" sh "$scripts/pre-start-env" main >/dev/null
check_targets "$confirmed"

# Unsafe URLs must be rejected before any env write.
for invalid in \
	'http://api.dev.payscrow-cascade.io' \
	'https://api.example.invalid' \
	'https://api.dev.payscrow-cascade.io/path' \
	'https://api.dev.payscrow-cascade.io?key=value' \
	'https://user:password@api.dev.payscrow-cascade.io'; do
	if WT_P2P_API_BASE="$invalid" sh "$scripts/pre-start-env" "$branch" >/dev/null 2>&1; then
		echo 'unsafe backend origin accepted' >&2; exit 1
	fi
	check_targets "$confirmed"
done

# An app removed on this branch must not be resurrected by stale build dirs.
rm apps/payscrow-provider/nuxt.config.ts
mkdir -p apps/payscrow-provider/.nuxt
printf 'REMOVED_APP=preserve\n' >apps/payscrow-provider/.env
sh "$scripts/pre-start-env" "$branch" >/dev/null
[ "$(cat apps/payscrow-provider/.env)" = 'REMOVED_APP=preserve' ] || exit 1
mv apps/payscrow-provider apps/archived-provider
sh "$scripts/pre-start-env" "$branch" >/dev/null
[ ! -d apps/payscrow-provider ] || { echo 'removed app directory recreated' >&2; exit 1; }
check_excluded

printf 'OK (pre-start-env): exact LK scope, shared/explicit backend, preservation and rejection cases passed\n'
