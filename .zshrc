# ~/.zshrc

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

# ===========================================
# PATH and Environment
# ===========================================
export PATH="$HOME/.local/bin:$PATH"
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"
export PATH="$PATH:$(go env GOPATH)/bin"
export PATH="$HOME/.opencode/bin:$PATH"

# Loads Environment variables
[ -f ~/.env ] && source ~/.env

# ===========================================
# Exports
# ===========================================
export EDITOR=vim
export VISUAL=vim
export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - zsh)"

# ===========================================
# Aliases
# ===========================================
alias python='python3'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias df='git --git-dir=$HOME/.dotfiles/ --work-tree=$HOME'
alias df-quick-commit='df add -u && df status && df commit -m "quick commit" && df push'
alias git diff="git diff --color-words"
alias tmux-start='tmux new-session -A -s notes'


# ===========================================
# Functions
# ===========================================

# Run a .sql file and save results as CSV to ~/Downloads
# Usage: sqlrun <db> <file.sql>
#   db: bim, finn, bim_stag, finn_stag
sqlrun() {
    local db="$1" file="$2"
    if [[ -z "$db" || -z "$file" ]]; then
        echo "Usage: sqlrun <db> <file.sql>"
        echo "  db: bim, finn, bim_stag, finn_stag"
        return 1
    fi
    if [[ ! -f "$file" ]]; then
        echo "File not found: $file"
        return 1
    fi

    local url
    case "$db" in
        bim)       url="$BIM_URL" ;;
        finn)      url="$FINN_URL" ;;
        bim_stag)  url="$BIM_STAGING_URL" ;;
        finn_stag) url="$FINN_STAGING_URL" ;;
        *) echo "Unknown db: $db (use bim, finn, bim_stag, finn_stag)"; return 1 ;;
    esac
    if [[ -z "$url" ]]; then
        echo "DB URL not set for $db"
        return 1
    fi

    # Ensure tunnel is open before running query
    ~/tools/ensure-tunnel "$db" || return 1

    local name="${file:t:r}"  # filename without path or extension
    local date="$(date +%Y-%m-%d)"
    local out="$HOME/Downloads/${name}_${date}.csv"

    echo "Running $file against $db → $out"
    psql "$url" --csv -f "$file" -o "$out" && echo "Saved: $out"
}

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

# Ctrl+Backspace (via Ghostty escape sequence)
bindkey '\e[ctrlbackspace' backward-kill-line

# Ctrl+h = backward-kill-line
bindkey '^H' backward-kill-line

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
  source ~/.zsh/.vidangel.zsh
fi
