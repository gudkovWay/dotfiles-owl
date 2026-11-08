#!/bin/sh
# Native exact-SHA, CI, receipt, hotfix and source-preservation regression cases.
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$dir/test_mr_gate.py"
