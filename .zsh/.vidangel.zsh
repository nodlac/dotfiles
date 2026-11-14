#
#########################################################
# Tardis Autocomplete
##########################################################
#
# Register before the shared shell runs compinit; a missing work checkout is OK.
[[ ! -d "$HOME/vidangel-repo/tiny-tardis/.completions/zsh" ]] ||
    fpath=( "$HOME/vidangel-repo/tiny-tardis/.completions/zsh" $fpath )

##########################################################
# Internal helpers (idempotent building blocks)
##########################################################
_va_ensure_colima() {
    # Linux uses the native Docker daemon; Colima is a macOS implementation detail.
    if [[ $OSTYPE != darwin* ]]; then
        docker info >/dev/null 2>&1 || { echo 'Start the Docker daemon first.'; return 1; }
        return 0
    fi
    if colima status &>/dev/null; then
        echo "  Colima already running"
    else
        echo "  Starting Colima..."
        # Let Colima choose defaults; larger machines can opt into more resources.
        colima start --cpu "${VA_COLIMA_CPUS:-2}" --memory "${VA_COLIMA_MEMORY:-4}"
    fi
}

# All groups except 'gpu' — that group pins Linux/Windows-only CUDA wheels
# (nvidia-*-cu12) with no macOS arm64 builds, so --all-groups alone fails here.
# Newer branches also have 'gpu-dev' (includes gpu), which --no-group gpu doesn't
# exclude; uv errors on --no-group for an undefined group, so add it per checkout.
# Run from the checkout root.
_va_uv_sync() {
    local -a cmd=(uv sync --all-groups --no-group gpu)
    grep -q '^gpu-dev = ' pyproject.toml && cmd+=(--no-group gpu-dev)
    echo "  ${cmd[*]}"
    "${cmd[@]}"
}

# Sync + activate the backend checkout for the current shell (worktree-aware):
# resolve the checkout from $PWD, pull, install deps, activate the venv. uv sync
# creates .venv when absent, so a fresh worktree bootstraps here too.
_va_ensure_repo() {
    local root; root=$(_va_backend_root)
    cd "$root" || return 1
    git pull
    _va_uv_sync || return 1
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

# Args before `--` are docker run flags; args after are the container command.
_va_ensure_container() {
    local name=$1; shift
    local image=$1; shift
    local i=${@[(i)--]}
    local -a run_args=("${@[1,i-1]}") cmd_args=("${@[i+1,-1]}")

    if docker ps --format '{{.Names}}' | grep -qx "$name"; then
        echo "  $name already running"
    elif docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        echo "  Starting existing $name..."
        docker start "$name"
    else
        echo "  Creating $name..."
        docker run --name="$name" -d --restart=always "${run_args[@]}" "$image" "${cmd_args[@]}"
    fi
}

_va_ensure_containers() {
    _va_ensure_container vidangel-postgres postgres:17 \
        -e POSTGRES_USER=root \
        -e POSTGRES_PASSWORD=dev \
        -e POSTGRES_DB=vidangel \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -v vidangel-postgres-data:/var/lib/postgresql/data \
        -p 5432:5432 \
        -- \
        -c shared_buffers=3GB \
        -c effective_cache_size=8GB \
        -c work_mem=32MB \
        -c maintenance_work_mem=1GB \
        -c synchronous_commit=off \
        -c full_page_writes=off \
        -c max_wal_size=4GB \
        -c checkpoint_completion_target=0.9 \
        -c random_page_cost=1.1 \
        -c effective_io_concurrency=200 \
        -c max_worker_processes=8 \
        -c max_parallel_workers=6 \
        -c max_parallel_workers_per_gather=3 \
        -c max_parallel_maintenance_workers=3 \
        -c dynamic_shared_memory_type=mmap

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

    local answer
    if [[ -f ~/.cache/vidangel/dev.dump ]]; then
        echo -n "  Restore from cached dump? (n = pull fresh from S3) [Y/n] "
        read -r answer
        [[ "$answer" =~ ^[Nn] ]] || { vidangel-refresh-db --cached; return $?; }
    else
        echo -n "  Pull dev.dump from S3 and restore? [Y/n] "
        read -r answer
        [[ "$answer" =~ ^[Nn] ]] && { echo "  Skipping. Run 'vidangel-refresh-db' when ready."; return 1; }
    fi
    vidangel-refresh-db
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
    vidangel-run-devserver "$@"
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

# The account's Enforce_MFA policy denies S3 without MFA, so plain IAM keys
# can't read the dump bucket. Session creds land in the `mfa` profile and are
# reused until they expire.
_va_aws_mfa() {
    if aws sts get-caller-identity --profile mfa &>/dev/null; then
        echo "  AWS MFA session still valid"
        return 0
    fi
    local serial code k s t
    serial=$(aws iam list-mfa-devices --query 'MFADevices[0].SerialNumber' --output text) || return 1
    echo -n "  MFA code for $serial: "
    read -r code
    read -r k s t <<<"$(aws sts get-session-token --serial-number "$serial" --token-code "$code" \
        --duration-seconds 43200 \
        --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)" || return 1
    [[ -n "$t" ]] || { echo "  FAIL: no session token returned"; return 1; }
    aws configure set aws_access_key_id "$k" --profile mfa
    aws configure set aws_secret_access_key "$s" --profile mfa
    aws configure set aws_session_token "$t" --profile mfa
    echo "  AWS MFA session ready (12h)"
}

# Pulls the nightly dump from S3 and replaces the local vidangel DB.
# --cached restores the last downloaded dump without hitting S3.
vidangel-refresh-db() {
    local cache_dir=~/.cache/vidangel
    local DUMP_FILE="$cache_dir/dev.dump"

    if [[ "$1" != "--cached" ]]; then
        echo "[1/3] AWS MFA login"
        _va_aws_mfa || return 1
        echo "[2/3] Downloading s3://vidangel-db-daily-dump/dev.dump"
        mkdir -p "$cache_dir"
        aws s3 cp s3://vidangel-db-daily-dump/dev.dump "$DUMP_FILE.part" --profile mfa \
            && mv "$DUMP_FILE.part" "$DUMP_FILE" || return 1
    fi
    [[ -f "$DUMP_FILE" ]] || { echo "Error: no dump at $DUMP_FILE"; return 1; }

    echo "[3/3] Restoring $DUMP_FILE (drops local vidangel DB)"
    _va_wait_for_postgres || return 1

    psql -h localhost -p 5432 -U root -d postgres -c "CREATE ROLE pgadmin WITH SUPERUSER LOGIN PASSWORD 'dev';" 2>/dev/null
    psql -h localhost -p 5432 -U root -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'vidangel';"
    psql -h localhost -p 5432 -U root -d postgres -c 'DROP DATABASE IF EXISTS vidangel;'
    pg_restore -h localhost -p 5432 -U pgadmin -x -C -j 6 -d postgres "$DUMP_FILE"

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
        echo "  FAIL  Database is empty — run 'vidangel-refresh-db'"
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
    export PGGSSENCMODE=disable
}

# Plain HTTP by default. Pass --secure (or set VA_SECURE=1) for TLS.
#
# HTTP is the default because the iOS/tvOS sims hardcode http://127.0.0.1:8000
# for the `local` environment, and because serving TLS on a *.vidangel.com host
# makes Django emit HSTS (base.py: max-age=3600, includeSubDomains), which pins
# that hostname to HTTPS in the browser for an hour afterwards.
_va_runserver() {
    local secure=""
    [[ -n "$VA_SECURE" ]] && secure=1
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --secure)   secure=1 ;;
            --insecure) secure="" ;;
        esac
        shift
    done

    # Second server in another worktree: VA_PORT=8001 vidangel-run-devserver.
    local port=${VA_PORT:-8000}
    local -a tls_args
    if [[ -n "$secure" ]]; then
        local certs="$HOME/vidangel-repo/vidangel-backend/server/certs"
        if [[ ! -f "$certs/localhost.pem" || ! -f "$certs/localhost-key.pem" ]]; then
            echo "  No HTTPS certs found. Generating via server/gen-certs.sh..."
            "$HOME/vidangel-repo/vidangel-backend/server/gen-certs.sh" || return 1
        fi
        tls_args=(--cert-file "$certs/localhost.pem" --key-file "$certs/localhost-key.pem")
        echo "  Serving HTTPS on :$port"
    else
        echo "  Serving HTTP on :$port (pass --secure for TLS)"
    fi

    python3 manage.py runserver_debug "$port" "${tls_args[@]}" --skip-checks --skip-migration-checks --print-sql-location --reloader-type=watchdog
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
    _va_runserver "$@"
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

# Make a checkout runnable (venv + env files) without touching anything shared:
# no kill, no infra, no migrations, no runserver — safe in any number of
# worktrees at once. Idempotent. Defaults to the checkout for THIS shell.
vidangel-prep-backend() {
    local root=${1:-$(_va_backend_root)}
    root=${root:A}
    if [[ ! -f "$root/manage.py" ]]; then
        echo "  Not a backend checkout: $root"; return 1
    fi
    echo "=== Prepping backend -> $root ==="

    # psycopg2 + GSSAPI negotiation segfaults pytest-xdist workers on macOS.
    export PGGSSENCMODE=disable

    # Subshell so prepping another path doesn't move the caller's cwd.
    (
        cd "$root" || exit 1

        # Worktrees start without a .venv (gitignored, not carried over). Build one
        # with 'uv sync' so this branch's exact deps are installed. We don't copy the
        # main repo's .venv: venvs aren't relocatable (absolute paths in pyvenv.cfg /
        # bin shebangs / activate), and uv's global cache makes a fresh sync fast.
        if [[ ! -f .venv/bin/activate ]]; then
            echo "  No .venv in worktree — creating with uv sync..."
            # Remove any partial venv from a previous failed sync so we start clean,
            # and tear it down again if this sync fails (a half-built venv would
            # otherwise pass the activate check above on the next run).
            rm -rf .venv
            _va_uv_sync || { echo "  uv sync failed."; rm -rf .venv; exit 1; }
        fi

        # Only render when missing: re-rendering would hit vault once per worktree
        # and write through .env symlinks into the main repo's copy. switch-backend
        # still re-renders on every switch via _va_boot.
        [[ -e .env ]] || _va_ensure_env || exit 1

        # .env.local is hand-kept local overrides, not rendered — share the main
        # repo's so every worktree runs with the same overrides.
        local main=$HOME/vidangel-repo/vidangel-backend
        if [[ ! -e .env.local && -f $main/.env.local && $PWD != $main ]]; then
            ln -s "$main/.env.local" .env.local && echo "  Linked .env.local from main repo"
        fi
    )
}

# Prep every backend worktree; keeps going past failures and lists them.
vidangel-prep-all-backends() {
    local main=$HOME/vidangel-repo/vidangel-backend
    local -a failed
    local p
    for p in ${(f)"$(git -C "$main" worktree list --porcelain | sed -n 's/^worktree //p')"}; do
        [[ -f "$p/manage.py" ]] || continue
        vidangel-prep-backend "$p" || failed+=("$p")
    done
    (( ${#failed} )) && { printf "  FAILED: %s\n" "${failed[@]}"; return 1; }
    return 0
}

# Kill the current backend and run the one for THIS checkout (worktree-aware).
vidangel-switch-backend() {
    local root; root=$(_va_backend_root)
    echo "=== Switching backend -> $root ==="
    vidangel-kill-backend

    cd "$root" || return 1

    vidangel-prep-backend "$root" || return 1
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
[[ ! -r "$HOME/repos/agent-tools/agent-tools.sh" ]] || source "$HOME/repos/agent-tools/agent-tools.sh"

##########################################################
# Work exports
##########################################################
if [[ $OSTYPE == darwin* ]]; then
    if [[ -x /usr/libexec/java_home ]]; then
        _va_java_home=$(/usr/libexec/java_home -v 17 2>/dev/null)
        [[ -z $_va_java_home ]] || export JAVA_HOME=$_va_java_home
        unset _va_java_home
    fi
    export ANDROID_HOME=${ANDROID_HOME:-$HOME/Library/Android/sdk}
else
    export ANDROID_HOME=${ANDROID_HOME:-$HOME/Android/Sdk}
fi
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
# Zsh completion is initialized once by the shared shell.
export BIM_CONN="host='127.0.0.1' port=24601 dbname='vidangel' user='$BIM_USER' password='$BIM_PASS'"
export FINNEGAN_CONN="host='127.0.0.1' port=24603 dbname='vidangel' user='$FINNEGAN_USER' password='$FINNEGAN_PASS'"

##########################################################
# PATH extensions
##########################################################
for _va_bin in "$ANDROID_HOME/platform-tools" "$ANDROID_HOME/emulator"; do
    [[ ! -d $_va_bin ]] || path+=("$_va_bin")
done
if [[ $OSTYPE == darwin* ]]; then
    for _va_bin in /opt/homebrew/opt/ruby/bin /usr/local/opt/ruby/bin; do
        [[ ! -d $_va_bin ]] || path=("$_va_bin" $path)
    done
fi
unset _va_bin

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
# Resolve credentials at invocation time, not during shell startup.
p-bim() { pgcli -h localhost -p 24603 -d vidangel -u "$FINNEGAN_USER"; }
alias p-finnegan=""

