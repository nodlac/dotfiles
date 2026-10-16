start-llama() {
  nohup ~/llama.cpp/build-cuda/bin/llama-server \
    --models-dir ~/llm-models \
    --host 127.0.0.1 \
    --port 8080 \
    --ngl 99 \
    --flash-attn on \
    -c 8192 \
    > ~/notes/router.log 2>&1 &
  echo "router started, pid $!  (log: ~/notes/router.log)"
}

stop-llama () { 
    pkill -f "llama-server.*models-dir"
    echo "router stopped"
}

llama-status() {
    curl -s http://127.0.0.1:8080/health && echo
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
}}
