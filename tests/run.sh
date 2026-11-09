#!/usr/bin/env bash
# Only test explicitly managed files and isolated fixtures; never scan a live home.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
command -v python3 >/dev/null || { printf 'Tests require python3\n' >&2; exit 1; }
exec python3 "$ROOT/tests/test_setup.py" "$@"
