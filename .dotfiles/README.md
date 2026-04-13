# Dotfiles

This is a bare git repository with worktree set to home directory.

## Fresh Install Steps

1. Clone the repository as a bare repo with worktree:
```bash
git clone --bare git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
git config --global status.showUntrackedFiles no
git config --global pull.rebase true
	.ssh/
```

2. Run the setup script (automatically creates symlinks):
```bash
~/.dotfiles/.endevouros-setup.sh
```

3. Restart shell or log out/in

4. (Optional) Add alias to ~/.zshrc:
```bash
alias eos-setup='~/.dotfiles/.endevouros-setup.sh'
```

## Updating Dotfiles

After making changes, commit with:
```bash
df add -u
df commit -m "description"
df push
```

Or use the shorthand alias:
```bash
df-quick-commit
```
