# Support both Apple Silicon and Intel Homebrew.
if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi
for prefix in /opt/homebrew /usr/local; do
    [[ ! -d "$prefix/opt/libpq/bin" ]] || path=("$prefix/opt/libpq/bin" $path)
done
unset prefix
alias ls='ls -G'
alias grep='grep --color=auto'
return 0
