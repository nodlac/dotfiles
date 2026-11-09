# Platform setup and verification

These are fresh-clone commands. On existing machines follow MIGRATION.md first.
Always review the preview, then remove `--dry-run` to apply it. Append
`--install-packages` / `--install-plugins` only when you want network/install
operations; neither is implied by machine selection. No command changes login
shell, OS defaults, firewall, Docker groups, SSH, credentials, or services.

## Behemoth — Arch/EndeavourOS workstation

```sh
./setup.sh --machine behemoth --profile desktop --dry-run
```

Links shared shell/tmux, Ghostty and i3. Desktop packages are separate from CLI
packages. AUR packages (`brave-bin`, `keyd`) and any AUR helper are intentionally
not automatically installed; use your approved AUR workflow. Keyd remapping,
Docker/NetworkManager/Bluetooth service activation and editor alternatives are
separate manual tasks; the [feature inventory](FEATURE_PARITY.md) points to
historical recipes in Git history.

## Callisto — native Ubuntu Server, headless

```sh
./setup.sh --machine callisto --profile headless --dry-run
```

Rejects WSL and the desktop profile. Ubuntu packages include CLI dependencies only.
Distro `fdfind`/`batcat` names are handled by shell aliases, not forced binary links.
Source-building newer tmux/neovim and hosting deployment are not implicit. Test
packaged tmux first (config retains the 3.4 compatibility fallback); use a verified
Neovim >= 0.10 distribution before opting into `--link-nvim`. See the Callisto
preservation checklist in MIGRATION.md before touching its existing worktree.

## Somnambulist — Ubuntu on WSL2

```sh
./setup.sh --machine somnambulist --profile headless --dry-run
```

Requires detected WSL2, not WSL1 or native Ubuntu. No Linux GUI tools, systemd
assumptions, Windows PATH changes, system services, or Windows-side configuration
are applied. Configure Windows Terminal, keyboard/clipboard integration and
WSL-specific service needs separately after verification. Detection fixtures do
not replace a real WSL2 smoke test.

## macOS — Apple Silicon or Intel

```sh
./setup.sh --machine macos --profile desktop --dry-run
```

Uses BSD-compatible `ls -G`, discovers Homebrew under `/opt/homebrew` or
`/usr/local`, and uses Bash 3.2-compatible setup code. Install Homebrew using its
vendor instructions before opting into package installation. Desktop selection
links Ghostty, Aerospace and the Karabiner rule asset, **not** the live
`karabiner.json`. Approve driver/Input Monitoring permissions and enable the rule
manually. Key repeat, caps-to-Escape, Spotlight and hotkey defaults are documented
in the feature inventory, with historical recipes in Git history; they are never
silently changed. Neither `chsh` nor an Intel/ARM shell path is hardcoded by
bootstrap.

## Medina Station — verified macOS (Apple Silicon) desktop

Verified on the machine itself on 2026-11-09: macOS 26.6.2 arm64, zsh 5.9,
system Bash 3.2.57, Homebrew tmux 3.6a. Activation command:

```sh
./setup.sh --machine medina-station --profile desktop --confirm-work-os macos --dry-run
```

The machine profile is deliberately empty except for its public identity; the
explicit `--confirm-work-os` + `--profile` requirement stays so a different OS
or role is never assumed. Credential loading (`~/.env`), the work shell profile,
`~/tools` on PATH and the tmux todo header live in the user-owned
`~/.config/dotfiles/local.zsh` / `tmux.local.conf`, outside the repository.

Desktop setup is currently implemented for macOS and native Arch/EndeavourOS only; Ubuntu desktop
and WSL desktop are rejected. Put approved work overrides in the user-owned
`~/.config/dotfiles/local.zsh` / `tmux.local.conf`. Old private profiles and the
todo/notes feature are not automatically sourced or inspected.

## Generic and unknown Linux distributions

`./setup.sh` links shared configuration with the headless profile. Unknown Linux
distributions can use config-only setup; unsupported package managers fail before
links change. Unsupported kernels fail detection. Install prerequisites manually
and validate locally before adding a platform recipe.

## Actual deployment status

**Medina Station was migrated and smoke-tested on 2026-11-09**: the full suite
(54 tests) passed locally on macOS/Bash 3.2, the old configs were moved intact
into `~/.local/state/dotfiles/backups/`, and a fresh zsh plus an isolated tmux
server (`tmux -L migration-check`) were verified — native `df` intact, `dtf` on
the new checkout, work helpers loading from `local.zsh`. The old `~/.dotfiles`
Git directory, branches and the live tmux server were left untouched.
This verification was recorded before the repository cleanup, not a rerun of the
post-cleanup suite on Medina Station.

- **Behemoth:** its canonical shell/tmux and Ghostty/i3 links were verified locally
  after the owner applied setup. Desktop input/app behavior and service workflows
  have not been independently verified.
- **Callisto:** the owner reported passing isolated tests with its bundled tmux
  binary/runtime, then confirmed the canonical shell link, checkout-scoped `dtf`,
  native `df` and working tmux 3.5a. Backups and server workflows remain unverified.
- **Personal MacBook and Somnambulist/WSL2:** no machine-validation output has been
  provided. Their actual deployments remain pending.

Automated tests run on Behemoth in disposable homes, plus Ubuntu/macOS CI runners
and an Arch Linux container. CI checks are separate from the recorded Medina
Station deployment, and detection fixtures are not a real WSL2 deployment.
Inspect current PR checks; package availability, GUI/input integration and
services need separate owner-approved machine smoke tests.
