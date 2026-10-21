#!/bin/sh
# The shared prepared dev launcher owns readiness/reuse/failure semantics.
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
exec python3 "$dir/tests/test_dev_start.py"
