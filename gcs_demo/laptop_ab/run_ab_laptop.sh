#!/usr/bin/env bash
# 在編譯筆電（Ubuntu 22.04）上依序跑方案 A（m4b_runner）與方案 B（planb_runner）；每個 phase 先 A 再 B，各一次。
# 執行器本身會核對來源包（hash8、檔案雜湊、commit、工作樹乾淨、模型 manifest）並自己起專用 Ollama（預設 11555）。
#   bash gcs_demo/laptop_ab/run_ab_laptop.sh --check                                  # 只做唯讀檢查，不跑任何東西
#   bash gcs_demo/laptop_ab/run_ab_laptop.sh --fake <run前綴> [smoke] [research]          # 假模型，只檢查執行器（不是 live）
#   bash gcs_demo/laptop_ab/run_ab_laptop.sh --live <來源包目錄> <hash8> <run前綴> [smoke] [research]
# live 只有在 Claude、Codex 對同一份來源包 SHA256 精確同意，且使用者親打「同意 <hash8>」之後才能執行。
# 可覆寫：GCS_OLLAMA_BIN（~/ollama-0.40.14/bin/ollama）、GCS_OLLAMA_MODELS（~/.ollama-0.40.14/models）、OLLAMA_PORT（11555）
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
BASE="$(cd -- "$REPO/../.." && pwd -P)"          # 執行器把來源包裡的相對路徑接在這裡（PC 上是「碩士論文」）
RUNS="$(cd -- "$REPO/.." && pwd -P)/runs"
export GCS_OLLAMA_BIN="${GCS_OLLAMA_BIN:-$HOME/ollama-0.40.14/bin/ollama}"
export GCS_OLLAMA_MODELS="${GCS_OLLAMA_MODELS:-$HOME/.ollama-0.40.14/models}"
OLLAMA_PORT="${OLLAMA_PORT:-11555}"
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
PY="${PYTHON:-python3}"
MAN="$GCS_OLLAMA_MODELS/manifests/registry.ollama.ai/library"
GEMMA_MANIFEST_SHA=b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2   # gcs_demo/gemma4_tokenizer.py 寫死的值

problems=0
need() { if eval "$2"; then echo "OK   $1"; else echo "缺少 $1"; problems=$((problems+1)); fi; }
check() {
    echo "repo=$REPO"; echo "base=$BASE"; echo "runs=$RUNS"
    need "python3 >= 3.10" "$PY -c 'import sys; sys.exit(sys.version_info < (3, 10))'"
    need "git 工作樹乾淨（live 必要）" "[[ -z \"\$(git -C '$REPO' status --porcelain=v1 --untracked-files=all)\" ]]"
    need "Ollama 0.40.14 執行檔 $GCS_OLLAMA_BIN" "[[ -x '$GCS_OLLAMA_BIN' ]]"
    need "Ollama 版本字串含 0.40.14（--version）" "'$GCS_OLLAMA_BIN' --version 2>&1 | grep -q '0\.40\.14'"
    need "gemma4:e2b manifest（sha 要等於 ${GEMMA_MANIFEST_SHA:0:8}）" "[[ -f '$MAN/gemma4/e2b' && \"\$(sha256sum '$MAN/gemma4/e2b' | cut -d' ' -f1)\" == $GEMMA_MANIFEST_SHA ]]"
    need "embeddinggemma-2:270m-q8_0-text manifest" "[[ -f '$MAN/embeddinggemma-2/270m-q8_0-text' ]]"
    need "手冊索引 $BASE/adr0002_rag_v1/index_v1" "[[ -f '$BASE/adr0002_rag_v1/index_v1/INDEX_MANIFEST.json' ]]"
    need "ID 索引 $BASE/adr0002_rag_v1/id_index_v1" "[[ -f '$BASE/adr0002_rag_v1/id_index_v1/ID_INDEX_MANIFEST.json' ]]"
    need "演算法說明 $BASE/adr0002_algo" "[[ -d '$BASE/adr0002_algo' ]]"
    need "埠 $OLLAMA_PORT 空著" "! (exec 3<>/dev/tcp/127.0.0.1/$OLLAMA_PORT) 2>/dev/null"
    free -m | awk '/^Mem:/{print "記憶體：總 " $2 " MB，可用 " $7 " MB"}'
    echo "問題數：$problems"
}

mode="${1:-}"; shift || true
case "$mode" in
    --check) check; exit $(( problems > 0 )) ;;
    --fake) [[ $# -ge 1 ]] || { echo 'usage: --fake <run前綴> [phase...]' >&2; exit 2; }
            prefix="$1"; shift; extra=(--fake) ;;
    --live) [[ $# -ge 3 ]] || { echo 'usage: --live <來源包目錄> <hash8> <run前綴> [phase...]' >&2; exit 2; }
            bundle="$(cd -- "$1" && pwd -P)"; hash8="$2"; prefix="$3"; shift 3
            [[ "$hash8" =~ ^[0-9a-f]{8}$ ]] || { echo 'hash8 要是 8 個小寫十六進位字元' >&2; exit 2; }
            extra=(--bundle "$bundle" --consent-hash8 "$hash8" --ollama-port "$OLLAMA_PORT") ;;
    *) sed -n 2,9p "$0"; exit 2 ;;
esac
[[ "$prefix" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'run前綴只能用英數、底線、點、減號' >&2; exit 2; }
phases=("$@"); [[ ${#phases[@]} -gt 0 ]] || phases=(smoke research)
for ph in "${phases[@]}"; do
    [[ "$ph" == smoke || "$ph" == research ]] || { echo "未知 phase：$ph" >&2; exit 2; }
    for g in A B; do [[ ! -e "$RUNS/${prefix}_${g}_${ph}_run1" ]] || { echo "STOP：已存在 $RUNS/${prefix}_${g}_${ph}_run1（只跑一次，不覆蓋）" >&2; exit 2; }; done
done
check >/dev/null || true
[[ "$mode" == --fake || $problems == 0 ]] || { check; echo 'STOP：檢查沒過，未啟動任何東西' >&2; exit 2; }
mkdir -p -- "$RUNS"
cd -- "$REPO"
console="$RUNS/${prefix}_console.txt"
# CODEX-APP-0450 第 2 點：實跑前記錄完整清冊雜湊與實際 Ollama 版本（寫一次，已存在就停）
pre="$RUNS/${prefix}_preflight.txt"
[[ ! -e "$pre" ]] || { echo "STOP：已存在 $pre（只跑一次，不覆蓋）" >&2; exit 2; }
{
    echo "time=$(date -Iseconds)"; echo "mode=$mode"; echo "commit=$(git rev-parse HEAD)"
    echo "git_status_lines=$(git status --porcelain=v1 --untracked-files=all | wc -l)"
    if [[ "$mode" == --live ]]; then
        echo "bundle=$bundle"
        echo "bundle_sha256sums_sha256=$(sha256sum "$bundle/SHA256SUMS.txt" | cut -d' ' -f1)"
        echo "bundle_commit=$(head -1 "$bundle/commit.txt")"
    fi
    echo "ollama_bin=$GCS_OLLAMA_BIN"
    echo "ollama_bin_sha256=$(sha256sum "$GCS_OLLAMA_BIN" | cut -d' ' -f1)"
    echo "ollama_version_output=$("$GCS_OLLAMA_BIN" --version 2>&1 | tr '\n' ' ')"
    echo "ollama_models=$GCS_OLLAMA_MODELS"
    echo "python=$("$PY" --version 2>&1)"; echo "host=$(uname -a)"
} > "$pre"
cat "$pre"
if [[ "$mode" == --live ]]; then
    full="$(grep '^bundle_sha256sums_sha256=' "$pre" | cut -d= -f2)"
    [[ "${full:0:8}" == "$hash8" ]] || { echo "STOP：來源包清冊雜湊 $full 和 hash8 $hash8 不符" >&2; exit 2; }
    [[ "$(grep '^bundle_commit=' "$pre" | cut -d= -f2)" == "$(git rev-parse HEAD)" ]] || { echo 'STOP：來源包 commit 和目前 HEAD 不同' >&2; exit 2; }
    grep -q '^ollama_version_output=.*0\.40\.14' "$pre" || { echo 'STOP：Ollama 版本不是 0.40.14' >&2; exit 2; }
fi
{ echo "start=$(date -Iseconds)"; echo "host=$(uname -a)"; echo "commit=$(git rev-parse HEAD)"; echo "mode=$mode phases=${phases[*]}"; } | tee -a "$console"
for ph in "${phases[@]}"; do
    a="$RUNS/${prefix}_A_${ph}_run1"; b="$RUNS/${prefix}_B_${ph}_run1"
    echo "== A $ph -> $a" | tee -a "$console"
    "$PY" -m gcs_demo.m4b_runner --phase "$ph" --out "$a" "${extra[@]}" 2>&1 | tee -a "$console"
    echo "== B $ph -> $b" | tee -a "$console"
    "$PY" -m gcs_demo.planb_runner --phase "$ph" --out "$b" "${extra[@]}" --shared-from "$a" 2>&1 | tee -a "$console"
done
echo "end=$(date -Iseconds)" | tee -a "$console"
