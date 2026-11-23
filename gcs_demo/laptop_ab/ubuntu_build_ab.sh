#!/usr/bin/env bash
# 方案 A／B 正式 UI 編譯（Ubuntu 編譯筆電）：全新副本 -> MVP 安裝（UI agent＋插槽＋AiAlerts＋AiMission）-> AiAgent（寫死 A 或 B）-> 離線 CMake 編譯。
#   bash gcs_demo/laptop_ab/ubuntu_build_ab.sh <A|B> <正式UI來源> <新的副本路徑（不可已存在）>
# 例：bash gcs_demo/laptop_ab/ubuntu_build_ab.sh A ~/ELAN_GCP_ui ~/mvp_build/ELAN_GCP_ui_ab_A
# 不啟動 UI、模型或服務；不下載；不刪舊 build；正式 UI 原始資料夾只讀。
# MVP 那一層固定用 commit 5f5c3ca 的檔案（你筆電上 MVP 編譯成功的版本）：git archive 匯出到旁邊的新資料夾再執行，
# 因為這個分支的 GcpAgentCore.js 有 ADR-0002 D-13 修改，和 UI agent 安裝器的雜湊清冊不同；工作目錄不動。
# 編譯環境預設值和 ui_agent/mvp/ubuntu_build_mvp.sh 相同（QT_PREFIX、CMAKE、CPM_CACHE_SRC、LIBEVENTS_SOURCE、JOBS 可覆寫）。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(cd -- "$HERE/../.." && pwd -P)"
MVP_COMMIT=5f5c3ca
[[ $# == 3 && "$1" =~ ^[AB]$ ]] || { echo 'usage: bash ubuntu_build_ab.sh <A|B> <source-UI> <new-copy-path>' >&2; exit 2; }
PLAN="$1"
PORT=$([[ "$PLAN" == A ]] && echo 8767 || echo 8768)
SRC="$(cd -- "$2" && pwd -P)"
DST="$(realpath -m -- "$3")"
INST="$DST.mvp_installer_$MVP_COMMIT"
QT_PREFIX="${QT_PREFIX:-$HOME/Qt/6.8.3/gcc_64}"
CMAKE="${CMAKE:-$HOME/qgc-aqt-env/bin/cmake}"
CPM_CACHE_SRC="${CPM_CACHE_SRC:-$HOME/elan_agent_v5/build/cpm_modules}"
LIBEVENTS_SOURCE="${LIBEVENTS_SOURCE:-$HOME/qgroundcontrol-v5/build/cpm_modules/libevents/1ea2d34e1cc3658140fb45034b187e87d60c899b}"
JOBS="${JOBS:-4}"

fail() { echo "STOP: $*" >&2; exit 2; }
for tool in realpath rsync tee ninja sha256sum git tar; do command -v "$tool" >/dev/null || fail "missing tool: $tool"; done
[[ "$DST" != / && "$DST" != "$SRC" && "$DST" != "$SRC/"* && "$SRC" != "$DST/"* ]] || fail 'destination must be separate from the source UI'
[[ ! -e "$DST" && ! -L "$DST" && ! -e "$INST" ]] || fail "destination already exists: $DST (each build uses a new folder)"
[[ -f "$SRC/GCP/GcpMainShell.qml" && ! -e "$SRC/GCP/Agent" ]] || fail 'source must be an uninstalled formal UI tree'
[[ -d "$QT_PREFIX/lib/cmake/Qt6" ]] || fail "Qt not found: $QT_PREFIX"
[[ -x "$CMAKE" ]] || fail "CMake not found: $CMAKE"
CM_VERSION="$("$CMAKE" --version | head -1)"
[[ "$CM_VERSION" =~ ([0-9]+)\.([0-9]+) ]] && (( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 25) )) || fail "CMake >= 3.25 required, got: $CM_VERSION"
[[ -d "$CPM_CACHE_SRC" ]] || fail "dependency cache not found: $CPM_CACHE_SRC"
[[ -f "$LIBEVENTS_SOURCE/libs/cpp/protocol/receive.h" ]] || fail "libevents source not found: $LIBEVENTS_SOURCE"
[[ "$JOBS" =~ ^[1-9][0-9]?$ ]] || fail 'JOBS must be 1..99'
git -C "$REPO" cat-file -e "$MVP_COMMIT^{commit}" || fail "commit $MVP_COMMIT not in this clone (git fetch first)"
[[ -z "$(git -C "$REPO" status --porcelain -- gcs_demo/laptop_ab)" ]] || fail 'gcs_demo/laptop_ab has uncommitted changes'

mkdir -- "$DST"
LOG="$DST/ab_build_logs"; mkdir -- "$LOG"
{
    echo "started=$(date -Iseconds)"; echo "plan=$PLAN"; echo "agent_port=$PORT"
    echo "repo_head=$(git -C "$REPO" rev-parse HEAD)"; echo "mvp_installer_commit=$(git -C "$REPO" rev-parse "$MVP_COMMIT")"
    echo "source_ui=$SRC"; echo "qt=$QT_PREFIX"; echo "cmake=$CMAKE ($CM_VERSION)"
    echo "cpm_cache_src=$CPM_CACHE_SRC"; echo "libevents=$LIBEVENTS_SOURCE"; echo "jobs=$JOBS"
} > "$LOG/build_info.txt"

echo "[1/6] export MVP installer files from $MVP_COMMIT -> $INST ..."
mkdir -- "$INST"
git -C "$REPO" archive "$MVP_COMMIT" ui_agent gcs_demo/qml gcs_demo/alerts/qml | tar -x -C "$INST"
echo '[2/6] copy formal UI (read-only source) ...'
rsync -a --exclude='/.git' --exclude='/build*/' --exclude='/.ui-agent-*' --exclude='/.mvp-install*' --exclude='/.ab-install*' -- "$SRC/" "$DST/"
echo '[3/6] MVP installer (dry run, then install) ...'
bash "$INST/ui_agent/mvp/install_mvp_into_ui.sh" --check "$DST" 2>&1 | tee "$LOG/1_install_mvp_check.log"
bash "$INST/ui_agent/mvp/install_mvp_into_ui.sh" "$DST" 2>&1 | tee "$LOG/2_install_mvp.log"
echo "[4/6] AiAgent plugin (plan $PLAN, agent port $PORT) ..."
bash "$HERE/install_ab_into_ui.sh" "$PLAN" "$PORT" "$DST" 2>&1 | tee "$LOG/3_install_ab.log"
echo '      local git snapshot of the copy (QGC version scripts need git; source UI untouched) ...'
[[ ! -e "$DST/.git" ]] || fail "copy already has .git: $DST/.git"
{ git -C "$DST" init -q && echo '/ab_build_logs/' >> "$DST/.git/info/exclude" && git -C "$DST" add -A \
  && git -C "$DST" -c user.name=ab-build -c user.email=ab-build@localhost -c commit.gpgsign=false \
       commit -q -m "A/B build snapshot (local only)" && git -C "$DST" describe --always --tags; } 2>&1 | tee "$LOG/3b_git_snapshot.log"
echo '[5/6] configure (offline) ...'
cp -a -- "$CPM_CACHE_SRC" "$DST/build-ab-cpm-cache"
mapfile -t GEO < <(find "$DST/build-ab-cpm-cache/geographiclib" -mindepth 1 -maxdepth 1 -type d)
[[ ${#GEO[@]} == 1 ]] || fail "expected exactly one geographiclib folder in the cache, found ${#GEO[@]}"
echo "geographiclib=${GEO[0]}" >> "$LOG/build_info.txt"
"$CMAKE" -S "$DST" -B "$DST/build-ab" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug "-DCMAKE_PREFIX_PATH=$QT_PREFIX" "-DCMAKE_MAKE_PROGRAM=$(command -v ninja)" \
    "-DCPM_SOURCE_CACHE=$DST/build-ab-cpm-cache" "-DCPM_libevents_SOURCE=$LIBEVENTS_SOURCE" \
    "-DCPM_geographiclib_SOURCE=${GEO[0]}" \
    -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
    2>&1 | tee "$LOG/4_configure.log"
echo '[6/6] build ...'
"$CMAKE" --build "$DST/build-ab" --parallel "$JOBS" 2>&1 | tee "$LOG/5_build.log"
EXE="$(find "$DST/build-ab" -maxdepth 3 -type f -name QGroundControl -perm -u+x | head -1)"
{ echo "finished=$(date -Iseconds)"; echo "executable=${EXE:-NOT_FOUND}"; } >> "$LOG/build_info.txt"
[[ -n "$EXE" ]] || fail "build finished but no QGroundControl executable found; see $LOG/5_build.log"
echo "BUILD OK (plan $PLAN): $EXE"
echo "No application was launched. To open it: bash $HERE/run_ab_desktop.sh $PLAN $EXE --fake   (or --live <bundle> <hash8>)"
