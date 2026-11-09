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
separate manual tasks retained in the legacy recipes.

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
manually. Key repeat, caps-to-Escape, Spotlight and hotkey defaults are retained
as reference recipes, never silently changed. Neither `chsh` nor an Intel/ARM
shell path is hardcoded by bootstrap.

## Medina Station — OS and requirements not yet verified

Do not guess. Confirm these with the owner/IT before activation:

- Actual OS/distribution and WSL status (`./setup.sh --detect`).
- Whether it is managed by MDM or another configuration system.
- Approved shell, package sources, desktop apps, work tools and credential-loading
  policy. No personal machine settings or private notes should be imported.
- Existing shell/tmux customizations that must remain available.

The machine profile is deliberately empty except for its public identity.
Activation requires an explicit role and OS confirmation matching detection, e.g.
**only after confirming a Linux/headless requirement**:

```sh
./setup.sh --machine medina-station --profile headless --confirm-work-os linux --dry-run
```

Use `macos` instead of `linux` only if that is the verified OS. Desktop setup is
currently implemented for macOS and native Arch/EndeavourOS only; Ubuntu desktop
and WSL desktop are rejected. Put approved work overrides in the user-owned
`~/.config/dotfiles/local.zsh` / `tmux.local.conf`. Old private profiles and the
todo/notes feature are not automatically sourced or inspected.

## Generic and unknown Linux distributions

`./setup.sh` links shared configuration with the headless profile. Unknown Linux
distributions can use config-only setup; unsupported package managers fail before
links change. Unsupported kernels fail detection. Install prerequisites manually
and validate locally before adding a platform recipe.

## Actual deployment status

No target machine was migrated by this change. Local automated tests ran on the
Behemoth Linux host in disposable homes; detection fixtures simulate other
platforms. GitHub CI results must be checked on the PR. macOS CI is a runner test,
not verification of either user's Mac or Medina Station. Callisto, real WSL2,
keyboard integration, GUI apps, package availability and service behavior require
owner-approved machine-by-machine smoke tests after review.
