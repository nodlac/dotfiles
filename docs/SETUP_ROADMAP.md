# Portable setup: decisions and remaining work

## Direction

One conventional checkout and one `setup.sh` entry point. Shared personal/work
helpers belong on every device; OS detection chooses platform behavior. Hostname
presets are optional compatibility overrides, not a requirement for a fresh install.
Use the generic machine default and choose headless/desktop capabilities explicitly.

## Implemented

- Shared shell sources the repository's `.zsh/.nodlac.zsh` and `.zsh/.vidangel.zsh`.
  They matched Behemoth's home copies when migrated. Missing work checkouts,
  agent-tools, Java, Android tools and NVIDIA tools no longer break shell startup.
  Linux uses native Docker rather than Colima; macOS retains Colima. Its resource
  allocation can be overridden with VA_COLIMA_CPUS / VA_COLIMA_MEMORY.
- No `~/.config/dotfiles/local.zsh` existed on Behemoth at this audit. The local
  override remains available for genuinely local settings, not shared defaults.
- Setup offers SQL/Cloudflare functions on an interactive terminal, or explicitly
  with `--enable-helpers`. Noninteractive setup never waits for an answer;
  `--skip-helpers` suppresses the prompt without disabling an existing selection.
  Setup does not run these helpers, start containers, or fetch credentials.
- npm configuration and the browser bookmark export link to portable assets.
  Behemoth's obsolete `.setup.conf` and `.mac-setup.sh` links were removed.
- Package/plugin installation remains explicit. `--configure-system` adds native
  Linux Docker service activation (plus NetworkManager/Bluetooth for desktop),
  or macOS keyboard repeat and hotkey defaults. Preview with `--dry-run` first.
  These are real system changes and are never applied by default or `dtf pull`.
- Tmux todo header and toggle bindings are intentionally skipped.

## Follow-ups

- [ ] **Infisical -> `~/.env` (not today):** choose project/environment and login
  flow, define a secure export/refresh mechanism, permissions and offline/failure
  behavior, then explicitly integrate shell loading. Never commit credentials or
  silently fetch secrets during shell startup. CLI installation already exists;
  installing the CLI is not secret integration.
- [ ] **Pull the MacBook's latest setup before claiming parity.** The copies on
  Behemoth are not evidence of the MacBook's current state. Compare its current
  checkout, profiles, local overrides, package inventories, keyboard settings,
  Karabiner and work tooling with this repository; migrate approved differences.
- [ ] Complete provisioning parity: review Homebrew/AUR bootstrap, AUR packages,
  user-owned npm/Python tool installation, OpenCode, agent-tools and tools/install
  integration, login-shell selection, Linux keyd/editor alternatives, macOS
  Karabiner activation/permissions and optional browser installs. Port reviewed,
  idempotent tasks with previews and explicit consent; do not run whole legacy
  installers, use `pip --break-system-packages`, or overwrite existing configs.
- [ ] Right-size backend container/Postgres tuning for device capacity. Colima
  no longer assumes a 32 GB Mac, but the inherited database tuning still does.
- [ ] Validate on real macOS (Intel/Apple Silicon), Ubuntu and fresh Arch installs.
  Fixture tests do not establish live system provisioning or hardware parity.
- [ ] **Revisit remaining legacy cleanup after the weekend, not before.** Keep
  `~/.dotfiles` and remaining legacy files intact for now to avoid weekend
  disruption. Before retirement, validate the portable setup in fresh shells
  and normal work sessions, verify remaining references, and preserve any needed
  Git metadata/local configuration. Obtain approval before deleting anything;
  do not delete home files merely because the old repository used to track them.
