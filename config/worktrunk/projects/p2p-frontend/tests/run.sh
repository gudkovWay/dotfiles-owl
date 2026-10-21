#!/bin/sh
# Run all tests in this directory. Exit non-zero on any failure.
set -u

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
failed=0

for t in "$dir"/test-*.sh; do
	name=$(basename "$t")
	if sh "$t"; then
		echo "PASS $name"
	else
		echo "FAIL $name"
		failed=1
	fi
done

exit $failed
