##########################################################
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

# variable contains commands to refresh the vidangel db
vidangel-restore-dev-dump() {
    DUMP_FILE=~/Downloads/dev.dump

    if [ ! -f "$DUMP_FILE" ]; then
      echo "Error: dump file not found at $DUMP_FILE"
      exit 1
    fi
    psql -h localhost -p 5432 -U root -d postgres -c "CREATE ROLE pgadmin WITH SUPERUSER LOGIN PASSWORD 'dev';"
    psql -h localhost -p 5432 -U root -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'vidangel';"
    psql -h localhost -p 5432 -U root -d postgres -c 'DROP DATABASE vidangel;'
    pg_restore -h localhost -p 5432 -U pgadmin -x -C -d postgres $DUMP_FILE
}

vidangel-start-backend() {
    echo "====================================================="
    echo ""
    echo "Did you remember to open docker?"
    echo ""
    echo "====================================================="
    cd ~/vidangel-repo/vidangel-backend
    git pull
    uv sync
    source ~/vidangel-repo/vidangel-backend/.venv/bin/activate
    vault login -method=userpass username=caldon password=GYK3cg67foBzEw
    w2 ~/vidangel-repo/vidangel-backend/.templates/dev.env.hbs > .env

    # Start PostgreSQL (if not already running)
    if ! docker ps | grep -q vidangel-postgres; then
        if docker ps -a | grep -q vidangel-postgres; then
            echo "  Starting existing vidangel-postgres container..."
            docker start vidangel-postgres
        else
            echo "  Creating vidangel-postgres container..."
            docker run --name=vidangel-postgres \
              -d \
              -e POSTGRES_USER=root \
              -e POSTGRES_PASSWORD=dev \
              -e POSTGRES_DATABASE=vidangel \
              -e POSTGRES_HOST_AUTH_METHOD=trust \
              -v vidangel-postgres-data:/var/lib/postgresql/data \
              -p 5432:5432 \
              --restart=always \
              postgres:17
        fi
    else
        echo "  vidangel-postgres already running"
    fi
    
    # Start Redis (if not already running)
    if ! docker ps | grep -q vidangel-redis; then
        if docker ps -a | grep -q vidangel-redis; then
            echo "  Starting existing vidangel-redis container..."
            docker start vidangel-redis
        else
            echo "  Creating vidangel-redis container..."
            docker run --name=vidangel-redis \
              -d \
              -p 6379:6379 \
              --restart=always \
              redis:6-bullseye
        fi
    else
        echo "  vidangel-redis already running"
    fi
    
    # Start Typesense (if not already running)
    if ! docker ps | grep -q typesense; then
        if docker ps -a | grep -q typesense; then
            echo "  Starting existing typesense container..."
            docker start typesense
        else
            echo "  Creating typesense container..."
            docker run --name typesense \
              -d \
              -p 8108:8108 \
              -v /opt/docker/typesense:/data \
              -e TYPESENSE_DATA_DIR=/data \
              -e TYPESENSE_API_KEY=testing000 \
              --restart=always \
              typesense/typesense:29.0
        fi
    else
        echo "  typesense already running"
    fi
}

vidangel-reset-serve() {
    python3 manage.py makemigrations
    python3 manage.py migrate
    # Sets the base values for the popularity score in our index.
    python manage.py run_update_popularity
    # This destroys the current search index and rebuilds from scratch.
    #  It doesn't take too long and helps prevent out of sync issues with the index.
    python manage.py update_search
    # Update the Offerings View which will create a modified_at history 
    #  in Redis for incremental search updates.
    python manage.py offerings_materialized_view -r
    python manage.py offerings_materialized_view -c
    # # Run the "test suite" of canned searches.
    # python manage.py score_search_test
}

vidangel-run-devserver() {
    export CELERY_TASK_ALWAYS_EAGER=f
    export DISABLE_FINNEGAN_ANALYTICS=True
    export DISABLE_ITERABLE=True
    export DISABLE_SQS_PROCESSING=False
    export DJANGO_SETTINGS_MODULE=vidangel_backend.settings.dev
    export DJANGO_SHOW_TOOLBAR=T
    export ENABLE_TRACING_MIDDLEWARE=False
    export FILTER_HOST=https://sepia.vidangel.com
    export IMAGE_WIZARD_URL=http://0.0.0.0:8998/v1
    export PYTHONUNBUFFERED=1

    python manage.py runserver_debug --skip-checks --skip-migration-checks --print-sql-location --reloader-type=watchdog
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
    DJANGO_SETTINGS_MODULE=vidangel_backend.settings.dev     watchmedo auto-restart -d ./apps -p "*.py" -R -- celery -A vidangel_backend worker -l INFO -P processes -E -c8
}


##########################################################
# Work exports
##########################################################
export ANDROID_HOME=/Users/Medina_Station/Library/Android/sdk
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

##########################################################
# Work Alias
##########################################################
alias bim="python3 ~/vidangel-repo/vidangel-backend/manage.py"
alias va-management='eva -i i-00d603407628a0d0e'
alias vault-refresh-token="vault login -method=userpass username=$VAULT_USER password=$VAULT_PASS"


##########################################################
# Vi mode
##########################################################
set -o vi

# Cursor: block in normal mode, beam in insert mode
if [ -n "$BASH_VERSION" ]; then
  bind 'set show-mode-in-prompt on'
  bind '"\\e[?2004h": ""'  # optional: bracketed paste
  
  # Cursor shape via readline
  bind 'set vi-ins-mode-string \1\e[6 q\2'
  bind 'set vi-cmd-mode-string \1\e[2 q\2'

elif [ -n "$ZSH_VERSION" ]; then
  bindkey -v

  zle-keymap-select() {
    if [[ $KEYMAP == vicmd ]]; then
      echo -ne '\e[2 q'  # block
    else
      echo -ne '\e[6 q'  # beam
    fi
  }
  zle -N zle-keymap-select

  zle-line-init() { echo -ne '\e[6 q'; }
  zle -N zle-line-init
fi

# Reset cursor to beam on exit
trap 'echo -ne "\e[6 q"' EXIT


autoload -Uz compinit && compinit
# Show a menu when you hit tab
zstyle ':completion:*' menu select
# List descriptions for options (the gray text in Fish)
zstyle ':completion:*' verbose yes
zstyle ':completion:*:descriptions' format '%B%d%b'
zstyle ':completion:*:messages' format '%d'
zstyle ':completion:*:warnings' format 'No matches for: %d'


##########################################################
# Agent task management
##########################################################
source ~/work_scripts/agent-tools.sh


##########################################################
# PATH extensions
##########################################################
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH="/opt/homebrew/opt/ruby/bin:$PATH"


##########################################################
# Exports
##########################################################
export BIM_CONN="host='127.0.0.1' port=24601 dbname='vidangel' user='$BIM_USER' password='$BIM_PASS'"
export FINNEGAN_CONN="host='127.0.0.1' port=24603 dbname='vidangel' user='$FINNEGAN_USER' password='$FINNEGAN_PASS'"
