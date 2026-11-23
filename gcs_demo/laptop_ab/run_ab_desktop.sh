#!/usr/bin/env bash
# 開啟方案 A 或 B 的正式 UI：MVP 服務（Ollama 11435 -> 閘道 8090 -> 任務／告警 8765）-> Agent 服務（A 8767／B 8768）-> UI。
#   bash gcs_demo/laptop_ab/run_ab_desktop.sh A <QGroundControl 執行檔> --fake
#   bash gcs_demo/laptop_ab/run_ab_desktop.sh B <QGroundControl 執行檔> --live <來源包資料夾> <hash8>
# --fake：Agent 用固定回覆的假模型（不是 live，不需同意）。
# --live：Agent 用真模型（專用 Ollama 0.40.14 在 11555，由 Agent 服務自己起、自己收）；只能在你親打「同意 <hash8>」之後用。
#         服務會先核對來源包（SHA256SUMS 的 hash8、commit、工作目錄乾淨、模型 manifest），不合就不起模型。
# 關掉 UI 視窗（或 Ctrl+C）時，這個腳本起的服務全部停掉；系統原本的 Ollama（11434，0.15.6）不動。
# 一次只開一個方案（A、B 共用 11555 與筆電記憶體）。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
usage() { echo 'usage: bash run_ab_desktop.sh <A|B> <QGroundControl executable> --fake | --live <bundle-dir> <hash8>' >&2; exit 2; }
[[ $# -ge 3 && "$1" =~ ^[AB]$ && -x "$2" ]] || usage
PLAN="$1"; EXE="$(realpath -- "$2")"; MODE="$3"
PORT=$([[ "$PLAN" == A ]] && echo 8767 || echo 8768)
AGENT_ARGS=(--plan "$PLAN" --port "$PORT")
case "$MODE" in
    --fake) [[ $# == 3 ]] || usage; AGENT_ARGS+=(--fake) ;;
    --live) [[ $# == 5 && "$5" =~ ^[0-9a-f]{8}$ && -f "$4/SHA256SUMS.txt" ]] || usage
            AGENT_ARGS+=(--bundle "$(realpath -- "$4")" --consent-hash8 "$5") ;;
    *) usage ;;
esac
INFO="$(dirname -- "$(dirname -- "$EXE")")/ab_build_logs/build_info.txt"
if [[ -f "$INFO" ]] && ! grep -qx "plan=$PLAN" "$INFO"; then echo "STOP: $EXE 是用別的方案編的（見 $INFO）" >&2; exit 2; fi

OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama-0.40.14/bin/ollama}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.ollama-0.40.14/models}"
export GCS_OLLAMA_BIN="${GCS_OLLAMA_BIN:-$OLLAMA_BIN}" GCS_OLLAMA_MODELS="${GCS_OLLAMA_MODELS:-$OLLAMA_MODELS}"
MODEL="${MODEL:-gemma4:e2b}"
OLLAMA_URL=http://127.0.0.1:11435
STAMP="$(date +%Y%m%d_%H%M%S)"
LOGDIR="$HOME/mvp_run_logs/ab_${PLAN}_$STAMP"; mkdir -p -- "$LOGDIR"
AGENT_LOG="$REPO/../interactive_logs/${PLAN}_${STAMP}${MODE/--/_}"
mkdir -p -- "$REPO/../interactive_logs"
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
PIDS=()
cleanup() { for (( i=${#PIDS[@]}-1; i>=0; i-- )); do kill "${PIDS[$i]}" 2>/dev/null || true; done
            for p in "${PIDS[@]}"; do wait "$p" 2>/dev/null || true; done
            echo "stopped services; logs in $LOGDIR and $AGENT_LOG"; }
trap cleanup EXIT INT TERM
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
wait_http() { for _ in $(seq 1 "${2:-60}"); do curl -fsS --max-time 2 "$1" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

cd -- "$REPO"
[[ -x "$OLLAMA_BIN" ]] || { echo "STOP: Ollama 0.40.14 not found at $OLLAMA_BIN" >&2; exit 2; }
for p in 8090 8765 8767 8768 11555; do port_busy "$p" && { echo "STOP: port $p already in use (another MVP/A/B or an evaluation run?)" >&2; exit 2; }; done

echo '[1/5] Ollama 0.40.14 on 127.0.0.1:11435 (MVP panels) ...'
if port_busy 11435; then echo '  already running, reusing it'
else OLLAMA_HOST=127.0.0.1:11435 nohup "$OLLAMA_BIN" serve > "$LOGDIR/ollama.log" 2>&1 & PIDS+=($!)
     wait_http "$OLLAMA_URL/api/version" || { echo 'STOP: Ollama did not start; see ollama.log' >&2; exit 3; }; fi
OLLAMA_HOST=127.0.0.1:11435 "$OLLAMA_BIN" list | grep -q "^$MODEL" || { echo "STOP: model $MODEL not in $OLLAMA_MODELS" >&2; exit 3; }

echo '[2/5] shared LLM gateway on 127.0.0.1:8090 ...'
GCS_GATEWAY_UPSTREAM=ollama GCS_GATEWAY_UP_URL="$OLLAMA_URL" GCS_GATEWAY_MODEL="$MODEL" \
GCS_GATEWAY_LOG="$LOGDIR/gateway_calls.jsonl" PYTHONPATH="$REPO" \
    nohup python3 -m gcs_demo.llm_gateway > "$LOGDIR/gateway.log" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8090/health || { echo 'STOP: gateway did not start; see gateway.log' >&2; exit 3; }

echo '[3/5] mission / alerts service on 127.0.0.1:8765 ...'
PYTHONPATH="$REPO" nohup python3 -m gcs_demo.server --port 8765 > "$LOGDIR/server.log" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8765/ || { echo 'STOP: mission/alerts service did not start; see server.log' >&2; exit 3; }

echo "[4/5] Agent service plan $PLAN ($MODE) on 127.0.0.1:$PORT, logs $AGENT_LOG ..."
PYTHONPATH="$REPO" nohup python3 -m gcs_demo.laptop_ab.agent_service "${AGENT_ARGS[@]}" --logdir "$AGENT_LOG" \
    > "$LOGDIR/agent_service.log" 2>&1 & PIDS+=($!)
wait_http "http://127.0.0.1:$PORT/api/agent/health" 180 || { echo 'STOP: Agent service did not start; see agent_service.log and SERVICE_INFO.json' >&2; cat "$LOGDIR/agent_service.log" >&2; exit 3; }
curl -fsS "http://127.0.0.1:$PORT/api/agent/health" | tee "$LOGDIR/agent_health.json"; echo

echo "[5/5] opening the formal UI, plan $PLAN (close the window to stop everything) ..."
GCS_LLM_BACKEND=openai GCS_LLM_URL=http://127.0.0.1:8090/f/ui/v1 GCS_LLM_MODEL="$MODEL" GCS_LLM_TIMEOUT_MS=32000 \
GCS_MVP_API_URL=http://127.0.0.1:8765 GCS_AB_AGENT_URL="http://127.0.0.1:$PORT" \
    "$EXE" > "$LOGDIR/ui.log" 2>&1 || echo "UI exited with code $?"
