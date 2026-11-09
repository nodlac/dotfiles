alias ls='ls --color=auto'
alias grep='grep --color=auto'
# Ubuntu ships fd and bat under different binary names.
if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then alias fd=fdfind; fi
if ! command -v bat >/dev/null 2>&1 && command -v batcat >/dev/null 2>&1; then alias bat=batcat; fi
return 0
