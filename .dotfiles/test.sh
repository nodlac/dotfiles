#!/usr/bin/env bash
# Compatibility wrapper for dtf-test.
set -e
dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
exec bash "$dir/tests/run.sh" "$@"
