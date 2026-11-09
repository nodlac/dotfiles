#!/usr/bin/env bash
# Compatibility entry point; package/plugin installs now require explicit flags.
set -e
dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [ -f "$dir/setup.sh" ]; then root=$dir
elif [ -f "$dir/../setup.sh" ]; then root=$(cd "$dir/.." && pwd -P)
else printf '%s\n' 'Missing setup.sh; use a conventional clone (see docs/MIGRATION.md)' >&2; exit 1
fi
exec bash "$root/setup.sh" --machine macos --profile desktop "$@"
