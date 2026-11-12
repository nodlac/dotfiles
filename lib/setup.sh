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
    if [ "${3:-existing}" != generated ]; then
        [ -e "$1" ] || fail "Missing required source: $1"
    fi
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
            pacman)
                if [ "$desktop" = firehawk ]; then
                    read_packages "$ROOT/platform/packages/arch-firehawk.txt"
                else
                    read_packages "$ROOT/platform/packages/arch-desktop.txt"
                fi ;;
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
        pacman)
            if [ "$profile:$desktop" = desktop:firehawk ]; then
                log "Firehawk requests a full upgrade to avoid an Arch partial upgrade; review pacman before accepting."
                sudo pacman -Syu --needed "${packages[@]}"
            else
                sudo pacman -S --needed "${packages[@]}"
            fi ;;
        apt-get) sudo apt-get update; sudo apt-get install "${packages[@]}" ;;
    esac
}
# Pinned upstream release; update the version and all four hashes together.
plan_infisical() {
    infisical_version=0.45.4
    local arch os tool
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64) arch=amd64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) fail "Infisical: unsupported architecture $arch" ;;
    esac
    case "$DF_OS" in
        linux) os=linux ;;
        macos) os=darwin ;;
        *) fail "Infisical: unsupported OS $DF_OS" ;;
    esac
    case "$os:$arch" in
        linux:amd64) infisical_sha=107389f4c9a0cc48023a834bb2a5bf1280c0a0e45ea7a98d13807d4def21b0a5 ;;
        linux:arm64) infisical_sha=fcfd91de70efdedc7f8c1b1d90a024b433bb185387fe32467d49625a3bf55379 ;;
        darwin:amd64) infisical_sha=d5f80a0d926c84f5875bf927152cadd193a769962af67a3d6f4ba3666f1140ae ;;
        darwin:arm64) infisical_sha=2c44c652b896d5d845abad46348b0b94af1b7be8846491a2501e92e2da43e257 ;;
    esac
    infisical_asset=cli_${infisical_version}_${os}_${arch}.tar.gz
    infisical_target=$HOME/.local/bin/infisical
    check_parents "$infisical_target"
    # Never overwrite a user-managed executable or follow a target symlink.
    if exists "$infisical_target"; then
        log "KEEP    $infisical_target (remove manually to reinstall)"
        return
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        infisical_hasher=(sha256sum)
    elif command -v shasum >/dev/null 2>&1; then
        infisical_hasher=(shasum -a 256)
    else
        fail 'Infisical requires sha256sum or shasum'
    fi
    for tool in curl tar; do
        command -v "$tool" >/dev/null 2>&1 || fail "Infisical requires $tool"
    done
    log "INFISICAL $infisical_version ($os/$arch) -> $infisical_target"
}
install_infisical() (
    exists "$infisical_target" && exit 0
    set -e
    umask 077
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl --fail --location --silent --show-error \
        "https://github.com/Infisical/cli/releases/download/v$infisical_version/$infisical_asset" \
        -o "$tmp/archive.tar.gz"
    (cd "$tmp"; printf '%s  archive.tar.gz\n' "$infisical_sha" | "${infisical_hasher[@]}" -c -)
    # Extract only the binary, not arbitrary archive paths.
    tar -xzf "$tmp/archive.tar.gz" -C "$tmp" infisical
    [ -f "$tmp/infisical" ] && [ ! -L "$tmp/infisical" ] || fail 'Invalid Infisical binary'
    chmod 755 "$tmp/infisical"
    check_parents "$infisical_target"
    mkdir -p "$(dirname "$infisical_target")"
    # noclobber refuses an unexpected file (including a symlink) at the target.
    (set -C; command cat "$tmp/infisical" > "$infisical_target")
    chmod 755 "$infisical_target"
)

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
