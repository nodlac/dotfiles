# Optional legacy cloudflared/sql helpers. Review before sourcing from local.zsh.
# No helpers run merely by sourcing this file. Existing tunnel tools stay unmanaged.
cloudflared-start() {
    local token_file="$HOME/.config/cloudflared/tunnel-token"
    local temp_file="${token_file}.tmp.$$"
    local token

    if ! docker info >/dev/null 2>&1; then
        echo "Docker is not available or the daemon is not running."
        return 1
    fi

    mkdir -p "${token_file:h}" || return 1
    chmod 700 "${token_file:h}" || return 1

    printf 'Enter Cloudflare Tunnel token: '
    read -r -s token || return 1
    printf '\n'
    if [[ -z "$token" ]]; then
        echo "Token cannot be empty."
        return 1
    fi

    (umask 077; printf '%s' "$token" > "$temp_file") || return 1
    unset token
    mv "$temp_file" "$token_file" || return 1
    chmod 600 "$token_file" || return 1

    docker rm -f cloudflared >/dev/null 2>&1 || true
    docker run -d \\
        --name cloudflared \\
        --restart unless-stopped \\
        --mount "type=bind,src=$token_file,dst=/run/secrets/tunnel-token,readonly" \\
        cloudflare/cloudflared:latest \\
        tunnel --no-autoupdate run --token-file /run/secrets/tunnel-token
}

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
