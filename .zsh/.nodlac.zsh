llama-start() {
  nohup ~/llama.cpp/build-cuda/bin/llama-server \
    --models-dir ~/llm-models \
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
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
}

llama-restart() {
    llama-stop
    llama-start
}
