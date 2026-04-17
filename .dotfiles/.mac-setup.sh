#!/usr/bin/env bash
set -e

USER_HOME="$HOME"
DOTFILES_DIR="$USER_HOME/.dotfiles"

echo "=== macOS Setup Script ==="
echo "Run with: ~/.dotfiles/.mac-setup.sh"
echo ""

# ───────────────────────────────────────────
# Dotfiles git repo config
# ───────────────────────────────────────────
init_dotfiles_repo() {
    if [ -d "$DOTFILES_DIR/.git" ]; then
        CURRENT_WORKTREE=$(git --git-dir="$DOTFILES_DIR" config core.worktree 2>/dev/null || true)
        CURRENT_BARE=$(git --git-dir="$DOTFILES_DIR" config core.bare 2>/dev/null || true)

        if [ "$CURRENT_WORKTREE" != "$USER_HOME" ] || [ "$CURRENT_BARE" != "false" ]; then
            echo "=== Configuring dotfiles git repo ==="
            git --git-dir="$DOTFILES_DIR" config core.bare false
            git --git-dir="$DOTFILES_DIR" config core.worktree "$USER_HOME"
            git --git-dir="$DOTFILES_DIR" config status.showUntrackedFiles no
            echo "  Configured: bare=false, worktree=$USER_HOME, untracked=hidden"
        fi
    fi
}

# ───────────────────────────────────────────
# Homebrew
# ───────────────────────────────────────────
install_homebrew() {
    echo "=== Checking Homebrew ==="
    if command -v brew &>/dev/null; then
        echo "  Homebrew already installed"
    else
        echo "  Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
}

install_brew_packages() {
    echo "=== Installing Homebrew formulae ==="

    FORMULAE=(
        # Shell & Terminal
        zsh
        tmux
        fzf
        fd
        ripgrep
        bat
        mcfly

        # Development
        neovim
        go
        node
        fnm
        pyenv
        python@3
        pipx
        uv
        arduino-cli

        # Tools
        lazygit
        awscli
        vault
        telnet
        valkey

        # Media
        ffmpeg
    )

    brew install "${FORMULAE[@]}" 2>/dev/null || true
    echo "  Formulae done"
}

install_brew_casks() {
    echo "=== Installing Homebrew casks ==="

    CASKS=(
        ghostty
        aerospace
        brave-browser
        slack
        figma
        notunes
        obs
        kdenlive
        inkscape
        gimp
        colima
        docker
        local
        google-drive
    )

    brew install --cask "${CASKS[@]}" 2>/dev/null || true
    echo "  Casks done"

    read -p "  Install test browsers (Firefox, Chrome, Edge)? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        brew install --cask firefox google-chrome microsoft-edge 2>/dev/null || true
        echo "  Test browsers done"
    fi
}

# ───────────────────────────────────────────
# Symlinks
# ───────────────────────────────────────────
# The dotfiles repo uses a hybrid layout:
#   - ~/.dotfiles/.zshrc, .tmux.conf, etc. → symlinked to ~/
#   - ~/.config/*, ~/.zsh/*, ~/tools/, etc. → checked out directly by git
# This function only handles the first group.
setup_symlinks() {
    echo "=== Setting up symlinks ==="

    for f in "$DOTFILES_DIR"/.*; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        case "$base" in
            .|..|.git|.dotfiles|.DS_Store) continue ;;
        esac
        if [ -L "$USER_HOME/$base" ]; then
            echo "  $base already linked"
        elif [ -f "$USER_HOME/$base" ]; then
            echo "  $base exists (not symlink) — backing up to $base.bak"
            mv "$USER_HOME/$base" "$USER_HOME/$base.bak"
            ln -sf "$DOTFILES_DIR/$base" "$USER_HOME/$base"
            echo "  Linked $base"
        else
            ln -sf "$DOTFILES_DIR/$base" "$USER_HOME/$base"
            echo "  Linked $base"
        fi
    done
}

# ───────────────────────────────────────────
# Zsh plugins
# ───────────────────────────────────────────
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

# ───────────────────────────────────────────
# Tmux plugins
# ───────────────────────────────────────────
setup_tmux() {
    echo "=== Setting up tmux ==="

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
}

# ───────────────────────────────────────────
# npm global packages
# ───────────────────────────────────────────
install_npm_packages() {
    echo "=== Installing global npm packages ==="
    if command -v npm &>/dev/null; then
        NPM_DIR="$USER_HOME/.npm-global"
        mkdir -p "$NPM_DIR"
        echo "prefix=$NPM_DIR" > "$USER_HOME/.npmrc"
        export PATH="$NPM_DIR/bin:$PATH"
        npm install -g neovim tree-sitter-cli 2>/dev/null || true
        echo "  npm globals done"
    else
        echo "  npm not found, skipping"
    fi
}

# ───────────────────────────────────────────
# pip packages
# ───────────────────────────────────────────
install_pip_packages() {
    echo "=== Installing Python packages ==="
    if command -v pip3 &>/dev/null; then
        pip3 install --break-system-packages --no-cache-dir \
            argcomplete glances psutil 2>/dev/null || true
        echo "  pip packages done"
    else
        echo "  pip3 not found, skipping"
    fi
}

# ───────────────────────────────────────────
# opencode
# ───────────────────────────────────────────
install_opencode() {
    echo "=== Installing opencode CLI ==="
    if [ -f "$USER_HOME/.opencode/bin/opencode" ] || command -v opencode &>/dev/null; then
        echo "  opencode already installed"
    else
        mkdir -p "$USER_HOME/.opencode/bin"
        curl -fsSL https://opencode.ai/install | sh
        echo "  opencode installed"
    fi
}

# ───────────────────────────────────────────
# tools/install.sh
# ───────────────────────────────────────────
setup_tools() {
    echo "=== Running tools/install.sh ==="
    if [ -f "$DOTFILES_DIR/tools/install.sh" ]; then
        source "$DOTFILES_DIR/tools/install.sh"
    else
        echo "  tools/install.sh not found"
    fi
}

# ───────────────────────────────────────────
# agent-tools (separate repo)
# ───────────────────────────────────────────
AGENT_TOOLS_REPO="${AGENT_TOOLS_REPO:-git@github.com:nodlac/agent-dashboard.git}"
AGENT_TOOLS_DIR="${AGENT_TOOLS_DIR:-$HOME/repos/agent-tools}"

setup_agent_tools() {
    echo "=== Installing agent-tools ==="
    if [ -d "$AGENT_TOOLS_DIR/.git" ]; then
        echo "  $AGENT_TOOLS_DIR exists — pulling"
        git -C "$AGENT_TOOLS_DIR" pull --ff-only || echo "  pull failed (leaving as-is)"
    else
        mkdir -p "$(dirname "$AGENT_TOOLS_DIR")"
        git clone "$AGENT_TOOLS_REPO" "$AGENT_TOOLS_DIR" || { echo "  clone failed"; return; }
    fi
    if [ -x "$AGENT_TOOLS_DIR/install.sh" ]; then
        "$AGENT_TOOLS_DIR/install.sh"
    fi
}

# ───────────────────────────────────────────
# macOS defaults
# ───────────────────────────────────────────
set_macos_defaults() {
    echo "=== Setting macOS defaults ==="

    # Key repeat speed (lower = faster)
    defaults write NSGlobalDomain KeyRepeat -int 2
    defaults write NSGlobalDomain InitialKeyRepeat -int 15

    echo "  Key repeat set (fast)"
    echo "  NOTE: Set Caps Lock -> Escape in System Settings > Keyboard > Modifier Keys"
}

# ───────────────────────────────────────────
# Main
# ───────────────────────────────────────────
main() {
    init_dotfiles_repo
    install_homebrew
    install_brew_packages
    install_brew_casks
    setup_symlinks
    setup_zsh_plugins
    setup_tmux
    install_npm_packages
    install_pip_packages
    install_opencode
    setup_tools
    setup_agent_tools
    set_macos_defaults

    echo ""
    echo "=== Setup complete! ==="
    echo ""
    echo "Next steps:"
    echo "  1. Restart shell or: source ~/.zshrc"
    echo "  2. Set Caps Lock -> Escape in System Settings > Keyboard > Modifier Keys"
    echo "  3. Start aerospace: open -a AeroSpace"
    echo "  4. tmux: prefix + I to install plugins (Ctrl-Space + I)"
}

main "$@"
