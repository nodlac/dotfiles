# Shared setup primitives. Bash 3.2-compatible (including Apple's system bash).
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*"; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }

# Do not traverse user-controlled symlink parents: replacing their children could
# silently edit a different config tree. A separate, reviewed migration is needed.
check_parents() {
    local p
    p=$(dirname "$1")
    while [ "$p" != "$HOME" ] && [ "$p" != / ]; do
        if [ -L "$p" ] || { [ -e "$p" ] && [ ! -d "$p" ]; }; then
            fail "Unsafe parent $p; review it manually before setup"
        fi
        p=$(dirname "$p")
    done
}
add_link() {
    [ -e "$1" ] || fail "Missing required source: $1"
    case "$ROOT/" in
        "$2/"*) fail "Checkout is inside managed target $2; clone into a separate projects directory" ;;
    esac
    check_parents "$2"
    sources[${#sources[@]}]=$1
    targets[${#targets[@]}]=$2
}

preflight_links() {
    local i src dst
    conflicts=0
    i=0
    while [ "$i" -lt "${#sources[@]}" ]; do
        src=${sources[$i]}; dst=${targets[$i]}
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
            log "OK      $dst"
        elif exists "$dst"; then
            if [ "$replace" = yes ]; then
                log "BACKUP  $dst -> $backup_dir/${dst#"$HOME"/}"
                log "LINK    $dst -> $src"
            else
                log "CONFLICT $dst (unchanged; review or use --replace to approve backup + replacement)"
                conflicts=$((conflicts + 1))
            fi
        else
            log "LINK    $dst -> $src"
        fi
        i=$((i + 1))
    done
    [ "$conflicts" -eq 0 ] || return 2
}
apply_links() {
    local i src dst backup
    i=0
    while [ "$i" -lt "${#sources[@]}" ]; do
        src=${sources[$i]}; dst=${targets[$i]}
        if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
            i=$((i + 1)); continue
        fi
        check_parents "$dst"
        if exists "$dst"; then
            [ "$replace" = yes ] || fail "Target changed after preflight: $dst"
            backup=$backup_dir/${dst#"$HOME"/}
            exists "$backup" && fail "Backup collision: $backup"
            (umask 077; mkdir -p "$(dirname "$backup")")
            mv "$dst" "$backup"
        fi
        mkdir -p "$(dirname "$dst")"
        # No -f: never clobber an unexpected concurrently-created target.
        # Preflight also forbids directory symlink parents.
        exists "$dst" && fail "Target appeared during setup: $dst"
        ln -s "$src" "$dst"
        i=$((i + 1))
    done
}

read_packages() {
    local file=$1 line
    [ -f "$file" ] || fail "Missing package manifest: $file"
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|\#*) continue ;; esac
        case "$line" in *[!a-zA-Z0-9@+._/-]*) fail "Invalid package name in $file" ;; esac
        packages[${#packages[@]}]=$line
    done < "$file"
}
plan_packages() {
    packages=(); casks=()
    case "$DF_OS:$DF_DISTRO" in
        macos:*) manager=brew; read_packages "$ROOT/platform/packages/macos.txt" ;;
        linux:arch|linux:endeavouros) manager=pacman; read_packages "$ROOT/platform/packages/arch.txt" ;;
        linux:ubuntu|linux:debian) manager=apt-get; read_packages "$ROOT/platform/packages/ubuntu.txt" ;;
        *) fail "No package recipe for $DF_DISTRO (config-only setup is supported)" ;;
    esac
    if [ "$profile" = desktop ]; then
        case "$manager" in
            pacman) read_packages "$ROOT/platform/packages/arch-desktop.txt" ;;
            brew)
                read_packages "$ROOT/platform/packages/macos-desktop-formulae.txt"
                local base_count=${#packages[@]}
                read_packages "$ROOT/platform/packages/macos-desktop.txt"
                casks=("${packages[@]:$base_count}")
                packages=("${packages[@]:0:$base_count}") ;;
            *) fail "Desktop package recipe not reviewed for $DF_DISTRO; use headless or install packages manually" ;;
        esac
    fi
    command -v "$manager" >/dev/null 2>&1 || fail "$manager is required; install it using vendor instructions first"
    log "PACKAGES $manager: ${packages[*]}"
    [ "${#casks[@]}" -eq 0 ] || log "CASKS    ${casks[*]}"
}
install_packages() {
    case "$manager" in
        brew)
            brew install "${packages[@]}"
            [ "${#casks[@]}" -eq 0 ] || brew install --cask "${casks[@]}" ;;
        pacman) sudo pacman -S --needed "${packages[@]}" ;;
        apt-get) sudo apt-get update; sudo apt-get install "${packages[@]}" ;;
    esac
}
plan_plugins() {
    plugin_sources=(
        https://github.com/zsh-users/zsh-history-substring-search.git
        https://github.com/zsh-users/zsh-autosuggestions.git
        https://github.com/zsh-users/zsh-completions.git
        https://github.com/zdharma-continuum/fast-syntax-highlighting.git
        https://github.com/Aloxaf/fzf-tab.git
        https://github.com/tmux-plugins/tpm.git
        https://github.com/jimeh/tmux-themepack.git
        https://github.com/tmux-plugins/tmux-resurrect.git
        https://github.com/tmux-plugins/tmux-continuum.git
    )
    plugin_targets=(
        "$HOME/.zsh/zsh-history-substring-search"
        "$HOME/.zsh/zsh-autosuggestions"
        "$HOME/.zsh/zsh-completions"
        "$HOME/.zsh/fast-syntax-highlighting"
        "$HOME/.zsh/fzf-tab"
        "$HOME/.tmux/plugins/tpm"
        "$HOME/.tmux/plugins/tmux-themepack"
        "$HOME/.tmux/plugins/tmux-resurrect"
        "$HOME/.tmux/plugins/tmux-continuum"
    )
    local i=0 dst
    while [ "$i" -lt "${#plugin_sources[@]}" ]; do
        dst=${plugin_targets[$i]}
        check_parents "$dst"
        if exists "$dst"; then
            [ ! -L "$dst" ] && [ -d "$dst/.git" ] || fail "Plugin path exists but is not a checkout: $dst"
            log "KEEP    $dst (no pull or update)"
        else
            log "CLONE   ${plugin_sources[$i]} -> $dst"
        fi
        i=$((i + 1))
    done
}
install_plugins() {
    local i=0 dst
    while [ "$i" -lt "${#plugin_sources[@]}" ]; do
        dst=${plugin_targets[$i]}
        if ! exists "$dst"; then
            mkdir -p "$(dirname "$dst")"
            git clone --depth 1 "${plugin_sources[$i]}" "$dst"
        fi
        i=$((i + 1))
    done
}
