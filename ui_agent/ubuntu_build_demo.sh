#!/usr/bin/env bash
# 在 Ubuntu（已裝 Qt 6.8.3 的那台）一次做完：開 UI 副本（git worktree）→ 裝 agent → 編 Linux 桌面版。
# 用法：./ubuntu_build_demo.sh <原 ELAN_GCP_ui 路徑> [副本路徑]
# 原目錄不會被修改：是 git repo 就用 worktree（分支 ui-agent-demo），不是就整份複製到副本再 git init 做基準。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "${1:?請給原 ELAN_GCP_ui repo 路徑}" && pwd)"
DST="${2:-$SRC/../ELAN_GCP_ui_agent}"

if [ ! -d "$DST" ]; then
    if git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$SRC" worktree add "$DST" -b ui-agent-demo
    else
        mkdir -p "$DST"
        rsync -a --exclude 'build*/' --exclude '.git/' "$SRC"/ "$DST"/
        git -C "$DST" init -q
        git -C "$DST" add -A
        git -C "$DST" -c user.name=ui-agent -c user.email=ui-agent@local commit -qm "原始 UI 副本（裝 agent 前）"
    fi
fi
DST="$(cd "$DST" && pwd)"
[ -d "$DST/GCP/Agent" ] || "$HERE/install_into_ui.sh" "$DST"

# 沿用原 repo 桌面版 build 的 Qt 路徑
QT_PREFIX="${QT_PREFIX:-}"
if [ -z "$QT_PREFIX" ] && [ -f "$SRC/build/CMakeCache.txt" ]; then
    QT_PREFIX="$(sed -n 's/^Qt6_DIR:[A-Z]*=\(.*\)\/lib\/cmake\/Qt6$/\1/p' "$SRC/build/CMakeCache.txt" | head -1)"
fi
[ -n "$QT_PREFIX" ] || { [ -d "$HOME/Qt/6.8.3/gcc_64" ] && QT_PREFIX="$HOME/Qt/6.8.3/gcc_64"; }
[ -n "$QT_PREFIX" ] || { echo "找不到 Qt 路徑，請設定 QT_PREFIX=<Qt 6.8.3 gcc_64 路徑> 再執行"; exit 1; }
echo "Qt：$QT_PREFIX"

# 專案需要 CMake ≥ 3.25；系統版太舊時改用已知位置的新版（例如 ~/qgc-aqt-env/bin）
for d in "$HOME/qgc-aqt-env/bin" "$HOME/.local/bin" /opt/cmake/bin; do
    [ -x "$d/cmake" ] && "$d/cmake" --version | head -1 | grep -qE ' 3\.(2[5-9]|[3-9][0-9])|  ?[4-9]\.' && { export PATH="$d:$PATH"; break; }
done
echo "CMake：$(cmake --version | head -1)"

cd "$DST"
[ -f build/CMakeCache.txt ] || cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_PREFIX_PATH="$QT_PREFIX"
cmake --build build --parallel 4 2>&1 | tee build_agent.log | tail -5
echo
echo "編譯完成。執行（不登入、規則模式）："
echo "  cd $DST && GCP_PREVIEW=MainShell GCS_LLM_BACKEND=none ./build/Debug/QGroundControl"
