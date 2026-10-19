# Dedupe PATH on every shell — works for both `path` array and PATH string.
typeset -U path PATH

export PATH="$HOME/tools:$HOME/.opencode/bin:/usr/local/bin:$PATH"
[[ -d $HOME/bin ]] && export PATH="$HOME/bin:$PATH"
[[ -d $HOME/.local/share/pi-node/current/bin ]] && export PATH="$HOME/.local/share/pi-node/current/bin:$PATH"
export EDITOR="nvim"
export VISUAL="nvim"
