# Dotfiles

This is a bare git repository with worktree set to home directory.

## Fresh Install Steps

1. Clone the repository as a bare repo with worktree:
```bash
git clone --bare git@github.com:nodlac/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
git config core.bare false
git config core.worktree ~
```

2. Set up symlinks for config files:
```bash
# Symlink dotfiles to home directory
for f in ~/.dotfiles/.*; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    [ "$base" = "." ] && continue
    [ "$base" = ".." ] && continue
    [ "$base" = ".git" ] && continue
    [ "$base" = ".dotfiles" ] && continue
    ln -sf "$f" ~/"$base"
done

# Symlink .config files
for d in ~/.dotfiles/.config/*; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    mkdir -p ~/.config/"$base"
    ln -sf "$d" ~/.config/"$base"
done
```

3. Run the setup script:
```bash
~/.dotfiles/.endevouros-setup.sh
```

4. Add alias to ~/.zshrc:
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