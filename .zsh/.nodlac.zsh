#########################################################
# Llama commands
#########################################################

llama-start() {
  local server=${LLAMA_SERVER_BIN:-}
  [[ -n $server ]] || server=$(command -v llama-server)
  [[ -n $server ]] || { echo 'Install llama-server or set LLAMA_SERVER_BIN.'; return 1; }
  mkdir -p "$HOME/logs" || return 1
  nohup "$server" \
    --models-dir "${LLAMA_MODELS_DIR:-$HOME/llm-models}" \
    --host 127.0.0.1 \
    --port 9931 \
    --jinja \
    -ngl 99 \
    --flash-attn on \
    -c 8192 \
    > ~/logs/llama-router.log 2>&1 &
  echo "router started, pid $!  (log: ~/logs/llama-router.log)"
}

llama-stop() { 
    pkill -f "llama-server.*models-dir"
    echo "router stopped"
}

llama-status() {
    curl -s http://127.0.0.1:9931/health && echo
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
    fi
}

llama-restart() {
    llama-stop
    llama-start
}


#########################################################
# Aliases
#########################################################
alias connect-callisto="ssh -p 3250 nodlac@136.38.167.119"
