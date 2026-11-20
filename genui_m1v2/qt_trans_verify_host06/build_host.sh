#!/bin/bash
# 編譯小主程式。只用筆電上已有的工具；缺 cmake／編譯器就停（不安裝、不下載）。
# 用法：bash build_host.sh <make_host_src.sh 的輸出目錄> <建置目錄（必須不存在）>
set -u
S="$1"; B="$2"; QT=~/Qt/6.8.3/gcc_64
[ -e "$B" ] && { echo "$B already exists"; exit 3; }
CM=$(ls ~/Qt/Tools/CMake/bin/cmake 2>/dev/null || command -v cmake || true)
NJ=$(ls ~/Qt/Tools/Ninja/ninja 2>/dev/null || command -v ninja || true)
CXX=$(command -v g++ || command -v c++ || true)
echo "cmake=$CM ninja=$NJ cxx=$CXX"; [ -n "$CM" ] && "$CM" --version | head -1; [ -n "$CXX" ] && "$CXX" --version | head -1
[ -n "$CM" ] && [ -n "$CXX" ] || { echo "MISSING_TOOLS (not installing)"; exit 5; }
GEN=(); [ -n "$NJ" ] && GEN=(-G Ninja -DCMAKE_MAKE_PROGRAM="$NJ")
"$CM" -S "$S" -B "$B" "${GEN[@]}" -DCMAKE_PREFIX_PATH="$QT" -DCMAKE_BUILD_TYPE=Release || exit 6
"$CM" --build "$B" -j 4 || exit 7
ls -l "$B/genui_host" && sha256sum "$B/genui_host"
