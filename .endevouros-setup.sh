#!/usr/bin/env bash
set -e

echo "=== EndeavourOS Setup Script ==="
echo "Run with: sudo ~/.endevouros-setup.sh"
echo ""

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
    CONFIG_FILE="$HOME/.dotfiles/.setup.conf"
    
    if [ -f "$CONFIG_FILE" ]; then
        echo "  Reading from $CONFIG_FILE"
        grep -v '^#' "$CONFIG_FILE" | grep -v '^$' | awk '{print $1}' | sort -u
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
    
    if command -v npm &>/dev/null; then
        npm install -g node-gyp nopt semver
    else
        echo "  npm not found, skipping"
    fi
}

setup_dotfiles() {
    echo "=== Setting up dotfiles ==="
    
    if [ -d "$HOME/.dotfiles" ]; then
        cd "$HOME/.dotfiles"
        git pull
    else
        git clone git@github.com:nodlac/dotfiles.git "$HOME/.dotfiles"
    fi
    
    for f in "$HOME/.dotfiles"/.*; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        [ "$base" = "." ] && continue
        [ "$base" = ".." ] && continue
        [ "$base" = ".git" ] && continue
        ln -sf "$f" "$HOME/$base"
    done
    
    if [ -d "$HOME/.dotfiles/.config" ]; then
        for d in "$HOME/.dotfiles/.config"/*; do
            [ -d "$d" ] || continue
            base=$(basename "$d")
            mkdir -p "$HOME/.config/$base"
            ln -sf "$d" "$HOME/.config/$base"
        done
    fi
}

setup_zsh_plugins() {
    echo "=== Setting up zsh plugins ==="
    
    if [ ! -d "$HOME/.zsh/zsh-history-substring-search" ]; then
        git clone https://github.com/zsh-users/zsh-history-substring-search "$HOME/.zsh/zsh-history-substring-search"
    else
        echo "  zsh-history-substring-search already cloned"
    fi
}

setup_tools() {
    echo "=== Running tools/install.sh ==="
    
    if [ -f "$HOME/.dotfiles/tools/install.sh" ]; then
        source "$HOME/.dotfiles/tools/install.sh"
    else
        echo "  tools/install.sh not found"
    fi
}

enable_services() {
    echo "=== Enabling services ==="
    
    sudo systemctl enable docker 2>/dev/null || true
    sudo systemctl start docker 2>/dev/null || true
    
    sudo systemctl enable NetworkManager 2>/dev/null || true
    sudo systemctl start NetworkManager 2>/dev/null || true
    
    sudo systemctl enable bluetooth 2>/dev/null || true
    sudo systemctl start bluetooth 2>/dev/null || true
}

set_default_shell() {
    echo "=== Setting default shell to zsh ==="
    
    if command -v zsh &>/dev/null; then
        if [ "$SHELL" != "/usr/bin/zsh" ]; then
            chsh -s /usr/bin/zsh
        else
            echo "  zsh already default shell"
        fi
    else
        echo "  zsh not found, skipping"
    fi
}

setup_infisical() {
    echo "=== Setting up Infisical ==="
    
    DOMAIN="thepit.vidnagel.com"
    
    if command -v infisical &>/dev/null; then
        echo "  infisical CLI already installed"
    else
        curl -1sLf https://dl.infisical.com/shell/install.sh | sh
    fi
    
    echo "Run: infisical login"
    echo "Then: infisical secrets pull --project=default --env=dev --format=dotenv -o ~/.env"
}

main() {
    install_yay
    install_packages
    install_pip_packages
    install_npm_packages
    setup_dotfiles
    setup_zsh_plugins
    setup_tools
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