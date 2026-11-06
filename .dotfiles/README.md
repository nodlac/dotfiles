# Dotfiles

Git repo with `~/.dotfiles` as the git-dir and `$HOME` as the worktree.

## How It Works

The repo tracks two kinds of files:

| Location | Examples | How they get to `$HOME` |
|----------|----------|------------------------|
| `~/.dotfiles/.*` | `.zshrc`, `.tmux.conf`, `.zshenv`, `.npmrc` | **Symlinked** by the setup script |
| Directly in `$HOME` | `.config/nvim/*`, `.config/ghostty/*`, `.aerospace.toml`, `tools/*`, `.zsh/*` | **Checked out** by git |

The `df` alias (`git --git-dir=$HOME/.dotfiles/ --work-tree=$HOME`) is used for all git operations.

## Fresh Install — EndeavourOS

```bash
git clone --bare git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
git config status.showUntrackedFiles no
git checkout
~/.dotfiles/.eos-setup.sh
```

The setup script: creates symlinks, installs pacman/AUR packages, zsh plugins, tmux plugins, npm/pip globals, and enables services.

## Fresh Install — macOS

```bash
git clone --bare git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
git config status.showUntrackedFiles no
git checkout
~/.dotfiles/.mac-setup.sh
```

The setup script: creates symlinks, installs Homebrew formulae/casks, zsh plugins, tmux plugins, npm/pip globals, and sets macOS defaults.

## Fresh Install — Ubuntu Server (headless)

Uses the `server` branch: desktop configs remain tracked for safe merging,
but the server installer does not install or activate the desktop stack. It
uses apt packages instead of pacman/AUR and sets `MACHINE_ENV=server` in `~/.env`.

```bash
git clone --bare --branch server git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
git config status.showUntrackedFiles no
git checkout
~/.dotfiles/.server-setup.sh
```

The setup script: creates symlinks, installs apt packages, builds tmux 3.5a
from source when the installed version is older, installs neovim from GitHub
releases if the apt build is too old, sets up zsh/tmux plugins, installs pip
globals, sets `MACHINE_ENV=server` in `~/.env`, and makes zsh the default shell.
The tmux config remains compatible with Ubuntu's tmux 3.4 as a fallback.

At the end, the installer offers an optional hosting add-on at
`tools/server-hosting-setup.sh`. It installs Docker Compose and Caddy, creates
an owner-only Infisical environment file only if one does not already exist,
and starts Infisical bound to `127.0.0.1:8080` with pinned image versions and
PostgreSQL 18. It requires a successful local API health check before proceeding.
UFW setup and SSH hardening require separate confirmations. Run
`tools/infisical-first-admin.sh` to prepare private first-user signup through an
SSH tunnel; public Caddy/HTTPS publishing is a separate confirmed step:

```bash
~/tools/server-hosting-setup.sh --publish
```

Before publishing, create the first admin account and ensure the domain's A
record and router TCP 80/443 forwards point to this server. The add-on preserves
existing Compose and secret files rather than overwriting them.

The server branch retains the desktop configs, so it can be merged into
`main` without deleting aerospace, Ghostty, i3, or Karabiner files. The
server-specific package list lives in `.dotfiles/.server-setup.conf` so it
does not replace the EndeavourOS `.setup.conf`.

## Updating Dotfiles

```bash
df add -u
df commit -m "description"
df push
```

Or use the shorthand:
```bash
df-quick-commit
```