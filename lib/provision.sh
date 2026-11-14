# Explicit OS provisioning, separate from configuration links. Bash 3.2 compatible.
# No downloaded installers, credential loading, group changes or shell changes.
plan_system() {
    case "$DF_OS:$DF_DISTRO:$DF_WSL" in
        macos:*)
            [ "$profile" = desktop ] || fail '--configure-system on macOS requires --profile desktop'
            command -v defaults >/dev/null 2>&1 || fail 'macOS defaults command is required'
            log 'SYSTEM  macOS: fast key repeat; disable input-source/Dictation hotkeys; Spotlight on Option-D' ;;
        linux:arch:none|linux:endeavouros:none|linux:ubuntu:none|linux:debian:none)
            command -v systemctl >/dev/null 2>&1 || fail 'System provisioning requires systemd'
            system_services=(docker)
            if [ "$profile" = desktop ]; then
                system_services+=(NetworkManager bluetooth)
            fi
            log "SYSTEM  sudo systemctl enable --now ${system_services[*]}"
            log 'SYSTEM  Required service packages must already be installed (or use --install-packages).' ;;
        *) fail "System provisioning is not reviewed for $DF_OS/$DF_DISTRO/$DF_WSL" ;;
    esac
}
configure_system() {
    case "$DF_OS" in
        macos)
            defaults write NSGlobalDomain KeyRepeat -int 2
            defaults write NSGlobalDomain InitialKeyRepeat -int 15
            for hotkey in 60 61 164; do
                defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys \
                    -dict-add "$hotkey" '<dict><key>enabled</key><false/></dict>'
            done
            defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 64 \
                '<dict><key>enabled</key><true/><key>value</key><dict><key>parameters</key><array><integer>100</integer><integer>2</integer><integer>524288</integer></array><key>type</key><string>standard</string></dict></dict>'
            log 'macOS keyboard defaults applied; log out/in to activate. Approve Karabiner permissions separately.' ;;
        linux) sudo systemctl enable --now "${system_services[@]}" ;;
    esac
}
