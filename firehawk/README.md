# Ember desktop theme

Ember is the desktop theme name, not a business name. BEHEMOTH is this machine's
identity; business branding remains separate. The theme keeps the orange/red,
near-black and white palette without displaying the former business logo/name.

Existing `firehawk/` directories, commands and setup option values are retained
for compatibility until a separate technical rename. i3 remains the default desktop
and a fallback. This optional Hyprland path targets native Arch/EndeavourOS.

## Deploy through the dotfiles entry point

From the repository root:

```sh
./setup.sh --machine behemoth --profile desktop --desktop firehawk --theme-profile behemoth --dry-run

# Review the plan. Package installation requests sudo and a full Arch upgrade:
./setup.sh --machine behemoth --profile desktop --desktop firehawk --theme-profile behemoth --install-packages
```

Run as your ordinary user, never via sudo. Save work before approving a system
upgrade; review pacman's transaction. Setup never logs you out, restarts your
desktop, removes i3, changes the login manager, or enables services.

- Default/headless/macOS workflows stay unchanged.
- `--desktop` requires `--profile desktop` and native Arch/EndeavourOS.
- Omit `--install-packages` for config-only deployment. It requires Python >=3.11,
  Pillow, fontconfig and a monospace font already installed.
- `--dry-run` only reports source/target checks, theme plan and optional package
  plans. It does not run Python, render a wallpaper, write config or invoke sudo.
- Existing configs are conflicts. Review `--replace --dry-run` before explicitly
  approving `--replace`; originals go to the existing dotfiles backup tree.
- All links are preflighted before generation. Packages, when requested, are
  installed before generation so they can supply Python/Pillow. Package failure
  leaves config links untouched. This is not an OS/filesystem-wide transaction.
- Missing/failed generation never installs broken config links. A successful
  generation can remain staged if later filesystem linking fails.
- No automatic application reload. Do not run setup/theme commands concurrently.

For another machine, omit `--machine behemoth` (generic shell profile), and select
its visual profile independently with `--theme-profile NAME`. Without that option,
the generator selects local override > hostname alias > default.
System hostnames are never changed.

## What setup manages

```text
~/.config/hypr     -> ~/.config/firehawk/current/hypr
~/.config/waybar   -> ~/.config/firehawk/current/waybar
~/.config/swaync   -> ~/.config/firehawk/current/swaync
~/.local/bin/firehawk-theme -> <checkout>/firehawk/firehawk-theme
```

The ordinary shared shell/tmux/machine links and existing Ghostty config link
are also managed by the main setup. The Firehawk terminal palette is opt-in below.

Immutable generations live under `~/.local/state/firehawk/generations/`;
`~/.config/firehawk/current` is switched atomically only after a complete build.
Input and generated-output hashes make unchanged reruns idempotent and detect
damaged outputs. Old generations are retained, not automatically pruned.
Generation errors preserve the previous current theme.

Repository contents:

```text
theme/palette.toml       Shared Firehawk tokens
profiles/*.toml         Ship identity, hostname aliases, optional colors/modules
hosts/behemoth.toml      Hardware audit notes (not automatically loaded)
assets/brand/FMA.png     Retained historical asset; not used or required by Ember
templates/              Maintained config/script sources
firehawk-theme          Generation, inspection and recovery utility
test_theme.py           Isolated theme and deployment regression tests
```

## Current implementation

- Templates target Hyprland **0.57 Lua**, based on the Arch 0.57.2 bundled example.
- BEHEMOTH matches `behemoth` and the current hostname `supernerd`.
- Wallpaper: 2560×1440, restrained ring/structural motif, machine ID and Ember theme name; no business logo.
- Waybar: ship ID, Downloads/Screenshots quick menus, workspaces, clock, CPU,
  RAM, audio, network, tray, notices.
- Mobile profiles can add a battery module.
- Matching Rofi, SwayNC, hyprlock, hyprpaper, and hypridle configuration.
- Optional Ghostty foreground/background/cursor/selection snippet; ANSI semantic
  colors remain unchanged.
- Idle lock after 10 minutes; lock request before sleep.
- No automatic clipboard capture/history. Business secrets should not be retained.
- No blanket NVIDIA environment variables. DRM modesetting was already enabled
  on the initial machine; preferred monitor mode and scale 1 are the initial defaults.

Automatic suspend/DPMS, power menu, keybinding popup, clipboard
picker, media bar module, scratch-terminal spawning, GTK/icons and detailed window
rules are deferred. Locks, sleep/wake, screen sharing and compositor APIs must be
validated in a real Wayland session before calling the desktop production-ready.
Hardware notes are deliberately separate from visual identity and do not impose
Behemoth's monitor/GPU settings on another machine.

## Profiles and local customization

```sh
firehawk-theme preview
firehawk-theme preview behemoth
firehawk-theme apply behemoth
firehawk-theme apply --force       # e.g. force rendering after font changes
firehawk-theme doctor
```

Before command-link installation, invoke `./firehawk/firehawk-theme` from the repo.
Selection order: explicit argument > `~/.config/firehawk/profile` containing one
profile name > short hostname alias > default. Local overrides stay outside Git.

Create `profiles/callisto.toml`, for example (choose aliases appropriate to your host):

```toml
name = "CALLISTO"
role = "MOBILE OPERATIONS"
aliases = ["callisto-laptop"]
mobile = true

# Optional overrides; omitted tokens inherit the shared brand:
[colors]
orange = "#FF7700"
```

Names/roles use uppercase letters, digits, spaces, slash, underscore and hyphen.
Aliases must be unique across profiles. Profile filenames use lowercase letters,
digits and hyphens. Color keys must match shared tokens and values must be #RRGGBB.

Edit `templates/` then apply again. For personal Lua bindings/monitor overrides,
create `~/.config/firehawk/local.lua`; it is loaded last and is never generated,
backed up or overwritten by theme commands. Do not edit generated configs directly.

Ghostty integration is deliberately opt-in. After reviewing its existing config,
add this line yourself:

```text
config-file = ~/.config/firehawk/current/ghostty.conf
```

Rofi gets an explicit theme path, preserving your existing Rofi configuration.

## Downloads and Screenshots quick menus

Only two pinned folder buttons: **Downloads** and **Screenshots**. Each opens a
Firehawk-styled GTK popup with the five newest modified regular files from
`~/Downloads` or `~/Pictures/Screenshots`. It refreshes on every opening, skips
hidden/in-progress downloads and symlinks, and never recursively lists subfolders.
An empty/missing folder is handled without creating it just to show the menu.

- Drag a row into an app that accepts file drops (attachments, uploads, etc.).
- Click a row to open it with its default application.
- **Open folder** opens the full directory in your default file manager.
- Escape, the close button, or clicking the same bar button again dismisses it.
- On Wayland, `gtk-layer-shell` positions it below the bar without tiling it.

Drag payloads are standard `text/uri-list` file URIs, not text filenames or copied
file contents. Drags advertise **copy only**: the popup never moves/deletes files
or uploads anything itself. Drop acceptance depends on the target application's
Wayland/XWayland/sandbox support and needs live testing. No history database,
file-content indexing or thumbnails are maintained.

The package manifest includes PyGObject, GTK3, gtk-layer-shell and Thunar. Existing
file associations are not changed. No extra folders or folders menu are added.

## Apple keyboard remap

`templates/hypr/keyboards.lua` ports the existing i3 modifier mapping using native
XKB options (`altwin:swap_alt_win,caps:escape`), applied only to the Apple Magic
Keyboard with Touch ID and Numeric Keypad (including its duplicate input node).

| Physical key | Hyprland meaning |
|---|---|
| Option, left/right | Super |
| Command, left/right | Alt |
| Caps Lock | Escape |
| Control | Unchanged |

Thus **Option+Enter** opens Ghostty and **Option+D** opens the launcher. Command
is not Control; the remap mirrors the existing X11 setup. The Glove80 firmware
layout and other keyboards are untouched. This does not modify X11/i3, TTY keys,
the login screen, or a system-wide driver option. Existing Command-based i3
screenshot bindings are separate and are not ported by this modifier remap.

After login, check `hyprctl devices` for the exact Apple keyboard name and options.
If the device appears under a different name (for example via Bluetooth), adapt
the device rule rather than applying the swap globally. Physical-key behavior
still requires testing in the live Wayland session.

## Initial bindings

| Keys | Action |
|---|---|
| Super+Enter | Ghostty |
| Super+D | App launcher |
| Super+Q | Close window |
| Super+F | Fullscreen |
| Super+V | Toggle floating |
| Super+arrows | Focus |
| Super+1…0 | Workspace |
| Super+Shift+1…0 | Move to workspace |
| Super+S / Super+Shift+S | Show scratch workspace / move window there |
| Super+mouse drag | Move/resize |
| Super+N | Notification center |
| Print | Region screenshot to clipboard |
| Super+Print | Full screenshot to ~/Pictures/Screenshots |
| Shift+Print | Region screenshot in Swappy |
| Super+Shift+Escape | Lock |
| Super+Shift+C | Reload Hyprland config |

Region cancellation does not change the clipboard or create persistent captures.
Temporary screenshots are removed on exit; clipboard history capture is disabled.

## Login and runtime checklist

Save your work, log out normally and select **Hyprland** for initial testing.
Do not launch another compositor inside i3. UWSM is available as a package but is
not configured/required by this initial startup path. LightDM's Wayland session
listing has not been validated here. If Hyprland is not offered, keep the greeter
unchanged: after logging out, use a separate TTY (Ctrl+Alt+F3), log in as yourself,
and run `Hyprland` there. Do not run it as root or inside the existing X11 session.

Run `firehawk-theme doctor` and `hyprctl configerrors` from Hyprland. Test:

- [ ] Correct resolution/refresh and readable scaling
- [ ] Workspace bindings, floating/fullscreen, scratch workspace, launcher
- [ ] Ghostty, native Wayland and XWayland applications
- [ ] Waybar, audio/mic controls, notifications, polkit authentication
- [ ] Downloads/Screenshots popups: latest five, open, dismiss, real file drop
- [ ] Screenshot copy/save/edit and region cancellation
- [ ] Manual lock, idle lock, successful unlock and lock-before-sleep
- [ ] NVIDIA suspend/resume and display wake
- [ ] Browser/Electron screen sharing through desktop portals
- [ ] Fullscreen games and accelerated browser rendering

Fixture/syntax passes do not verify these hardware/session behaviors.

## Behemoth frozen-input troubleshooting

A Behemoth-only temporary override is available in
`hosts/behemoth-recovery.lua`. It is opt-in via a `dofile` in the local
`~/.config/firehawk/local.lua`; it is not enabled for other machines by setup.
It forces a software cursor as a diagnostic NVIDIA workaround, enables compositor
logs, opens a terminal at startup, and runs `scripts/session-diagnostics`.
The workaround is **not a confirmed fix** for the reported frozen pointer.

The existing system-wide keyd configuration intercepts the physical keyboards;
the Apple-specific Hyprland remap may not match its virtual keyboard. This does
not establish the cause of mouse freezing. Do not remap the generic keyd keyboard
blindly: that would also change Glove80 input. No keyd or i3 settings were changed.

Recovery bindings: **Ctrl+Alt+Enter** opens Ghostty; **Ctrl+Alt+Backspace** exits
Hyprland immediately (unsaved application work can be lost). The input backend
must still be functioning for these to work. If it is frozen, try Ctrl+Alt+F3 to
switch to a TTY; log in and inspect `hyprctl instances` before terminating only
the failed compositor. Do not stop LightDM or the entire user session blindly.

Logs/snapshots go to `~/.local/state/ember/diagnostics/session-*`, outside `/run`,
so a reboot does not remove them. Snapshot commands are time-limited; no key-event
recorder is run. The capture depends on the compositor reaching its startup hook;
absence of capture is evidence it may have failed earlier. Syntax validation does
not prove that actual input works. Remove the local override's `dofile` line to
disable this temporary troubleshooting mode.

## Recovery

Choose **i3** at the login screen. Existing i3 config and packages were not removed.
To unlink only Firehawk's three managed desktop links:

```sh
firehawk-theme deactivate
```

It removes only symlinks pointing to Firehawk current, never unrelated configs,
backups or generations. Restore any original configs from
`~/.local/state/dotfiles/backups/<run>/` after checking paths.
The command link and shared shell/Ghostty links are left in place.

To select an older theme, inspect `~/.local/state/firehawk/generations/` and
repoint only the `~/.config/firehawk/current` symlink to that generation's `config`
directory while logged into i3. No running processes are reloaded automatically.

## Verification

```sh
bash tests/run.sh
python3 -B firehawk/test_theme.py
python3 -B firehawk/test_recent_files.py
luac -p firehawk/templates/hypr/hyprland.lua
bash -n setup.sh lib/setup.sh lib/firehawk.sh firehawk/install-packages.sh firehawk/templates/scripts/screenshot
```

The theme/deployment suite requires Python >=3.11, Pillow, fontconfig/fonts and Git.
Tests use allowlisted fixture copies and disposable homes, including paths with
spaces. Package transactions are stubbed, never actually performed. Arch CI runs
both suites, with Lua/shell checks. CI configuration is not a claim of a remote CI pass.

The Ember theme identity is saved in `~/notes/ember-theme.md`.
Historical business notes and the original unused logo are retained separately;
review business assets before publishing the repository.
Nothing is automatically staged, committed, pushed or installed.
