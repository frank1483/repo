#!/usr/bin/env bash
# 開啟 MVP 桌面版：Ollama 0.40.14（11435）-> 共用 LLM 閘道（8090）-> 任務／告警服務（8765）-> 正式 UI。
# 關掉 UI 視窗（或按 Ctrl+C）時，這個腳本自己起的服務會一起停掉；系統原本的 Ollama（11434，0.15.6）不動。
#   bash ui_agent/mvp/run_mvp_desktop.sh <QGroundControl 執行檔>
# 可覆寫：OLLAMA_BIN（~/ollama-0.40.14/bin/ollama）、OLLAMA_MODELS（~/.ollama-0.40.14/models）、MODEL（gemma4:e2b）
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
[[ $# == 1 && -x "$1" ]] || { echo 'usage: bash run_mvp_desktop.sh <QGroundControl executable>' >&2; exit 2; }
EXE="$(realpath -- "$1")"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama-0.40.14/bin/ollama}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.ollama-0.40.14/models}"
MODEL="${MODEL:-gemma4:e2b}"
OLLAMA_URL=http://127.0.0.1:11435
LOGDIR="$HOME/mvp_run_logs/$(date +%Y%m%d_%H%M%S)"; mkdir -p -- "$LOGDIR"
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; echo "stopped MVP services; logs in $LOGDIR"; }
trap cleanup EXIT INT TERM
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
wait_http() { for _ in $(seq 1 60); do curl -fsS --max-time 2 "$1" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

[[ -x "$OLLAMA_BIN" ]] || { echo "STOP: Ollama 0.40.14 not found at $OLLAMA_BIN" >&2; exit 2; }
for p in 8090 8765; do port_busy "$p" && { echo "STOP: port $p already in use (another MVP running?)" >&2; exit 2; }; done

echo '[1/4] Ollama 0.40.14 on 127.0.0.1:11435 ...'
if port_busy 11435; then echo '  already running, reusing it'
else OLLAMA_HOST=127.0.0.1:11435 nohup "$OLLAMA_BIN" serve > "$LOGDIR/ollama.log" 2>&1 & PIDS+=($!)
     wait_http "$OLLAMA_URL/api/version" || { echo 'STOP: Ollama did not start; see ollama.log' >&2; exit 3; }; fi
curl -fsS "$OLLAMA_URL/api/version" | tee "$LOGDIR/ollama_version.json"; echo
OLLAMA_HOST=127.0.0.1:11435 "$OLLAMA_BIN" list | grep -q "^$MODEL" || { echo "STOP: model $MODEL not in $OLLAMA_MODELS" >&2; exit 3; }

echo '[2/4] shared LLM gateway on 127.0.0.1:8090 ...'
GCS_GATEWAY_UPSTREAM=ollama GCS_GATEWAY_UP_URL="$OLLAMA_URL" GCS_GATEWAY_MODEL="$MODEL" \
GCS_GATEWAY_LOG="$LOGDIR/gateway_calls.jsonl" PYTHONPATH="$REPO" \
    nohup python3 -P -m gcs_demo.llm_gateway > "$LOGDIR/gateway.log" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8090/health || { echo 'STOP: gateway did not start; see gateway.log' >&2; exit 3; }

echo '[3/4] mission / alerts service on 127.0.0.1:8765 ...'
PYTHONPATH="$REPO" nohup python3 -P -m gcs_demo.server --port 8765 > "$LOGDIR/server.log" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8765/ || { echo 'STOP: mission/alerts service did not start; see server.log' >&2; exit 3; }

echo '[4/4] opening the formal UI (close the window to stop everything) ...'
GCS_LLM_BACKEND=openai GCS_LLM_URL=http://127.0.0.1:8090/f/ui/v1 GCS_LLM_MODEL="$MODEL" GCS_LLM_TIMEOUT_MS=32000 \
GCS_MVP_API_URL=http://127.0.0.1:8765 \
    "$EXE" > "$LOGDIR/ui.log" 2>&1 || echo "UI exited with code $?"
