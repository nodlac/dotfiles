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
     ssh -i ~/.ssh/lepotato -p 83 ubuntu@136.38.39.34
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

_va_ensure_repo() {
    cd ~/vidangel-repo/vidangel-backend
    git pull
    uv sync --all-groups
    source .venv/bin/activate
}

_va_ensure_env() {
    cd ~/vidangel-repo/vidangel-backend
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

# Zero to working in one command
vidangel-start-backend() {
    echo "=== VidAngel Backend Setup ==="
    echo ""

    echo "[1/7] Colima"
    _va_ensure_colima || return 1

    echo "[2/7] Repository & dependencies"
    _va_ensure_repo || return 1

    echo "[3/7] Environment"
    _va_ensure_env || return 1

    echo "[4/7] Docker containers"
    _va_ensure_containers || return 1

    echo "[5/7] Service readiness"
    _va_wait_for_postgres || return 1
    _va_wait_for_redis || return 1
    _va_wait_for_typesense || return 1

    echo "[6/7] Database data"
    _va_ensure_db_data || return 1

    echo "[7/7] Migrations & search index"
    vidangel-reset-server || return 1

    echo ""
    echo "=== Running preflight checks ==="
    vidangel-preflight || return 1

    echo ""
    echo "=== Starting dev server ==="
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

vidangel-run-devserver() {
    vidangel-preflight || { echo ""; echo "Fix the above failures before starting the server."; return 1; }
    echo ""

    cd ~/vidangel-repo/vidangel-backend
    source .venv/bin/activate

    export CELERY_TASK_ALWAYS_EAGER=False
    export DISABLE_FINNEGAN_ANALYTICS=True
    export DISABLE_ITERABLE=True
    export DISABLE_SQS_PROCESSING=True
    export DJANGO_SETTINGS_MODULE=vidangel_backend.settings.dev
    export DJANGO_SHOW_TOOLBAR=True
    export ENABLE_TRACING_MIDDLEWARE=False
    export FILTER_HOST=https://sepia.vidangel.com
    export PYTHONUNBUFFERED=1

    python3 manage.py runserver_debug --skip-checks --skip-migration-checks --print-sql-location --reloader-type=watchdog
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

##########################################################
# Work Alias
##########################################################
alias bim="python3 ~/vidangel-repo/vidangel-backend/manage.py"
alias va-management='eva -i i-00d603407628a0d0e'
alias vault-refresh-token="vault login -method=userpass username=$VAULT_USER password=$VAULT_PASS"
alias p-bim="pgcli -h localhost -p 24603 -d vidangel -u $FINNEGAN_USER -W $FINNEGAN_PASS"
alias p-finnegan=""

