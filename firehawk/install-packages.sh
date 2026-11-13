#!/usr/bin/env bash
# Package-only convenience helper. Main setup.sh is the deployment entry point.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $EUID -ne 0 ]] || { echo "Run as your normal user, not root." >&2; exit 1; }
command -v pacman >/dev/null || { echo "Arch/EndeavourOS only." >&2; exit 1; }
packages=()
while IFS= read -r name || [[ -n "$name" ]]; do
    case "$name" in ''|\#*) continue ;; esac
    [[ "$name" != *[!a-zA-Z0-9@+._/-]* ]] || { echo "Invalid package name." >&2; exit 1; }
    packages+=("$name")
done < "$ROOT/platform/packages/arch-firehawk.txt"
echo "Package-only helper: full upgrade; review pacman's transaction before accepting."
sudo pacman -Syu --needed "${packages[@]}"
echo "Packages installed. No configs, services or login manager changed."
