# ~/.zshrc

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

# ===========================================
# PATH and Environment
# ===========================================
export PATH="$HOME/.local/bin:$PATH"
export PATH="$PATH:$(go env GOPATH)/bin"
export PATH="$HOME/.opencode/bin:$PATH"
export EDITOR=vim
export VISUAL=vim

# ===========================================
# Aliases
# ===========================================
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias df='git --git-dir=$HOME/.dotfiles/ --work-tree=$HOME'

# ===========================================
# Prompt
# ===========================================
PS1='%F{blue}%~%f $ '

# ===========================================
# Plugins
# ===========================================
source ~/.zsh/zsh-history-substring-search/zsh-history-substring-search.zsh

# ===========================================
# Vi Mode with Cursor Switching
# ===========================================
bindkey -v

# Cursor: beam in insert, block in command
zle-keymap-select() {
  if [[ $KEYMAP = vicmd ]]; then
    print -n -- '\e[2 q'
  else
    print -n -- '\e[6 q'
  fi
}
zle -N zle-keymap-select

# Initial cursor (beam for insert mode)
print -n -- '\e[6 q'

# Test functions - run these to check cursor
cursor-beam() { print -n -- '\e[6 q'; }
cursor-block() { print -n -- '\e[2 q'; }

# Fix backspace in vi mode
bindkey '^?' backward-delete-char

# ===========================================
# Arrow Key History Search (from inputrc)
# ===========================================
# Arrow keys
bindkey "^[[A" history-substring-search-up
bindkey "^[[B" history-substring-search-down

# vi command mode
bindkey -M vicmd 'k' history-substring-search-up
bindkey -M vicmd 'j' history-substring-search-down

# ===========================================
# History
# ===========================================
HISTSIZE=10000
SAVEHIST=10000
HISTFILE=~/.zsh_history

# ===========================================
# Completion
# ===========================================
autoload -Uz compinit
compinit

# Menu selection
zstyle ':completion:*' menu select

# Case insensitive completion
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

# Color completion
zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"

# Group completions
zstyle ':completion:*' group-name ''
zstyle ':completion:*:descriptions' format '%B%d%b'



# ===========================================
# Work Specific Aliases
# ===========================================
# Load work aliases if on work machine
if [[ "$MACHINE_ENV" == "work" ]]; then
  source ~/.zsh/aliases-work.zsh
fi   
