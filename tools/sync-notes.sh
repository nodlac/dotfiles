#!/bin/zsh
#
notify() {
    /opt/homebrew/bin/terminal-notifier -title "$1" -message "$2" -sound Basso
}

cd ~/notes/ || { notify "Notes Sync" "Failed: ~/notes/ not found"; exit 1; }

# Stash any local changes
git stash

# Pull remote changes
if ! git pull; then
    notify "Notes Sync" "Failed: git pull error"
    exit 1
fi

# Restore local changes
git stash pop 2>/dev/null

# Only commit if there are changes
if [[ -n $(git status --porcelain) ]]; then
    git add .
    if ! git commit -m "sync notes"; then
        notify "Notes Sync" "Failed: git commit error"
        exit 1
    fi
    if ! git push; then
        notify "Notes Sync" "Failed: git push error"
        exit 1
    fi
fi
