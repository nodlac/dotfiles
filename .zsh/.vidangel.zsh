#
#########################################################
# Tardis Autocomplete
##########################################################
fpath=( ~/vidangel-repo/tiny-tardis/.completions/zsh $fpath )
autoload -U compinit; compinit

##########################################################
# Work Functions
##########################################################
connect-lepotato() {
     ssh -i ~/.ssh/lepotato -p 83 ubuntu@136.38.167.119
}

##########################################################
# Internal helpers (idempotent building blocks)
##########################################################
_va_ensure_colima() {
    if colima status &>/dev/null; then
        echo "  Colima already running"
    else
        echo "  Starting Colima..."
        colima start
    fi
}

# All groups except 'gpu' — that group pins Linux/Windows-only CUDA wheels
# (nvidia-*-cu12) with no macOS arm64 builds, so --all-groups alone fails here.
_VA_UV_SYNC=(uv sync --all-groups --no-group gpu)

# Sync + activate the backend checkout for the current shell (worktree-aware):
# resolve the checkout from $PWD, pull, install deps, activate the venv. uv sync
# creates .venv when absent, so a fresh worktree bootstraps here too.
_va_ensure_repo() {
    local root; root=$(_va_backend_root)
    cd "$root" || return 1
    git pull
    "${_VA_UV_SYNC[@]}" || return 1
    source .venv/bin/activate
}

# Render .env from the repo's tracked template (+ vault secrets) into CWD.
# Operates in the current dir so it works for both the main repo and worktrees;
# callers cd to the target checkout first.
_va_ensure_env() {
    if [[ ! -f .templates/dev.env.hbs ]]; then
        echo "  No .templates/dev.env.hbs in $PWD — cannot build .env."
        return 1
    fi
    vault-refresh-token
    w2 .templates/dev.env.hbs > .env
}

_va_ensure_container() {
    local name=$1; shift
    local image=$1; shift

    if docker ps --format '{{.Names}}' | grep -qx "$name"; then
        echo "  $name already running"
    elif docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        echo "  Starting existing $name..."
        docker start "$name"
    else
        echo "  Creating $name..."
        docker run --name="$name" -d --restart=always "$@" "$image"
    fi
}

_va_ensure_containers() {
    _va_ensure_container vidangel-postgres postgres:17 \
        -e POSTGRES_USER=root \
        -e POSTGRES_PASSWORD=dev \
        -e POSTGRES_DB=vidangel \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -v vidangel-postgres-data:/var/lib/postgresql/data \
        -p 5432:5432

    _va_ensure_container vidangel-redis redis:7.2.0-alpine \
        -p 6379:6379

    _va_ensure_container typesense typesense/typesense:29.0 \
        -p 8108:8108 \
        -v /opt/docker/typesense:/data \
        -e TYPESENSE_DATA_DIR=/data \
        -e TYPESENSE_API_KEY=testing000
}

_va_wait_for_postgres() {
    echo "  Waiting for Postgres..."
    local retries=10
    while ! psql -h localhost -p 5432 -U root -d postgres -c "SELECT 1" &>/dev/null; do
        ((retries--)) || { echo "  FAIL: Postgres did not become ready"; return 1; }
        sleep 1
    done
    echo "  Postgres ready"
}

_va_wait_for_redis() {
    echo "  Waiting for Redis..."
    local retries=10
    while ! docker exec vidangel-redis redis-cli ping &>/dev/null; do
        ((retries--)) || { echo "  FAIL: Redis did not become ready"; return 1; }
        sleep 1
    done
    echo "  Redis ready"
}

_va_wait_for_typesense() {
    echo "  Waiting for Typesense..."
    local retries=10
    while ! curl -sf http://localhost:8108/health -H 'X-TYPESENSE-API-KEY: testing000' &>/dev/null; do
        ((retries--)) || { echo "  FAIL: Typesense did not become ready"; return 1; }
        sleep 1
    done
    echo "  Typesense ready"
}

_va_ensure_db_data() {
    local row_count
    row_count=$(psql -h localhost -p 5432 -U root -d vidangel -tAc "SELECT count(*) FROM product_subscription" 2>/dev/null)

    if [[ -n "$row_count" && "$row_count" -gt 0 ]]; then
        echo "  Database has data ($row_count subscriptions)"
        return 0
    fi

    echo ""
    echo "  Database is empty or does not exist."

    # Check for cached dump first, then Downloads
    local cache_dir=~/.cache/vidangel
    if [[ -f "$cache_dir/dev.dump" ]]; then
        echo "  Found cached dump at $cache_dir/dev.dump"
        echo -n "  Restore from cache? [Y/n] "
        read -r answer
        if [[ ! "$answer" =~ ^[Nn] ]]; then
            vidangel-restore-dev-dump
            return $?
        fi
    elif [[ -f ~/Downloads/dev.dump ]]; then
        echo "  Found dump at ~/Downloads/dev.dump"
        echo -n "  Restore from Downloads? [Y/n] "
        read -r answer
        if [[ ! "$answer" =~ ^[Nn] ]]; then
            vidangel-restore-dev-dump
            return $?
        fi
    fi

    echo "  Skipping restore. Download dev.dump and run 'vidangel-restore-dev-dump' when ready."
    return 1
}

# Shared boot core: render this checkout's .env + bring up the shared infra
# (colima, containers, readiness waits). Idempotent — no-ops when already up, so
# a warm call is cheap, a cold one bootstraps. Callers cd to the target checkout
# (and activate the venv) first. Used by start-backend + switch-backend.
_va_boot() {
    _va_ensure_env         || return 1
    _va_ensure_colima      || return 1
    _va_ensure_containers  || return 1
    _va_wait_for_postgres  || return 1
    _va_wait_for_redis     || return 1
    _va_wait_for_typesense || return 1
}


vidangel-start-apple() {
    local dest device
    case "$1" in
      tv)     device="Apple TV 4K (3rd generation)"; dest="platform=tvOS Simulator,name=$device" ;;
      ipad)   device="iPad Pro 13-inch (M4)";        dest="platform=iOS Simulator,name=$device" ;;
      iphone) device="iPhone 16 Pro";                dest="platform=iOS Simulator,name=$device" ;;
      *) echo "usage: vidangel-start-apple tv|ipad|iphone"; return 1 ;;
    esac

    echo "=== vidangel-start-apple: $1 ==="
    echo "  device : $device"
    echo "  dest   : $dest"

    local proj=~/vidangel-repo/apple-clients/VidAngel/VidAngel.xcodeproj
    local scheme="VidAngel - Staging"
    local dd=/tmp/vidangel-dd
    echo "  proj   : $proj"
    echo "  scheme : $scheme"
    echo "  dd     : $dd"

    echo "[1/6] Resolving simulator UDID..."
    local udid=$(xcrun simctl list devices available | grep -F "$device (" | head -1 | grep -oE '[A-F0-9-]{36}')
    if [ -z "$udid" ]; then
        echo "  FAIL: sim not found for '$device'"
        return 1
    fi
    echo "  udid: $udid"

    echo "[2/6] Booting simulator..."
    if xcrun simctl bootstatus "$udid" -b >/dev/null 2>&1; then
        echo "  already booted"
    else
        xcrun simctl boot "$udid" || { echo "  FAIL: boot"; return 1; }
        echo "  booted"
    fi

    echo "[3/6] Opening Simulator.app..."
    open -a Simulator

    echo "[4/6] Building (xcodebuild)..."
    xcodebuild -project "$proj" -scheme "$scheme" -destination "$dest" \
      -derivedDataPath "$dd" -configuration Debug \
      -skipMacroValidation -skipPackagePluginValidation build
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "  FAIL: xcodebuild exited $rc"
        return $rc
    fi
    echo "  build OK"

    echo "[5/6] Locating .app bundle..."
    local app=$(find "$dd/Build/Products" -maxdepth 3 -name "*.app" | head -1)
    if [ -z "$app" ]; then
        echo "  FAIL: no .app under $dd/Build/Products"
        return 1
    fi
    echo "  app: $app"
    local bid=$(defaults read "$app/Info" CFBundleIdentifier)
    echo "  bundle id: $bid"

    echo "[6/6] Installing + launching..."
    xcrun simctl install "$udid" "$app" || { echo "  FAIL: install"; return 1; }
    xcrun simctl launch "$udid" "$bid" || { echo "  FAIL: launch"; return 1; }
    echo "  launched"
  }

##########################################################
# Public functions
##########################################################

# Zero to working in one command (worktree-aware: bootstraps THIS checkout).
vidangel-start-backend() {
    local root; root=$(_va_backend_root)
    echo "=== VidAngel Backend Setup -> $root ==="
    echo ""
    cd "$root" || return 1

    echo "[1/4] Infra & environment"
    _va_boot || return 1

    echo "[2/4] Database data"
    _va_ensure_db_data || return 1

    # Repo sync (git pull + uv sync + activate) happens inside reset-server via
    # _va_ensure_repo, so the venv this checkout needs is built here too.
    echo "[3/4] Repository, migrations & search index"
    vidangel-reset-server || return 1

    echo ""
    echo "[4/4] Dev server"
    vidangel-run-devserver
}

vidangel-reset-server() {
    _va_ensure_repo

    python3 manage.py makemigrations
    python3 manage.py migrate
    # Sets the base values for the popularity score in our index.
    python3 manage.py run_update_popularity
    # This destroys the current search index and rebuilds from scratch.
    #  It doesn't take too long and helps prevent out of sync issues with the index.
    python3 manage.py update_search
    # Update the Offerings View which will create a modified_at history
    #  in Redis for incremental search updates.
    python3 manage.py offerings_materialized_view -r
    python3 manage.py offerings_materialized_view -c
}

vidangel-restore-dev-dump() {
    local cache_dir=~/.cache/vidangel
    local DUMP_FILE=""

    # Prefer fresh download, fall back to cache
    if [[ -f ~/Downloads/dev.dump ]]; then
        DUMP_FILE=~/Downloads/dev.dump
    elif [[ -f "$cache_dir/dev.dump" ]]; then
        echo "No fresh dump in ~/Downloads, using cached version."
        DUMP_FILE="$cache_dir/dev.dump"
    else
        echo "Error: No dump file found. Download dev.dump to ~/Downloads first."
        return 1
    fi

    _va_wait_for_postgres || return 1

    psql -h localhost -p 5432 -U root -d postgres -c "CREATE ROLE pgadmin WITH SUPERUSER LOGIN PASSWORD 'dev';" 2>/dev/null
    psql -h localhost -p 5432 -U root -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'vidangel';"
    psql -h localhost -p 5432 -U root -d postgres -c 'DROP DATABASE IF EXISTS vidangel;'
    pg_restore -h localhost -p 5432 -U pgadmin -x -C -d postgres "$DUMP_FILE"

    # Cache the dump for future restores and clean up Downloads
    if [[ "$DUMP_FILE" == */Downloads/* ]]; then
        mkdir -p "$cache_dir"
        mv "$DUMP_FILE" "$cache_dir/dev.dump"
        echo "Dump cached at $cache_dir/dev.dump (removed from Downloads)"
    fi

    vidangel-reset-server
}

vidangel-preflight() {
    local pass=0
    local fail=0
    local warn=0

    _check() {
        if eval "$2" >/dev/null 2>&1; then
            echo "  PASS  $1"
            ((pass++))
        else
            echo "  FAIL  $1"
            ((fail++))
        fi
    }

    _warn() {
        if ! eval "$2" >/dev/null 2>&1; then
            echo "  WARN  $1"
            ((warn++))
        fi
    }

    echo "=== VidAngel Backend Preflight ==="
    echo ""

    # Docker / Colima
    _check "Colima running" "colima status"
    _check "vidangel-postgres running" "docker ps --format '{{.Names}}' | grep -qx vidangel-postgres"
    _check "vidangel-redis running" "docker ps --format '{{.Names}}' | grep -qx vidangel-redis"
    _check "typesense running" "docker ps --format '{{.Names}}' | grep -qx typesense"

    # Postgres connectivity + data
    _check "Postgres accepts connections" "psql -h localhost -p 5432 -U root -d vidangel -c 'SELECT 1'"
    local row_count=$(psql -h localhost -p 5432 -U root -d vidangel -tAc "SELECT count(*) FROM product_subscription" 2>/dev/null)
    if [[ -n "$row_count" && "$row_count" -gt 0 ]]; then
        echo "  PASS  Database has data ($row_count subscriptions)"
        ((pass++))
    else
        echo "  FAIL  Database is empty — run 'vidangel-restore-dev-dump'"
        ((fail++))
    fi

    # Migrations
    local unapplied=$(cd ~/vidangel-repo/vidangel-backend && source .venv/bin/activate && python3 manage.py showmigrations 2>/dev/null | grep '\[ \]' | wc -l | tr -d ' ')
    if [[ "$unapplied" -eq 0 ]]; then
        echo "  PASS  All migrations applied"
        ((pass++))
    else
        echo "  FAIL  $unapplied unapplied migration(s) — run 'python3 manage.py migrate'"
        ((fail++))
    fi

    # Redis
    _check "Redis responds to ping" "docker exec vidangel-redis redis-cli ping | grep -q PONG"

    # Typesense
    _check "Typesense healthy" "curl -sf http://localhost:8108/health -H 'X-TYPESENSE-API-KEY: testing000' | grep -q ok"

    # Vault
    _warn "Vault token may be expired" "vault token lookup"

    # .env
    _check ".env file exists" "test -f ~/vidangel-repo/vidangel-backend/.env"

    # venv
    _check "Virtual env exists" "test -f ~/vidangel-repo/vidangel-backend/.venv/bin/activate"

    echo ""
    echo "=== Results: $pass passed, $fail failed, $warn warning(s) ==="

    if [[ $fail -gt 0 ]]; then
        return 1
    fi
}

# Dev-server env exports (shared by run-devserver and switch-backend)
_va_devserver_env() {
    export CELERY_TASK_ALWAYS_EAGER=False
    export DISABLE_FINNEGAN_ANALYTICS=True
    export DISABLE_ITERABLE=True
    export DISABLE_SQS_PROCESSING=True
    export DJANGO_SETTINGS_MODULE=vidangel_backend.settings.dev
    export DJANGO_SHOW_TOOLBAR=True
    export ENABLE_TRACING_MIDDLEWARE=False
    export FILTER_HOST=https://sepia.vidangel.com
    export PYTHONUNBUFFERED=1
}

_va_runserver() {
    local certs="$HOME/vidangel-repo/vidangel-backend/server/certs"
    if [[ ! -f "$certs/localhost.pem" || ! -f "$certs/localhost-key.pem" ]]; then
        echo "  No HTTPS certs found. Generating via server/gen-certs.sh..."
        "$HOME/vidangel-repo/vidangel-backend/server/gen-certs.sh" || return 1
    fi
    python3 manage.py runserver_debug --cert-file "$certs/localhost.pem" --key-file "$certs/localhost-key.pem" --skip-checks --skip-migration-checks --print-sql-location --reloader-type=watchdog
}

# Resolve the backend checkout for the current shell (worktree-aware): walk up
# from $PWD looking for a Django backend root, else fall back to the main repo.
_va_backend_root() {
    local d="$PWD"
    while [[ "$d" != "/" ]]; do
        if [[ -f "$d/manage.py" && -d "$d/vidangel_backend" ]]; then
            echo "$d"; return 0
        fi
        d=$(dirname "$d")
    done
    echo "$HOME/vidangel-repo/vidangel-backend"
}

vidangel-run-devserver() {
    vidangel-preflight || { echo ""; echo "Fix the above failures before starting the server."; return 1; }
    echo ""

    # Worktree-aware: run the checkout for THIS shell, not always the main repo.
    local root; root=$(_va_backend_root)
    cd "$root" || return 1
    if [[ ! -f .venv/bin/activate ]]; then
        echo "  No .venv in $root — run 'vidangel-switch-backend' to build it."
        return 1
    fi
    source .venv/bin/activate
    _va_devserver_env
    _va_runserver
}

# Interactive worktree picker: list every backend worktree, pick one, switch.
vidangel-pick-worktree() {
    local main=$HOME/vidangel-repo/vidangel-backend
    local -a lines
    lines=("${(@f)$(git -C "$main" worktree list)}")
    if (( ${#lines} == 0 )); then
        echo "No worktrees found."; return 1
    fi
    echo "Select worktree:"
    local i=1 l
    for l in "${lines[@]}"; do
        printf "  %d) %s\n" "$i" "$l"
        ((i++))
    done
    echo -n "  # [1-${#lines}]: "
    local choice; read -r choice
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#lines} )); then
        echo "Invalid selection."; return 1
    fi
    # First whitespace-delimited field of the chosen line is the worktree path.
    local path="${${(z)lines[$choice]}[1]}"
    echo "=== Selected $path ==="
    cd "$path" || return 1
    vidangel-switch-backend
}

# Kill whatever Django dev server is currently running (any worktree) and free
# its port. Matches both the reloader parent and child runserver processes.
vidangel-kill-backend() {
    local pids
    pids=$(pgrep -f "manage.py runserver" 2>/dev/null)
    if [[ -n "$pids" ]]; then
        echo "  Killing current backend (pids: $(echo $pids | tr '\n' ' '))"
        echo "$pids" | xargs kill 2>/dev/null
        sleep 1
        pids=$(pgrep -f "manage.py runserver" 2>/dev/null)
        [[ -n "$pids" ]] && echo "$pids" | xargs kill -9 2>/dev/null
    else
        echo "  No running backend found."
    fi
    # Free port 8000 if anything still holds it
    local port_pids
    port_pids=$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null)
    [[ -n "$port_pids" ]] && { echo "  Freeing port 8000"; echo "$port_pids" | xargs kill -9 2>/dev/null; }
}

# Kill the current backend and run the one for THIS checkout (worktree-aware).
vidangel-switch-backend() {
    local root; root=$(_va_backend_root)
    echo "=== Switching backend -> $root ==="
    vidangel-kill-backend

    cd "$root" || return 1

    # Worktrees start without a .venv (gitignored, not carried over). Build one
    # with 'uv sync' so this branch's exact deps are installed. We don't copy the
    # main repo's .venv: venvs aren't relocatable (absolute paths in pyvenv.cfg /
    # bin shebangs / activate), and uv's global cache makes a fresh sync fast.
    if [[ ! -f .venv/bin/activate ]]; then
        echo "  No .venv in worktree — creating with '${_VA_UV_SYNC[*]}'..."
        # Remove any partial venv from a previous failed sync so we start clean,
        # and tear it down again if this sync fails (a half-built venv would
        # otherwise pass the activate check above on the next run).
        rm -rf .venv
        "${_VA_UV_SYNC[@]}" || { echo "  uv sync failed."; rm -rf .venv; return 1; }
    fi
    source .venv/bin/activate
    _va_devserver_env

    # .env render + shared infra up (idempotent: warm switch no-ops, cold one
    # bootstraps).
    _va_boot || return 1

    # Branches diverge on the shared dev DB — apply any pending migrations.
    _va_apply_migrations

    # NOT done here (deliberately — these mutate shared state and are slow; run
    # 'vidangel-start-backend' or 'vidangel-reset-server' if a branch needs them):
    #   - dev.dump restore (assumes the shared DB already has data)
    #   - makemigrations (migrations should be committed, not auto-generated)
    #   - run_update_popularity / update_search / offerings_materialized_view
    #     (shared search index + offerings view, already populated)
    echo "=== Starting backend from $root ==="
    _va_runserver
}

# Auto-apply any unapplied migrations for the current backend checkout.
_va_apply_migrations() {
    local unapplied
    unapplied=$(python3 manage.py showmigrations 2>/dev/null | grep -c '\[ \]')
    if [[ "$unapplied" -gt 0 ]]; then
        echo "  Applying $unapplied pending migration(s)..."
        python3 manage.py migrate
    else
        echo "  Migrations up to date."
    fi
}

vidangel-stop-backend() {
    echo "Stopping VidAngel Docker containers..."
    docker stop vidangel-postgres vidangel-redis typesense 2>/dev/null
    echo "Containers stopped"
}

vidangel-restart-backend() {
    echo "Restarting VidAngel Docker containers..."
    docker restart vidangel-postgres vidangel-redis typesense 2>/dev/null
    echo "Containers restarted"
}

vidangel-status-backend() {
    echo "VidAngel Docker Container Status:"
    docker ps -a --filter "name=vidangel-postgres" --filter "name=vidangel-redis" --filter "name=typesense" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

vidangel-celery-worker() {
    cd ~/vidangel-repo/vidangel-backend/
    source .venv/bin/activate
    export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
    DJANGO_SETTINGS_MODULE=vidangel_backend.settings.dev     watchmedo auto-restart -d ./apps -p "*.py" -R -- celery -A vidangel_backend worker -l INFO -P solo -E
}


##########################################################
# Agent task management
##########################################################
source ~/repos/agent-tools/agent-tools.sh

##########################################################
# Work exports
##########################################################
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export ANDROID_HOME=$HOME/Library/Android/sdk
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export BIM_CONN="host='127.0.0.1' port=24601 dbname='vidangel' user='$BIM_USER' password='$BIM_PASS'"
export FINNEGAN_CONN="host='127.0.0.1' port=24603 dbname='vidangel' user='$FINNEGAN_USER' password='$FINNEGAN_PASS'"

##########################################################
# PATH extensions
##########################################################
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH="/opt/homebrew/opt/ruby/bin:$PATH"
export PATH="$PATH:$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools"

##########################################################
# Work Alias
##########################################################
alias bim="python3 ~/vidangel-repo/vidangel-backend/manage.py"
alias va-management='eva -i i-00d603407628a0d0e'
# Function not alias: _va_ensure_env (defined earlier) calls this, and zsh
# expands aliases at function-parse time — an alias defined here would be unknown
# up there. A function resolves at call time, so order doesn't matter, and
# $VAULT_USER/$VAULT_PASS expand fresh on each call instead of being baked in.
# unalias guard: clears any stale alias left in the shell from a prior source,
# which would otherwise make zsh choke parsing the function definition below.
unalias vault-refresh-token 2>/dev/null
vault-refresh-token() { vault login -method=userpass username="$VAULT_USER" password="$VAULT_PASS"; }
alias p-bim="pgcli -h localhost -p 24603 -d vidangel -u $FINNEGAN_USER -W $FINNEGAN_PASS"
alias p-finnegan=""

