# Public server helpers only. No credential loading or service mutation.
export DOTFILES_MACHINE=callisto
PS1='%F{blue}Callisto:%f %F{blue}%~%f $ '
serve() { python3 -m http.server "${1:-8000}"; }
jlog() { journalctl -fu "$1"; }
sysupdate() { sudo apt-get update && sudo apt-get upgrade; }
alias tm='tmux attach-session'
