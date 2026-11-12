# Opt-in Firehawk bootstrap planning. Bash 3.2 compatible.
plan_firehawk() {
    local file name
    for file in firehawk/firehawk-theme firehawk/theme/palette.toml \
        firehawk/profiles/default.toml \
        firehawk/templates/hypr/hyprland.lua firehawk/templates/hypr/keyboards.lua \
        firehawk/templates/hypr/hyprlock.conf \
        firehawk/templates/hypr/hypridle.conf firehawk/templates/waybar/style.css \
        firehawk/templates/rofi/firehawk.rasi firehawk/templates/swaync/style.css \
        firehawk/templates/scripts/screenshot firehawk/templates/scripts/recent-files.py \
        firehawk/templates/scripts/recent-files.css; do
        [ -f "$ROOT/$file" ] || fail "Missing Firehawk source: $file"
    done
    case "$theme_profile" in
        auto) ;;
        ''|*[!a-z0-9-]*) fail "Invalid Firehawk profile: $theme_profile" ;;
        *) [ -f "$ROOT/firehawk/profiles/$theme_profile.toml" ] || fail "Missing Firehawk profile: $theme_profile" ;;
    esac
    check_parents "$HOME/.config/firehawk/current"
    check_parents "$HOME/.local/state/firehawk/generations/placeholder"
    if exists "$HOME/.config/firehawk/current" && [ ! -L "$HOME/.config/firehawk/current" ]; then
        fail 'Firehawk current must be absent or a symlink; review it manually'
    fi
    log "THEME   Firehawk profile=$theme_profile; Python >=3.11 + Pillow required for generation"
    log 'GENERATE immutable theme; retain previous generations; do not reload the running desktop'
    for name in hypr waybar swaync; do
        add_link "$HOME/.config/firehawk/current/$name" "$HOME/.config/$name" generated
    done
    # Expose a stable user command without changing PATH or existing shell config.
    add_link "$ROOT/firehawk/firehawk-theme" "$HOME/.local/bin/firehawk-theme"
}
build_firehawk() {
    command -v python3 >/dev/null 2>&1 || fail 'Firehawk needs Python >=3.11; use --install-packages or install it manually'
    python3 -c 'import sys; assert sys.version_info >= (3,11); import PIL' ||
        fail 'Firehawk needs Python >=3.11 and Pillow; no config links were changed'
    if [ "$theme_profile" = auto ]; then
        python3 -B "$ROOT/firehawk/firehawk-theme" apply
    else
        python3 -B "$ROOT/firehawk/firehawk-theme" apply "$theme_profile"
    fi
}
