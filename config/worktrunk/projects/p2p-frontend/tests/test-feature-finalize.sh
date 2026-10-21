#!/bin/sh
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$dir/test_feature_finalize.py"
exec python3 "$dir/test_finalize_flow.py"
