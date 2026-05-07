# Dedupe PATH on every shell — works for both `path` array and PATH string.
typeset -U path PATH

export PATH="$HOME/tools:$HOME/.opencode/bin:/usr/local/bin:$PATH"
export EDITOR="nvim"
export VISUAL="nvim"
