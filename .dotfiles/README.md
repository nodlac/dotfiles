# Dotfiles

This is a bare git repository with worktree set to home directory.

## Fresh Install Steps

1. Clone the repository:
```bash
git clone --bare git@github.com:nodlac/dotfiles.git ~/.dotfiles
```

2. Configure git to use home directory as worktree:
```bash
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
```

3. Run the setup script (creates symlinks):
```bash
~/.dotfiles/.endevouros-setup.sh
```

4. Restart shell or log out/in

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