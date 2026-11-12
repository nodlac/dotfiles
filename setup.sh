#!/usr/bin/env bash
# Safe configuration bootstrap. No sudo, network or installs unless requested.
set -eo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[ -f "$ROOT/lib/setup.sh" ] || { printf 'Missing lib/setup.sh\n' >&2; exit 1; }
. "$ROOT/lib/setup.sh"
[ -f "$ROOT/platform/detect.sh" ] || fail "Missing platform/detect.sh"
. "$ROOT/platform/detect.sh"

usage() {
    printf '%s\n' 'Usage: ./setup.sh [options]' \
        '  --dry-run             Report only; no filesystem/network/system changes' \
        '  --replace             Explicitly approve moving conflicts to unique backups' \
        '  --machine NAME        generic (default), behemoth, callisto, somnambulist,' \
        '                        macos, medina-station' \
        '  --profile ROLE        headless (default) or desktop (explicit opt-in)' \
        '  --desktop NAME        i3 (Linux default) or firehawk (Arch/EndeavourOS only)' \
        '  --theme-profile NAME  Firehawk identity: auto (default) or profile name' \
        '  --confirm-work-os OS  Required for medina-station: linux or macos' \
        '  --install-packages    Opt-in package manager actions (requires sudo on Linux)' \
        '  --install-plugins     Opt-in plugin clones; never pulls existing checkouts' \
        '  --install-infisical   Install pinned Infisical CLI into ~/.local/bin' \
        '  --link-nvim           Opt-in existing nvim config (requires nvim >= 0.10)' \
        '  --detect              Print detection and exit without changing anything' \
        '  --help                Show help'
}
dry_run=no replace=no machine=generic profile=headless
packages_requested=no plugins_requested=no nvim_requested=no infisical_requested=no
work_os= profile_explicit=no detect_only=no
desktop=i3 desktop_explicit=no theme_profile=auto theme_explicit=no
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --dry-run) dry_run=yes ;;
        --replace) replace=yes ;;
        --install-packages) packages_requested=yes ;;
        --install-plugins) plugins_requested=yes ;;
        --install-infisical) infisical_requested=yes ;;
        --link-nvim) nvim_requested=yes ;;
        --detect) detect_only=yes ;;
        --machine|--profile|--confirm-work-os|--desktop|--theme-profile)
            [ "$#" -ge 2 ] || fail "Missing value for $1"
            case "$1" in
                --machine) machine=$2 ;;
                --profile) profile=$2; profile_explicit=yes ;;
                --confirm-work-os) work_os=$2 ;;
                --desktop) desktop=$2; desktop_explicit=yes ;;
                --theme-profile) theme_profile=$2; theme_explicit=yes ;;
            esac
            shift ;;
        *) fail "Unknown option: $1 (see --help)" ;;
    esac
    shift
done
detect_platform
log "Detected os=$DF_OS distro=$DF_DISTRO wsl=$DF_WSL"
[ "$detect_only" = no ] || exit 0
[ -z "${SUDO_USER:-}" ] || fail "Run setup as yourself, not via sudo"
[ "${EUID:-$(id -u)}" -ne 0 ] || fail "Run setup as an ordinary user, not root"
case "${HOME:-}" in /*) ;; *) fail 'HOME must be an absolute path' ;; esac
HOME=${HOME%/}
[ -n "$HOME" ] && [ -d "$HOME" ] && [ ! -L "$HOME" ] || fail "HOME must be an existing non-symlink directory"
# Never run this installer inside the legacy home worktree; migration is manual.
[ -d "$ROOT/.git" ] || fail "Use a conventional clone, not a bare repository or legacy home worktree; see docs/MIGRATION.md"
[ "$ROOT" != "$HOME" ] || fail "Refusing to install from a home-directory worktree"
case "$profile" in headless|desktop) ;; *) fail "Unknown profile: $profile" ;; esac
case "$machine" in
    generic) ;;
    behemoth)
        case "$DF_OS:$DF_DISTRO:$DF_WSL" in linux:arch:none|linux:endeavouros:none) ;; *) fail 'Behemoth requires native Arch/EndeavourOS' ;; esac ;;
    callisto) [ "$DF_OS:$DF_DISTRO:$DF_WSL:$profile" = linux:ubuntu:none:headless ] || fail 'Callisto requires native Ubuntu and the headless profile' ;;
    somnambulist) [ "$DF_OS:$DF_DISTRO:$DF_WSL:$profile" = linux:ubuntu:2:headless ] || fail 'Somnambulist requires Ubuntu WSL2 and the headless profile' ;;
    macos) [ "$DF_OS" = macos ] || fail 'macos machine requires macOS' ;;
    medina-station)
        [ "$work_os" = "$DF_OS" ] && [ "$profile_explicit" = yes ] || fail 'Verify work requirements first; supply --confirm-work-os and an explicit --profile' ;;
    *) fail "Unknown machine: $machine" ;;
esac
[ "$DF_WSL" = none ] || [ "$profile" = headless ] || fail 'WSL desktop activation is not supported'
case "$desktop" in i3|firehawk) ;; *) fail "Unknown desktop: $desktop" ;; esac
if [ "$desktop_explicit" = yes ] || [ "$theme_explicit" = yes ]; then
    [ "$profile" = desktop ] || fail '--desktop/--theme-profile require --profile desktop'
    case "$DF_OS:$DF_DISTRO:$DF_WSL" in
        linux:arch:none|linux:endeavouros:none) ;;
        *) fail '--desktop/--theme-profile require native Arch/EndeavourOS' ;;
    esac
fi
[ "$theme_explicit" = no ] || [ "$desktop" = firehawk ] || fail '--theme-profile requires --desktop firehawk'
log "Selected machine=$machine profile=$profile desktop=$desktop"
backup_dir="$HOME/.local/state/dotfiles/backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
check_parents "$backup_dir/placeholder"
sources=() targets=()
add_link "$ROOT" "$HOME/.local/share/dotfiles"
add_link "$ROOT/config/shared/zshenv" "$HOME/.zshenv"
add_link "$ROOT/config/shared/zshrc" "$HOME/.zshrc"
add_link "$ROOT/config/shared/tmux.conf" "$HOME/.tmux.conf"
add_link "$ROOT/machines/$machine.zsh" "$HOME/.config/dotfiles/machine.zsh"
add_link "$ROOT/machines/$machine.tmux.conf" "$HOME/.config/dotfiles/machine.tmux.conf"
[ -f "$ROOT/platform/$DF_OS.zsh" ] || fail "Missing platform config: $DF_OS.zsh"
if [ "$profile" = desktop ]; then
    add_link "$ROOT/.config/ghostty" "$HOME/.config/ghostty"
    case "$DF_OS" in
        macos)
            add_link "$ROOT/.aerospace.toml" "$HOME/.aerospace.toml"
            add_link "$ROOT/.config/karabiner/assets/complex_modifications/linux-ctrl-swap.json" "$HOME/.config/karabiner/assets/complex_modifications/linux-ctrl-swap.json" ;;
        linux)
            case "$DF_DISTRO" in
                arch|endeavouros)
                    if [ "$desktop" = firehawk ]; then
                        . "$ROOT/lib/firehawk.sh"
                        plan_firehawk
                    else
                        add_link "$ROOT/.config/i3" "$HOME/.config/i3"
                    fi ;;
                *) fail 'Desktop activation is currently reviewed only for Arch/EndeavourOS and macOS' ;;
            esac ;;
    esac
fi
if [ "$nvim_requested" = yes ]; then
    add_link "$ROOT/.config/nvim" "$HOME/.config/nvim"
fi
# Preflight every source and conflict before performing any setup changes.
link_status=0
preflight_links || link_status=$?
[ "$packages_requested" = no ] || plan_packages
[ "$plugins_requested" = no ] || plan_plugins
[ "$infisical_requested" = no ] || plan_infisical
[ "$link_status" -eq 0 ] || exit "$link_status"
if [ "$dry_run" = yes ]; then
    log 'Dry run complete: no changes made.'
    exit 0
fi
if [ "$profile:$desktop" = desktop:firehawk ]; then
    # Pillow may be supplied by the requested package transaction. Never write
    # links to generated sources until the whole generation has succeeded.
    [ "$packages_requested" = no ] || install_packages
    build_firehawk
    apply_links
else
    apply_links
    [ "$packages_requested" = no ] || install_packages
fi
[ "$plugins_requested" = no ] || install_plugins
[ "$infisical_requested" = no ] || install_infisical
log 'Setup complete. Start zsh (or restart it); tmux config applies to new servers.'
log 'No login-shell, Git, credential, service or OS-default changes were made.'
log 'Local overrides: ~/.config/dotfiles/local.zsh and tmux.local.conf (never managed by setup).'
