#!/bin/sh
# Native exact-SHA CI/review gates and private-origin source cleanup regressions.
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$dir/test_mr_gate.py"
exec python3 "$dir/test_remote_cleanup.py"
