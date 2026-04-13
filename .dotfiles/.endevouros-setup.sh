#!/usr/bin/env bash
set -e

echo "=== EndeavourOS Setup Script ==="
echo "Run with: ~/.dotfiles/.endevouros-setup.sh (without sudo, will prompt for password)"
echo ""

get_user_home() {
    if [ -n "$SUDO_USER" ]; then
        getent passwd "$SUDO_USER" | cut -d: -f6
    else
        echo "$HOME"
    fi
}

install_yay() {
    echo "=== Installing yay (AUR helper) ==="
    if command -v yay &>/dev/null; then
        echo "  yay already installed"
    else
        git clone https://aur.archlinux.org/yay.git /tmp/yay
        cd /tmp/yay
        makepkg -si --noconfirm
        cd -
        rm -rf /tmp/yay
    fi
}

load_packages() {
    USER_HOME=$(get_user_home)
    CONFIG_FILE="$USER_HOME/.dotfiles/.setup.conf"
    
    if [ -f "$CONFIG_FILE" ]; then
        echo "  Reading from $CONFIG_FILE" >&2
        grep -v '^#' "$CONFIG_FILE" | grep -v '^$' | grep -v '^-' | awk '{print $1}' | sort -u
    else
        echo "  $CONFIG_FILE not found, using defaults"
        cat << 'DEFAULTS'
ghostty
i3-wm
rofi
dunst
i3blocks
i3lock
zsh
arduino-cli
nodejs
npm
go
neovim
python
python-pip
pyenv
arandr
brightnessctl
fzf
fd
mcfly
scrot
tmux
xbindkeys
xclip
tldr
valkey
mpv
meld
nwg-look
network-manager-applet
pavucontrol
playerctl
obs-studio
DEFAULTS
    fi
}

install_packages() {
    echo "=== Installing user packages ==="
    
    mapfile -t PACMAN_PACKAGES < <(load_packages)
    
    sudo pacman -Syu --needed --noconfirm "${PACMAN_PACKAGES[@]}"
}

install_aur_packages() {
    echo "=== Installing AUR packages (may retry on failure) ==="
    
    USER_HOME=$(get_user_home)
    CONFIG_FILE="$USER_HOME/.dotfiles/.setup.conf"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        return
    fi
    
    AUR_PACKAGES=$(grep -v '^#' "$CONFIG_FILE" | grep -v '^$' | awk '{print $1}' | grep -E '^-' | sed 's/^-//' | sort -u)
    
    if [ -n "$AUR_PACKAGES" ]; then
        if command -v yay &>/dev/null; then
            for pkg in $AUR_PACKAGES; do
                echo "  Installing $pkg..."
                yay -S --needed --noconfirm "$pkg" || echo "  $pkg failed, skipping"
            done
        else
            echo "  yay not found, skipping AUR packages"
        fi
    fi
}

install_opencode() {
    echo "=== Installing opencode CLI ==="
    USER_HOME=$(get_user_home)
    
    if command -v opencode &>/dev/null; then
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
        pip3 install --break-system-packages --no-cache-dir \
            argcomplete glances psutil python-uv
    else
        echo "  pip3 not found, skipping"
    fi
}

install_npm_packages() {
    echo "=== Installing global npm packages ==="
    USER_HOME=$(get_user_home)
    
    if command -v npm &>/dev/null; then
        NPM_DIR="$USER_HOME/.npm-global"
        mkdir -p "$NPM_DIR"
        
        echo "prefix=$NPM_DIR" > "$USER_HOME/.npmrc"
        
        export PATH="$NPM_DIR/bin:$PATH"
        npm install -g nopt semver 2>/dev/null || true
        
        echo "  Configured npm to use $NPM_DIR"
    else
        echo "  npm not found, skipping"
    fi
}

setup_zsh_plugins() {
    echo "=== Setting up zsh plugins ==="
    USER_HOME=$(get_user_home)
    
    mkdir -p "$USER_HOME/.zsh"
    
    if [ ! -d "$USER_HOME/.zsh/zsh-history-substring-search" ]; then
        echo "  Cloning zsh-history-substring-search..."
        git clone https://github.com/zsh-users/zsh-history-substring-search "$USER_HOME/.zsh/zsh-history-substring-search"
    else
        echo "  zsh-history-substring-search already cloned"
    fi
}

setup_tools() {
    echo "=== Running tools/install.sh ==="
    USER_HOME=$(get_user_home)
    
    if [ -f "$USER_HOME/.dotfiles/tools/install.sh" ]; then
        source "$USER_HOME/.dotfiles/tools/install.sh"
    else
        echo "  tools/install.sh not found"
    fi
}

setup_tmux() {
    echo "=== Setting up tmux ==="
    USER_HOME=$(get_user_home)
    
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
    
    if [ -f "$USER_HOME/.tmux.conf" ]; then
        echo "  Installing tmux plugins..."
        "$USER_HOME/.tmux/plugins/tpm/bin/install_plugins" || true
    fi
    
    echo "  tmux setup complete"
}

enable_services() {
    echo "=== Enabling services ==="
    
    sudo systemctl enable docker 2>/dev/null || true
    sudo systemctl start docker 2>/dev/null || true
    
    sudo systemctl enable NetworkManager 2>/dev/null || true
    sudo systemctl start NetworkManager 2>/dev/null || true
    
    sudo systemctl enable bluetooth 2>/dev/null || true
    sudo systemctl start bluetooth 2>/dev/null || true
    
    if command -v keyd &>/dev/null; then
        echo "=== Configuring keyd for Option key as Meta ==="
        sudo systemctl enable keyd 2>/dev/null || true
        sudo systemctl start keyd 2>/dev/null || true
        
        if [ ! -f /etc/keyd/default.conf ]; then
            sudo mkdir -p /etc/keyd
            sudo tee /etc/keyd/default.conf > /dev/null << 'EOF'
[ids]
*

[main]
left-option = left-meta
right-option = right-meta
EOF
            echo "  Created /etc/keyd/default.conf"
            sudo systemctl restart keyd 2>/dev/null || true
            echo "  Option key now works as Meta"
        else
            echo "  keyd config already exists"
        fi
    fi
}

set_default_shell() {
    echo "=== Setting default shell to zsh ==="
    USER_HOME=$(get_user_home)
    
    if command -v zsh &>/dev/null; then
        if [ "$(getent passwd $(whoami) | cut -d: -f7)" != "/usr/bin/zsh" ]; then
            chsh -s /usr/bin/zsh
        else
            echo "  zsh already default shell"
        fi
    else
        echo "  zsh not found, skipping"
    fi
}

setup_symlinks() {
    echo "=== Setting up symlinks ==="
    USER_HOME=$(get_user_home)
    
    for f in "$USER_HOME/.dotfiles"/.*; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        [ "$base" = "." ] && continue
        [ "$base" = ".." ] && continue
        [ "$base" = ".git" ] && continue
        [ "$base" = ".dotfiles" ] && continue
        if [ -L "$USER_HOME/$base" ]; then
            echo "  $base already linked"
        else
            ln -sf "$f" "$USER_HOME/$base"
            echo "  Linked $base"
        fi
    done
    
    if [ -d "$USER_HOME/.dotfiles/.config" ]; then
        for d in "$USER_HOME/.dotfiles/.config"/*; do
            [ -d "$d" ] || continue
            base=$(basename "$d")
            mkdir -p "$USER_HOME/.config/$base"
            if [ -L "$USER_HOME/.config/$base" ]; then
                echo "  .config/$base already linked"
            else
                ln -sf "$d" "$USER_HOME/.config/$base"
                echo "  Linked .config/$base"
            fi
        done
    fi
}

main() {
    setup_symlinks
    install_yay
    install_packages
    install_aur_packages
    install_opencode
    install_pip_packages
    install_npm_packages
    setup_zsh_plugins
    setup_tools
    setup_tmux
    enable_services
    set_default_shell
    # setup_infisical
    
    echo ""
    echo "=== Setup complete! ==="
    echo ""
    echo "Next steps:"
    echo "  1. Restart shell or log out/in"
    echo "  2. Uncomment setup_infisical() and run to set up Infisical at thepit.vidnagel.com"
}

main "$@"