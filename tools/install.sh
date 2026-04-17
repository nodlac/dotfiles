#!/usr/bin/env zsh
# install.sh — set up dotfiles-managed tools on a new machine
# (agent-tools is installed separately — see ~/.mac-setup.sh / ~/.eos-setup.sh)
set -e

SCRIPTS_DIR="${0:A:h}"
LOCAL_BIN="$HOME/.local/bin"
ZSHRC="$HOME/.zshrc"

green() { print -P "%F{green}$*%f"; }
yellow() { print -P "%F{yellow}$*%f"; }
red() { print -P "%F{red}$*%f"; }
info() { print "  $*"; }

echo ""
green "==> dotfiles/tools install"
echo ""

# ── 1. Check dependencies ─────────────────────────────────────────────────────

echo "Checking dependencies..."
missing=()
command -v python3 &>/dev/null || missing+=(python3)
command -v git     &>/dev/null || missing+=(git)

if (( ${#missing} )); then
    red "Missing: ${missing[*]}"
    info "Install with: brew install ${missing[*]}"
    exit 1
fi
info "python3 $(python3 --version 2>&1 | awk '{print $2}')  git $(git --version | awk '{print $3}')"

# ── 2. ~/.local/bin ───────────────────────────────────────────────────────────

echo ""
echo "Setting up ~/.local/bin..."
mkdir -p "$LOCAL_BIN"

install_wrapper() {
    local name="$1"
    local target="$2"
    local dest="$LOCAL_BIN/$name"
    cat > "$dest" <<WRAPPER
#!/usr/bin/env zsh
source ~/.env 2>/dev/null
exec $target "\$@"
WRAPPER
    chmod +x "$dest"
    info "installed $name → $dest"
}

install_symlink() {
    local name="$1"
    local src="$2"
    local dest="$LOCAL_BIN/$name"
    ln -sf "$src" "$dest"
    chmod +x "$src"
    info "linked   $name → $src"
}

install_wrapper  sprint-sync    "python3 $SCRIPTS_DIR/sprint-sync.py"
install_symlink  clickup-open   "$SCRIPTS_DIR/clickup-open.sh"

# ── 3. Ensure ~/.local/bin is in PATH ─────────────────────────────────────────

echo ""
echo "Checking PATH..."
if ! grep -q 'HOME/.local/bin' "$ZSHRC" 2>/dev/null; then
    echo '\nexport PATH="$HOME/.local/bin:$PATH"' >> "$ZSHRC"
    info "added ~/.local/bin to PATH in $ZSHRC"
else
    info "~/.local/bin already in $ZSHRC"
fi

# ── 4. ~/.env template ────────────────────────────────────────────────────────

echo ""
echo "Checking ~/.env..."
ENV_FILE="$HOME/.env"
needs_token=false
if [[ ! -f "$ENV_FILE" ]]; then
    touch "$ENV_FILE"
    needs_token=true
fi

if ! grep -q "CLICKUP_TOKEN" "$ENV_FILE" 2>/dev/null; then
    echo '\n# ClickUp API (get from: ClickUp → Settings → Apps → API Token)' >> "$ENV_FILE"
    echo 'export CLICKUP_TOKEN=""' >> "$ENV_FILE"
    echo 'export CLICKUP_USER_ID=""' >> "$ENV_FILE"
    echo 'export CLICKUP_TEAM_ID="14252037"' >> "$ENV_FILE"
    needs_token=true
fi

if $needs_token; then
    yellow "  ~/.env created — fill in CLICKUP_TOKEN and CLICKUP_USER_ID"
else
    info "~/.env already has CLICKUP_TOKEN"
fi

# ── 5. Claude Code permissions ────────────────────────────────────────────────

echo ""
echo "Setting up Claude Code permissions..."
CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR"

SETTINGS_SRC="$SCRIPTS_DIR/claude-settings/settings.json"
SETTINGS_LOCAL_SRC="$SCRIPTS_DIR/claude-settings/settings.local.json"

CLAUDE_MD_SRC="$SCRIPTS_DIR/claude-settings/CLAUDE.md"
if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
    yellow "  ~/.claude/CLAUDE.md already exists — skipping (delete to override)"
else
    cp "$CLAUDE_MD_SRC" "$CLAUDE_DIR/CLAUDE.md"
    info "copied CLAUDE.md → ~/.claude/CLAUDE.md"
fi

if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
    yellow "  ~/.claude/settings.json already exists — skipping (delete to override)"
else
    cp "$SETTINGS_SRC" "$CLAUDE_DIR/settings.json"
    info "copied settings.json → ~/.claude/settings.json"
fi

if [[ -f "$CLAUDE_DIR/settings.local.json" ]]; then
    yellow "  ~/.claude/settings.local.json already exists — skipping (delete to override)"
else
    cp "$SETTINGS_LOCAL_SRC" "$CLAUDE_DIR/settings.local.json"
    info "copied settings.local.json → ~/.claude/settings.local.json"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
green "==> Done"
echo ""
echo "  Reload your shell:  source ~/.zshrc"
if $needs_token; then
    echo "  Then fill in:       ~/.env  (CLICKUP_TOKEN, CLICKUP_USER_ID)"
fi
echo ""
