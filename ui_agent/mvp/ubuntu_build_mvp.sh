#!/usr/bin/env bash
# MVP 桌面版編譯（Ubuntu 編譯筆電）：全新副本 -> 安裝 UI agent＋插槽＋外掛 -> 離線 CMake 編譯。
# 不啟動 UI、模型或任何服務；不下載；不刪舊 build；正式 UI 原始資料夾只讀。
#   bash ui_agent/mvp/ubuntu_build_mvp.sh <正式UI來源> <新的副本路徑（不可已存在）>
# 預設值（編譯筆電 192.168.50.40，2026-11-13 唯讀檢查結果），都可用環境變數覆寫：
#   QT_PREFIX         ~/Qt/6.8.3/gcc_64
#   CMAKE             ~/qgc-aqt-env/bin/cmake（3.30.9；系統的 3.22.1 太舊）
#   CPM_CACHE_SRC     ~/elan_agent_v5/build/cpm_modules（v5 編譯成功時的相依套件快取；複製一份來用，不改原本的）
#   LIBEVENTS_SOURCE  ~/qgroundcontrol-v5/build/cpm_modules/libevents/1ea2d34e1cc3658140fb45034b187e87d60c899b
#   JOBS              4
# v2 (2026-11-13, after build1 failed at configure): the formal UI source has no .git, but QGC's cmake/Git.cmake
# needs git output, so the copy gets its own throwaway local git repo (one commit; nothing is pushed anywhere).
# geographiclib: CPM's cache hash includes the absolute PATCHES path, so the v5 cache folder (already patched) is
# passed explicitly with CPM_geographiclib_SOURCE.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
[[ $# == 2 ]] || { echo 'usage: bash ubuntu_build_mvp.sh <source-UI> <new-copy-path>' >&2; exit 2; }
SRC="$(cd -- "$1" && pwd -P)"
DST="$(realpath -m -- "$2")"
QT_PREFIX="${QT_PREFIX:-$HOME/Qt/6.8.3/gcc_64}"
CMAKE="${CMAKE:-$HOME/qgc-aqt-env/bin/cmake}"
CPM_CACHE_SRC="${CPM_CACHE_SRC:-$HOME/elan_agent_v5/build/cpm_modules}"
LIBEVENTS_SOURCE="${LIBEVENTS_SOURCE:-$HOME/qgroundcontrol-v5/build/cpm_modules/libevents/1ea2d34e1cc3658140fb45034b187e87d60c899b}"
JOBS="${JOBS:-4}"

fail() { echo "STOP: $*" >&2; exit 2; }
for tool in realpath rsync tee ninja sha256sum git; do command -v "$tool" >/dev/null || fail "missing tool: $tool"; done
[[ "$DST" != / && "$DST" != "$SRC" && "$DST" != "$SRC/"* && "$SRC" != "$DST/"* ]] || fail 'destination must be separate from the source UI'
[[ ! -e "$DST" && ! -L "$DST" ]] || fail "destination already exists: $DST (each build uses a new folder)"
[[ -f "$SRC/GCP/GcpMainShell.qml" && ! -e "$SRC/GCP/Agent" ]] || fail 'source must be an uninstalled formal UI tree'
[[ -d "$QT_PREFIX/lib/cmake/Qt6" ]] || fail "Qt not found: $QT_PREFIX"
[[ -x "$CMAKE" ]] || fail "CMake not found: $CMAKE"
CM_VERSION="$("$CMAKE" --version | head -1)"
[[ "$CM_VERSION" =~ ([0-9]+)\.([0-9]+) ]] && (( BASH_REMATCH[1] > 3 || (BASH_REMATCH[1] == 3 && BASH_REMATCH[2] >= 25) )) || fail "CMake >= 3.25 required, got: $CM_VERSION"
[[ -d "$CPM_CACHE_SRC" ]] || fail "dependency cache not found: $CPM_CACHE_SRC"
[[ -f "$LIBEVENTS_SOURCE/libs/cpp/protocol/receive.h" ]] || fail "libevents source not found: $LIBEVENTS_SOURCE"
[[ "$JOBS" =~ ^[1-9][0-9]?$ ]] || fail 'JOBS must be 1..99'

mkdir -- "$DST"
LOG="$DST/mvp_build_logs"; mkdir -- "$LOG"
{
    echo "started=$(date -Iseconds)"
    echo "repo_head=$(git -C "$HERE/../.." rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "source_ui=$SRC"; echo "qt=$QT_PREFIX"; echo "cmake=$CMAKE ($CM_VERSION)"
    echo "cpm_cache_src=$CPM_CACHE_SRC"; echo "libevents=$LIBEVENTS_SOURCE"; echo "jobs=$JOBS"
} > "$LOG/build_info.txt"

echo '[1/5] copy formal UI (read-only source) ...'
rsync -a --exclude='/.git' --exclude='/build*/' --exclude='/.ui-agent-*' --exclude='/.mvp-install*' -- "$SRC/" "$DST/"
echo '[2/5] installer dry run ...'
bash "$HERE/install_mvp_into_ui.sh" --check "$DST" 2>&1 | tee "$LOG/1_install_check.log"
echo '[3/5] install UI agent + MVP slots + plugins into the copy ...'
bash "$HERE/install_mvp_into_ui.sh" "$DST" 2>&1 | tee "$LOG/2_install.log"
echo '      local git snapshot of the copy (QGC version scripts need git; source UI untouched) ...'
[[ ! -e "$DST/.git" ]] || fail "copy already has .git: $DST/.git"
{ git -C "$DST" init -q && git -C "$DST" add -A \
  && git -C "$DST" -c user.name=mvp-build -c user.email=mvp-build@localhost -c commit.gpgsign=false \
       commit -q -m "MVP build snapshot (local only)" && git -C "$DST" describe --always --tags; } 2>&1 | tee "$LOG/2b_git_snapshot.log"
echo '[4/5] configure (offline) ...'
cp -a -- "$CPM_CACHE_SRC" "$DST/build-mvp-cpm-cache"
mapfile -t GEO < <(find "$DST/build-mvp-cpm-cache/geographiclib" -mindepth 1 -maxdepth 1 -type d)
[[ ${#GEO[@]} == 1 ]] || fail "expected exactly one geographiclib folder in the cache, found ${#GEO[@]}"
echo "geographiclib=${GEO[0]}" >> "$LOG/build_info.txt"
"$CMAKE" -S "$DST" -B "$DST/build-mvp" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug "-DCMAKE_PREFIX_PATH=$QT_PREFIX" "-DCMAKE_MAKE_PROGRAM=$(command -v ninja)" \
    "-DCPM_SOURCE_CACHE=$DST/build-mvp-cpm-cache" "-DCPM_libevents_SOURCE=$LIBEVENTS_SOURCE" \
    "-DCPM_geographiclib_SOURCE=${GEO[0]}" \
    -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
    2>&1 | tee "$LOG/3_configure.log"
echo '[5/5] build ...'
"$CMAKE" --build "$DST/build-mvp" --parallel "$JOBS" 2>&1 | tee "$LOG/4_build.log"
EXE="$(find "$DST/build-mvp" -maxdepth 3 -type f -name QGroundControl -perm -u+x | head -1)"
{ echo "finished=$(date -Iseconds)"; echo "executable=${EXE:-NOT_FOUND}"; } >> "$LOG/build_info.txt"
[[ -n "$EXE" ]] || fail "build finished but no QGroundControl executable found; see $LOG/4_build.log"
echo "BUILD OK: $EXE"
echo "No application was launched. To open it: bash $HERE/run_mvp_desktop.sh $EXE"
