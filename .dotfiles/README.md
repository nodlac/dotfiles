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

Uses the `server` branch: no desktop files (aerospace/ghostty/i3/karabiner),
apt packages instead of pacman/AUR, and `MACHINE_ENV=server` in `~/.env`.

```bash
git clone --bare --branch server git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
git config status.showUntrackedFiles no
git checkout
~/.dotfiles/.server-setup.sh
```

The setup script: creates symlinks, installs apt packages (neovim from GitHub
releases if the apt build is too old), zsh plugins, tmux plugins, pip globals,
sets `MACHINE_ENV=server` in `~/.env`, and makes zsh the default shell.

Stay on the `server` branch — `df checkout main` would drop desktop configs
into `$HOME`.

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