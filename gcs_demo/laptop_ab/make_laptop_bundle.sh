#!/usr/bin/env bash
# 在筆電建立方案 A／B 的 live 來源包（檔案清單和 PC 的 adr0002_v311_full_bundle_v1 相同，另加筆電版 3 個檔）。
# 只寫新的來源包資料夾，不跑任何模型。資料夾已存在就停（不覆蓋）。
#   bash gcs_demo/laptop_ab/make_laptop_bundle.sh <來源包名稱，例如 adr0002_laptop_bundle_v1>
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
BASE="$(cd -- "$REPO/../.." && pwd -P)"
MODELS="${GCS_OLLAMA_MODELS:-$HOME/.ollama-0.40.14/models}/manifests/registry.ollama.ai/library"
NAME="${1:-}"
[[ "$NAME" =~ ^adr0002_[A-Za-z0-9_]+_bundle_v[0-9]+$ ]] || { echo 'usage: make_laptop_bundle.sh adr0002_<名稱>_bundle_v<N>' >&2; exit 2; }
OUT="$BASE/$NAME"
[[ ! -e "$OUT" ]] || { echo "STOP：$OUT 已存在（不覆蓋）" >&2; exit 2; }
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || { echo 'STOP：repo 工作樹不乾淨' >&2; exit 2; }
COMMIT="$(git -C "$REPO" rev-parse HEAD)"

REPO_FILES=(gcs_demo/planb_runner.py gcs_demo/agent_planb.py gcs_demo/test_planb.py gcs_demo/outcomes.py gcs_demo/test_round2.py
 gcs_demo/test_round3.py gcs_demo/a4_runner.py gcs_demo/test_round4.py gcs_demo/test_fourcase.py gcs_demo/test_v310.py gcs_demo/test_v311.py
 gcs_demo/replay_runner.py gcs_demo/m4b_cases_eval_v3.json gcs_demo/m4b_cases_v39_smoke.json gcs_demo/m4b_cases_eval_v1.json
 gcs_demo/m4b_cases_dev_v3.json gcs_demo/m4b_cases_eval_v2.json gcs_demo/m4b_runner.py gcs_demo/gemma4_tokenizer.py gcs_demo/agent_m4b.py
 gcs_demo/id_graph.py gcs_demo/id_catalog_v1.json gcs_demo/m4b_cases_v2.json gcs_demo/test_m4b.py gcs_demo/m4_runner.py gcs_demo/agent_loop.py
 gcs_demo/agent_tools.py gcs_demo/areas_v1.json gcs_demo/preview_api.py gcs_demo/commit_layer.py gcs_demo/route_recheck.py gcs_demo/coverage.py
 gcs_demo/energy.py gcs_demo/planner.py gcs_demo/planner_t3.py gcs_demo/llm_gateway.py gcs_demo/rag_index.py ui_agent/qml/GcpAgentCore.js
 gcs_demo/domains/agriculture.json gcs_demo/domains/classes.json gcs_demo/domains/inspection.json gcs_demo/domains/multi_uav.json
 gcs_demo/test_laptop_linux.py gcs_demo/laptop_ab/run_ab_laptop.sh gcs_demo/laptop_ab/make_laptop_bundle.sh
 gcs_demo/reply_polish.py gcs_demo/test_polish.py
 gcs_demo/laptop_ab/__init__.py gcs_demo/laptop_ab/agent_service.py gcs_demo/laptop_ab/test_agent_service.py
 gcs_demo/laptop_ab/install_ab_into_ui.sh gcs_demo/laptop_ab/install_ab_payload_v1.sha256 gcs_demo/laptop_ab/test_install_ab.py
 gcs_demo/laptop_ab/ubuntu_build_ab.sh gcs_demo/laptop_ab/run_ab_desktop.sh
 gcs_demo/laptop_ab/qml/GcpAiAgentPanel.qml gcs_demo/laptop_ab/qml/GcpAiAgentRouteSink.qml gcs_demo/laptop_ab/qml/GcpAiAgentCore.js
 gcs_demo/laptop_ab/qml/GcpAiAgentBus.js gcs_demo/laptop_ab/qml/GcpAiAgentBuild.js.in)
BASE_FILES=(adr0002_rag_v1/index_v1/INDEX_MANIFEST.json adr0002_rag_v1/id_index_v1/ID_INDEX_MANIFEST.json
 adr0002_rag_v1/corpus/px4/FETCH_MANIFEST.json adr0002_rag_v1/corpus/qgc/FETCH_MANIFEST.json)
ALGO_FILES=("M4b與新架構_演算法說明_v3.5.md" "M4b與新架構_演算法說明_v3.6.md" "decisions-v3.6與after.md" "M4b與新架構_演算法說明_v3.7.md"
 "M4b與新架構_演算法說明_v3.7.1.md" "M4b與新架構_演算法說明_v3.8.md" "M4b與新架構_演算法說明_v3.9.md" "decisions-v3.9.md"
 "演算法說明_v3.10_第一批與離線回放_v2.md" "演算法說明_v3.10_第二批手冊檢索_v2.md" "decisions-v3.10.md" "decisions-v3.11.md"
 "decisions-v3.11.1.md" "v3.11手冊檢索探測結果_v1.md" "演算法說明_v3.11_手冊子句與向量英文詞_v1.md" "v3.10小範圍驗證結果_v1.md" "演算法說明_v3.12_回覆潤飾_v2.md" "decisions-v3.12.md"
 "方案AB待確認_雙方意見_v2.md" "decisions-Z3-Y.md")

missing=0
row() { if [[ -f "$2" ]]; then echo "$(sha256sum "$2" | cut -d' ' -f1) *$1"; else echo "缺少：$2" >&2; missing=$((missing+1)); fi; }
mkdir -- "$OUT"
echo "$COMMIT" > "$OUT/commit.txt"
{
  for f in "${REPO_FILES[@]}"; do row "$f" "$REPO/$f"; done
  for f in "${ALGO_FILES[@]}"; do row "adr0002_algo/$f" "$BASE/adr0002_algo/$f"; done
  row "$NAME/commit.txt" "$OUT/commit.txt"
  for f in "${BASE_FILES[@]}"; do row "$f" "$BASE/$f"; done
  row "ollama-manifest:gemma4:e2b" "$MODELS/gemma4/e2b"
  row "ollama-manifest:embeddinggemma-2:270m-q8_0-text" "$MODELS/embeddinggemma-2/270m-q8_0-text"
} > "$OUT/SHA256SUMS.txt"
if (( missing > 0 )); then mv -- "$OUT" "$OUT.INCOMPLETE"; echo "STOP：缺 $missing 個檔，已改名為 $OUT.INCOMPLETE（不是可用的來源包）" >&2; exit 2; fi
SUMS="$(sha256sum "$OUT/SHA256SUMS.txt" | cut -d' ' -f1)"
cat > "$OUT/MANIFEST.md" <<MD
# $NAME（筆電版方案 A／B 來源包）

建立：$(date '+%Y-%m-%d %H:%M') 台灣時間，主機 $(hostname)，commit \`$COMMIT\`，工作樹乾淨。
檔案清單同 PC \`adr0002_v311_full_bundle_v1\`，另加 \`test_laptop_linux.py\`、\`laptop_ab/run_ab_laptop.sh\`、\`laptop_ab/make_laptop_bundle.sh\`。
\`SHA256SUMS.txt\` 的 sha256：**\`$SUMS\`**（hash8＝\`${SUMS:0:8}\`），共 $(grep -c . "$OUT/SHA256SUMS.txt") 行。

live 同意規則：Claude、Codex 兩方對上面的 sha256 精確同意，使用者親打「同意 ${SUMS:0:8}」後才能執行。
MD
echo "BUNDLE OK: $OUT"
echo "sha256(SHA256SUMS.txt)=$SUMS"
echo "hash8=${SUMS:0:8}"
