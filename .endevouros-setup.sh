#!/usr/bin/env bash
set -e

echo "=== OS Setup Script for EndeavourOS/Arch ==="
echo "Run with: sudo ./setup.sh"

install_packages() {
    echo "=== Installing system packages ==="
    
    # Core packages
    PACMAN_PACKAGES=(
        # Base development
        base-devel git curl wget make gcc pkgconf autoconf automake
        # Shell
        zsh fish bash-completion
        # Terminal & UI
        i3-wm i3blocks i3lock i3status rofi dunst feh scrot
        xfce4-terminal ghostty
        # Network & Bluetooth
        NetworkManager bluez bluez-utils dnsmasq
        # Audio
        pipewire pipewire-alsa pipewire-pulse pipewire-jack
        alsa-utils pavucontrol playerctl
        # Development tools
        vim neovim nodejs npm python python-pip go
        # Build tools
        cmake ninja
        # Fonts
        noto-fonts noto-fonts-cjk noto-fonts-emoji cantarell-fonts
        # Utils
        fzf fd ripgrep bat exa duf htop btop tmux
        parallel tree jq yadm
        # Docker
        docker docker-compose
        # Tools
        arandr brightnessctl xbindkeys
        # Arduino
        arduino-cli
        # Media
        ffmpeg mpv imagemagick
        # Printing
        cups cups-filters system-config-printer
        # Misc
        xclip unrar zip unzip p7zip
        yay
    )
    
    sudo pacman -Syu --needed --noconfirm "${PACMAN_PACKAGES[@]}"
    
    # AUR packages (using yay)
    AUR_PACKAGES=(
        brave-bin
    )
    
    for pkg in "${AUR_PACKAGES[@]}"; do
        if ! pacman -Qq "$pkg" &>/dev/null; then
            yay -S --needed --noconfirm "$pkg"
        fi
    done
}

install_pip_packages() {
    echo "=== Installing Python packages ==="
    
    PIP_PACKAGES=(
        pipx
        uv
        argcomplete
        glances
        psutil
    )
    
    pip3 install --break-system-packages "${PIP_PACKAGES[@]}"
}

install_npm_packages() {
    echo "=== Installing global npm packages ==="
    
    npm install -g node-gyp semver nopt
}

setup_dotfiles() {
    echo "=== Setting up dotfiles ==="
    
    if [ -d "$HOME/.dotfiles" ]; then
        cd "$HOME/.dotfiles"
        git pull
    else
        git clone git@github.com:nodlac/dotfiles.git "$HOME/.dotfiles"
    fi
    
    find "$HOME/.dotfiles" -maxdepth 1 -type f -name ".*" | while read -r f; do
        base=$(basename "$f")
        [ "$base" = ".git" ] && continue
        ln -sf "$f" "$HOME/$base"
    done
    
    if [ -d "$HOME/.dotfiles/.config" ]; then
        find "$HOME/.dotfiles/.config" -maxdepth 1 -type d | while read -r d; do
            base=$(basename "$d")
            mkdir -p "$HOME/.config/$base"
            ln -sf "$d" "$HOME/.config/$base"
        done
    fi
}

setup_i3wm() {
    echo "=== Setting up i3-wm ==="
    
    # Install i3 related packages
    sudo pacman -S --needed --noconfirm \
        i3-wm i3blocks i3lock i3status rofi dunst feh scrot \
        brightnessctl xbindkeys numlockx redshift \
        picom xorg-server lxappearance
        
    # Enable i3wm in display manager or startx
    echo "exec i3" > ~/.xinitrc
}

enable_services() {
    echo "=== Enabling services ==="
    
    # Docker
    sudo systemctl enable docker
    sudo systemctl start docker
    
    # NetworkManager
    sudo systemctl enable NetworkManager
    sudo systemctl start NetworkManager
    
    # Bluetooth
    sudo systemctl enable bluetooth
    sudo systemctl start bluetooth
}

main() {
    install_packages
    install_pip_packages
    install_npm_packages
    setup_dotfiles
    enable_services
    
    echo "=== Setup complete! ==="
    echo "You may want to:"
    echo "  1. Reboot or restart X"
    echo "  2. Set up your dotfiles repo"
    echo "  3. Configure your fonts and theme"
}

main "$@"