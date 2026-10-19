#!/usr/bin/env bash
# Syntax + regression checks for every tracked dotfile.
#
#   df-test          run everything
#   df commit        runs this first (tools/git-hooks/pre-commit)
#   df commit -n     bypass
#
# ponytail: checks the WORKING TREE, not the index — a partial `df add -p` can
# commit content these never saw. Switch to a temp checkout of the index if that
# ever actually bites.

set -uo pipefail

DOTFILES="$HOME/.dotfiles"
# Hooks export these; they confuse ls-files and py_compile's cwd handling.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
dgit() { git --git-dir="$DOTFILES" --work-tree="$HOME" "$@"; }

pass=0 skip=0
fails=()
red=$'\033[31m' grn=$'\033[32m' dim=$'\033[2m' off=$'\033[0m'
[ -t 1 ] || { red="" grn="" dim="" off=""; }

ok()   { pass=$((pass+1)); }
bad()  { fails+=("$1"$'\n'"$(printf '%s' "${2:-}" | sed 's/^/    /')"); }
note() { skip=$((skip+1)); printf '%s- skip %s%s\n' "$dim" "$1" "$off"; }
# Run a validator; on failure record its combined output under $1.
try()  { local what="$1"; shift; local out; if out=$("$@" 2>&1); then ok; else bad "$what" "$out"; fi; }
# Regression guard: $3 is a grep -E pattern, $4 inverts the match.
want() { local what="$1" file="$2" re="$3" invert="${4:-}"
  [ -f "$HOME/$file" ] || { bad "$what" "missing file: $file"; return; }
  if grep -Eq "$re" "$HOME/$file"; then [ -n "$invert" ] && bad "$what" "$file still matches /$re/" || ok
  else [ -n "$invert" ] && ok || bad "$what" "$file has no /$re/"; fi; }

say() { printf '\n%s%s%s\n' "$dim" "$1" "$off"; }

# ── Syntax ────────────────────────────────────────────────────────────────
say "syntax"
LUAC=""
for c in luajit luac; do command -v $c >/dev/null && { LUAC=$c; break; }; done

while IFS= read -r f; do
  p="$HOME/$f"
  [ -f "$p" ] || continue
  case "$(head -c 200 "$p" | head -1)$f" in
    *zsh*)      try "zsh -n $f"  zsh -n "$p" ;;
    *bash*|*sh) try "bash -n $f" bash -n "$p" ;;
    *python*)   try "py $f"      python3 -m py_compile "$p" ;;
    *)
      case "$f" in
        *.py)   try "py $f"   python3 -m py_compile "$p" ;;
        *.lua)  [ -n "$LUAC" ] && try "lua $f" $LUAC -bl "$p" /dev/null || note "lua $f (no luajit/luac)" ;;
        *.json) try "json $f" python3 -m json.tool "$p" /dev/null ;;
        *.toml) try "toml $f" python3 -c 'import tomllib,sys; tomllib.load(open(sys.argv[1],"rb"))' "$p" ;;
      esac ;;
  esac
done < <(dgit ls-files)

# ── Each tool parses its own config ───────────────────────────────────────
say "configs load"
GHOSTTY=$(command -v ghostty || echo /Applications/Ghostty.app/Contents/MacOS/ghostty)
[ -x "$GHOSTTY" ] && try "ghostty validate-config" "$GHOSTTY" +validate-config || note "ghostty (not installed)"
command -v aerospace >/dev/null && try "aerospace reload-config" aerospace reload-config --dry-run --no-gui || note "aerospace (not installed)"
command -v tmux      >/dev/null && try "tmux.conf" tmux -L dotfiles-test -f "$DOTFILES/.tmux.conf" start-server \; kill-server || note "tmux (not installed)"
command -v i3        >/dev/null && try "i3 config" i3 -C -c "$HOME/.config/i3/config" || note "i3 (not installed)"

# ── Regressions we have actually hit ──────────────────────────────────────
say "regressions"
# Grabbing alt-arrow at WM level starves the terminal's word jump. See 7aa5cff.
want "aerospace leaves alt-left/right free" .aerospace.toml '^\s*alt-(left|right)\s*=' invert
want "zsh word jump on ctrl+arrow"          .dotfiles/.zshrc '^bindkey "\^\[\[1;5[CD]"'
want "ghostty pastes on ctrl+v"             .config/ghostty/config.ghostty '^keybind = ctrl\+v=paste_from_clipboard'
want "ghostty pastes on ctrl+shift+v"       .config/ghostty/config.ghostty '^keybind = ctrl\+shift\+v=paste_from_clipboard'
want "ghostty copies on ctrl+shift+c"       .config/ghostty/config.ghostty '^keybind = ctrl\+shift\+c=copy_to_clipboard'
# Swapping ctrl/cmd inside a terminal would eat SIGINT and the tmux prefix.
want "karabiner swap excludes ghostty"      .config/karabiner/assets/complex_modifications/linux-ctrl-swap.json 'mitchellh\\\\.ghostty'
want "caps lock is escape (mac)"            .dotfiles/.mac-setup.sh '"key_code": "caps_lock"'
want "caps lock is escape (linux)"          .dotfiles/.eos-setup.sh '^capslock = esc'
# keyd puts Mod4 on the physical Option key so alt- binds match aerospace.
want "option is meta (linux)"               .dotfiles/.eos-setup.sh '^left-option = left-meta'
# $DOTFILES_DIR is the bare git dir — tools/ lives in $USER_HOME. See e5e32de.
want "mac-setup finds tools/install.sh"     .dotfiles/.mac-setup.sh '\$USER_HOME/tools/install\.sh'
want "eos-setup finds tools/install.sh"     .dotfiles/.eos-setup.sh '\$USER_HOME/tools/install\.sh'
want "server-setup finds server package list" .dotfiles/.server-setup.sh '\.server-setup\.conf'
want "server-setup finds tools/install.sh"  .dotfiles/.server-setup.sh '\$USER_HOME/tools/install\.sh'
want "setup hooks up df-test"               .dotfiles/.mac-setup.sh 'core\.hooksPath'
want "eos-setup hooks up df-test"           .dotfiles/.eos-setup.sh 'core\.hooksPath'
want "server-setup hooks up df-test"        .dotfiles/.server-setup.sh 'core\.hooksPath'

for s in .dotfiles/.mac-setup.sh .dotfiles/.eos-setup.sh .dotfiles/.server-setup.sh tools/ensure-tunnel; do
  [ -x "$HOME/$s" ] && ok || bad "$s is executable" "chmod +x ~/$s"
done

# ── Nothing tracked may hold a secret ─────────────────────────────────────
say "secrets"
if leak=$(grep -nE '^export [A-Z_]*(TOKEN|PASS|SECRET|KEY)[A-Z_]*=.+' "$HOME/.env.template"); then
  bad ".env.template has no values" "$leak"
else ok; fi
# Anything that looks like a live credential, in any tracked file.
if leak=$(dgit grep -nIE '(sk-ant-[A-Za-z0-9_-]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10}|AKIA[0-9A-Z]{16})' -- . 2>/dev/null); then
  bad "no credentials in tracked files" "$leak"
else ok; fi

# ── Report ────────────────────────────────────────────────────────────────
printf '\n'
if [ ${#fails[@]} -eq 0 ]; then
  printf '%sok%s  %d passed, %d skipped\n' "$grn" "$off" "$pass" "$skip"
  exit 0
fi
for f in "${fails[@]}"; do printf '%sFAIL%s %s\n' "$red" "$off" "$f"; done
printf '\n%s%d failed%s, %d passed, %d skipped   %s(bypass: df commit -n)%s\n' \
  "$red" "${#fails[@]}" "$off" "$pass" "$skip" "$dim" "$off"
exit 1
