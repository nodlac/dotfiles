#!/usr/bin/env bash
# .server-setup.sh — Ubuntu Server (headless) setup for the dotfiles "server" branch.
# Run without sudo: ~/.dotfiles/.server-setup.sh  (prompts for sudo password when needed)
set -e

TARGET_USER="${SUDO_USER:-$USER}"

get_user_home() {
    if [ -n "$SUDO_USER" ]; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        echo "$HOME"
    fi
}

USER_HOME=$(get_user_home)
DOTFILES_DIR="$USER_HOME/.dotfiles"

echo "=== Ubuntu Server Setup Script ==="
echo "Run with: ~/.dotfiles/.server-setup.sh (without sudo, will prompt for password)"
echo ""

init_dotfiles_repo() {
    echo "=== Configuring dotfiles git repo ==="
    if git --git-dir="$DOTFILES_DIR" rev-parse --git-dir &>/dev/null; then
        git --git-dir="$DOTFILES_DIR" config core.bare false
        git --git-dir="$DOTFILES_DIR" config core.worktree "$USER_HOME"
        git --git-dir="$DOTFILES_DIR" config status.showUntrackedFiles no
        # df-test runs on every commit. tools/git-hooks is tracked; $DOTFILES_DIR/hooks is not.
        git --git-dir="$DOTFILES_DIR" config core.hooksPath "$USER_HOME/tools/git-hooks"
        echo "  Configured: bare=false, worktree=$USER_HOME, untracked=hidden"
    else
        echo "  $DOTFILES_DIR is not a git repo — do the bare clone first (see README)"
        exit 1
    fi
    echo ""
}

setup_symlinks() {
    echo "=== Setting up symlinks ==="

    for f in "$DOTFILES_DIR"/.*; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        [ "$base" = "." ] && continue
        [ "$base" = ".." ] && continue
        [ "$base" = ".git" ] && continue
        [ "$base" = ".dotfiles" ] && continue
        if [ -L "$USER_HOME/$base" ]; then
            echo "  $base already linked"
        else
            ln -sf "$DOTFILES_DIR/$base" "$USER_HOME/$base"
            echo "  Linked $base"
        fi
    done
}

load_packages() {
    CONFIG_FILE="$USER_HOME/.dotfiles/.setup.conf"

    if [ -f "$CONFIG_FILE" ]; then
        echo "  Reading from $CONFIG_FILE" >&2
        grep -v '^#' "$CONFIG_FILE" | grep -v '^$' | grep -v '^-' | awk '{print $1}' | sort -u
    else
        echo "  $CONFIG_FILE not found, using defaults"
        cat << 'DEFAULTS'
zsh
tmux
git
curl
build-essential
python3-pip
python3-venv
fzf
fd-find
ripgrep
bat
jq
htop
unzip
tealdeer
DEFAULTS
    fi
}

load_optional_packages() {
    CONFIG_FILE="$USER_HOME/.dotfiles/.setup.conf"
    [ -f "$CONFIG_FILE" ] || return 0
    grep -v '^#' "$CONFIG_FILE" | grep -v '^$' | awk '{print $1}' | grep -E '^-' | sed 's/^-//' | sort -u
}

install_packages() {
    echo "=== Installing apt packages ==="

    mapfile -t APT_PACKAGES < <(load_packages)
    if ((${#APT_PACKAGES[@]})); then
        sudo apt-get update
        sudo apt-get install -y "${APT_PACKAGES[@]}"
    fi

    mapfile -t OPT_PACKAGES < <(load_optional_packages)
    for pkg in "${OPT_PACKAGES[@]}"; do
        echo "  Installing optional $pkg..."
        sudo apt-get install -y "$pkg" || echo "  $pkg failed, skipping"
    done
}

fix_ubuntu_names() {
    echo "=== Fixing Debian/Ubuntu binary names ==="
    mkdir -p "$USER_HOME/.local/bin"

    if command -v fdfind &>/dev/null && [ ! -e "$USER_HOME/.local/bin/fd" ]; then
        ln -sf "$(command -v fdfind)" "$USER_HOME/.local/bin/fd"
        echo "  fd → fdfind"
    fi
    if command -v batcat &>/dev/null && [ ! -e "$USER_HOME/.local/bin/bat" ]; then
        ln -sf "$(command -v batcat)" "$USER_HOME/.local/bin/bat"
        echo "  bat → batcat"
    fi
}

install_tmux() {
    echo "=== Checking tmux (config uses tmux 3.5+ when available) ==="

    local tmux_cmd tmux_version tmux_major tmux_minor
    tmux_cmd="$USER_HOME/.local/bin/tmux"
    if [ ! -x "$tmux_cmd" ]; then
        tmux_cmd=$(command -v tmux || true)
    fi

    if [ -n "$tmux_cmd" ] && [ -x "$tmux_cmd" ]; then
        tmux_version=$("$tmux_cmd" -V 2>/dev/null | awk '{print $2}' | head -1)
        tmux_major="${tmux_version%%.*}"
        tmux_minor="${tmux_version#*.}"
        tmux_minor="${tmux_minor%%[^0-9]*}"
        if [[ "$tmux_major" =~ ^[0-9]+$ && "$tmux_minor" =~ ^[0-9]+$ ]] && \
           (( tmux_major > 3 || (tmux_major == 3 && tmux_minor >= 5) )); then
            echo "  tmux $tmux_version already installed"
            return
        fi
    fi

    local build_dir
    build_dir=$(mktemp -d /tmp/tmux-build.XXXXXX)
    echo "  Building tmux 3.5a in $build_dir..."
    git clone --depth 1 --branch 3.5a https://github.com/tmux/tmux.git "$build_dir"
    (
        cd "$build_dir"
        sh autogen.sh
        ./configure --prefix="$USER_HOME/.local"
        make -j"$(nproc)"
        make install
    )
    rm -rf "$build_dir"
    echo "  tmux installed to $USER_HOME/.local/bin/tmux"
}

install_neovim() {
    echo "=== Checking neovim (config needs >= 0.10) ==="

    if command -v nvim &>/dev/null; then
        local ver major minor
        ver=$(nvim --version | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=${ver%%.*}
        minor=${ver##*.}
        if (( major > 0 || minor >= 10 )); then
            echo "  nvim $ver already installed"
            return
        fi
        echo "  nvim $ver too old — installing stable from GitHub"
    fi

    local arch tarball
    arch=$(uname -m)
    case "$arch" in
        x86_64)  tarball="nvim-linux-x86_64.tar.gz" ;;
        aarch64) tarball="nvim-linux-arm64.tar.gz" ;;
        *) echo "  unsupported arch $arch, skipping"; return ;;
    esac

    curl -fsSL "https://github.com/neovim/neovim/releases/download/stable/$tarball" -o /tmp/nvim.tar.gz
    rm -rf "$USER_HOME/.local/nvim"
    mkdir -p "$USER_HOME/.local/nvim" "$USER_HOME/.local/bin"
    tar -xzf /tmp/nvim.tar.gz -C "$USER_HOME/.local/nvim" --strip-components=1
    rm /tmp/nvim.tar.gz
    ln -sf "$USER_HOME/.local/nvim/bin/nvim" "$USER_HOME/.local/bin/nvim"
    echo "  nvim installed → ~/.local/bin/nvim"
}

install_opencode() {
    echo "=== Installing opencode CLI ==="

    if [ -f "$USER_HOME/.opencode/bin/opencode" ] || [ -f "/usr/local/bin/opencode" ]; then
        echo "  opencode already installed"
    else
        mkdir -p "$USER_HOME/.opencode/bin"
        curl -fsSL https://opencode.ai/install | sh
        echo "  opencode installed to $USER_HOME/.opencode/bin"
    fi
}

install_pip_packages() {
    echo "=== Installing Python packages ==="

    if command -v pip3 &>/dev/null; then
        pip3 install --user --break-system-packages --no-cache-dir \
            argcomplete glances psutil uv
    else
        echo "  pip3 not found, skipping"
    fi
}

setup_zsh_plugins() {
    echo "=== Setting up zsh plugins ==="

    mkdir -p "$USER_HOME/.zsh"

    declare -A ZSH_PLUGINS=(
        [zsh-history-substring-search]="https://github.com/zsh-users/zsh-history-substring-search"
        [zsh-autosuggestions]="https://github.com/zsh-users/zsh-autosuggestions"
        [zsh-completions]="https://github.com/zsh-users/zsh-completions"
        [fast-syntax-highlighting]="https://github.com/zdharma-continuum/fast-syntax-highlighting"
        [fzf-tab]="https://github.com/Aloxaf/fzf-tab"
    )

    for plugin in "${!ZSH_PLUGINS[@]}"; do
        if [ -d "$USER_HOME/.zsh/$plugin" ]; then
            echo "  $plugin already installed"
        else
            echo "  Cloning $plugin..."
            git clone --depth 1 "${ZSH_PLUGINS[$plugin]}" "$USER_HOME/.zsh/$plugin"
        fi
    done
}

setup_tmux() {
    echo "=== Setting up tmux ==="

    if ! command -v tmux &>/dev/null; then
        echo "  tmux not found, skipping"
        return
    fi

    TPM_DIR="$USER_HOME/.tmux/plugins/tpm"
    if [ ! -d "$TPM_DIR" ]; then
        echo "  Installing TPM..."
        git clone https://github.com/tmux-plugins/tpm "$TPM_DIR"
    else
        echo "  TPM already installed"
    fi

    PLUGIN_DIR="$USER_HOME/.tmux/plugins"
    mkdir -p "$PLUGIN_DIR"

    TMUX_PLUGINS=(
        "jimeh/tmux-themepack"
        "tmux-plugins/tmux-resurrect"
        "tmux-plugins/tmux-continuum"
    )

    for plugin in "${TMUX_PLUGINS[@]}"; do
        plugin_name=$(basename "$plugin")
        if [ ! -d "$PLUGIN_DIR/$plugin_name" ]; then
            echo "  Cloning $plugin..."
            git clone --depth 1 "https://github.com/$plugin" "$PLUGIN_DIR/$plugin_name"
        else
            echo "  $plugin_name already installed"
        fi
    done

    echo "  tmux setup complete"
}

setup_env_file() {
    echo "=== Setting up ~/.env ==="
    local env_file="$USER_HOME/.env"

    if [ ! -f "$env_file" ]; then
        printf 'export MACHINE_ENV="server"\n' > "$env_file"
        echo "  created ~/.env with MACHINE_ENV=server"
    elif grep -q '^export MACHINE_ENV=.\+' "$env_file"; then
        echo "  MACHINE_ENV already set"
    elif grep -q '^export MACHINE_ENV=' "$env_file"; then
        sed -i 's/^export MACHINE_ENV=.*/export MACHINE_ENV="server"/' "$env_file"
        echo "  set MACHINE_ENV=server"
    else
        printf '\nexport MACHINE_ENV="server"\n' >> "$env_file"
        echo "  added MACHINE_ENV=server"
    fi
}

setup_tools() {
    echo "=== Running tools/install.sh ==="

    if [ -f "$USER_HOME/tools/install.sh" ]; then
        source "$USER_HOME/tools/install.sh"
    else
        echo "  tools/install.sh not found"
    fi
}

setup_agent_tools() {
    echo "=== Installing agent-tools ==="
    local repo_url="${AGENT_TOOLS_REPO:-git@github.com:nodlac/agent-dashboard.git}"
    local repo_dir="${AGENT_TOOLS_DIR:-$USER_HOME/repos/agent-tools}"

    if [ -d "$repo_dir/.git" ]; then
        echo "  $repo_dir exists — pulling"
        git -C "$repo_dir" pull --ff-only || echo "  pull failed (leaving as-is)"
    else
        mkdir -p "$(dirname "$repo_dir")"
        git clone "$repo_url" "$repo_dir" || { echo "  clone failed"; return; }
    fi
    if [ -x "$repo_dir/install.sh" ]; then
        "$repo_dir/install.sh"
    fi
}

setup_docker() {
    if command -v docker &>/dev/null; then
        echo "=== Configuring docker ==="
        sudo systemctl enable --now docker 2>/dev/null || true
        if id -nG "$TARGET_USER" | grep -qw docker; then
            echo "  $TARGET_USER already in docker group"
        else
            sudo usermod -aG docker "$TARGET_USER"
            echo "  added $TARGET_USER to docker group (log out/in to apply)"
        fi
    fi
}

set_default_shell() {
    echo "=== Setting default shell to zsh ==="

    if ! command -v zsh &>/dev/null; then
        echo "  zsh not found, skipping"
        return
    fi

    local zsh_path
    zsh_path=$(command -v zsh)
    if [ "$(getent passwd "$TARGET_USER" | cut -d: -f7)" != "$zsh_path" ]; then
        sudo chsh -s "$zsh_path" "$TARGET_USER"
        echo "  default shell → $zsh_path (takes effect next login)"
    else
        echo "  zsh already default shell"
    fi
}

main() {
    init_dotfiles_repo
    setup_symlinks
    install_packages
    install_tmux
    fix_ubuntu_names
    install_neovim
    install_opencode
    install_pip_packages
    setup_zsh_plugins
    setup_tmux
    setup_env_file
    setup_docker
    set_default_shell
    # setup_tools          # work tools (ClickUp/sprint-sync) — uncomment if wanted
    # setup_agent_tools    # agent-dashboard — uncomment if wanted

    echo ""
    echo "=== Setup complete! ==="
    echo ""
    echo "Next steps:"
    echo "  1. Log out/in (default shell → zsh, docker group)"
    echo "  2. Run 'df-test' to validate the dotfiles"
    echo "  3. Optional: uncomment setup_tools / setup_agent_tools above and re-run"
}

main "$@"
