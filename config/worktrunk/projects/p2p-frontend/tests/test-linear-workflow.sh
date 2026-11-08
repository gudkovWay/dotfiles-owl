#!/bin/sh
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -m unittest discover -s "$dir" -p test_linear_workflow.py
