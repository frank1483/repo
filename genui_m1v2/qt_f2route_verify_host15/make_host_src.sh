#!/bin/bash
# 從正式 UI 原檔（只讀）複製允許清單的 11 個 QML 檔與 FontLoader 用到的字型，組成小主程式的原始碼目錄（不改原檔、不進 repo）。
# 字型照 FontLoader 的 qrc 路徑放（qrc:/qml/QGroundControl/GCP/<相對路徑>），讓正式字型能載入。
# 用法：bash make_host_src.sh <ELAN_GCP_ui 路徑> <輸出目錄（必須不存在）> <本資料夾>
set -eu
R="$1"; SRC="$1/GCP"; OUT="$2"; KIT="$3"
[ -d "$SRC" ] || { echo "no $SRC"; exit 2; }
[ -e "$OUT" ] && { echo "$OUT already exists"; exit 3; }
mkdir -p "$OUT"
FILES="GcpTheme.qml GcpThemeColor.qml GcpThemeFont.qml GcpThemeRadius.qml GcpThemeSpacing.qml GcpThemeLayout.qml GcpThemeMotion.qml GcpThemeSwatches.qml Controls/GcpCard.qml Controls/GcpPanel.qml Controls/GcpTelemetryMetricCard.qml"
QML=""; SING=""
for f in $FILES; do
  b=$(basename "$f"); cp "$SRC/$f" "$OUT/$b"; QML="$QML $b"
  grep -q '^[[:space:]]*pragma[[:space:]]\+Singleton' "$OUT/$b" && SING="$SING $b"
done
# FontLoader 來源：qrc:/qml/QGroundControl/GCP/... → 找原檔位置並照相對路徑複製
: > "$OUT/fonts_map.txt"; FONTS=""; MISS=0
for u in $(grep -ohE 'qrc:/qml/QGroundControl/GCP/[^"]+' "$OUT"/*.qml | sort -u); do
  rel=${u#qrc:/qml/QGroundControl/GCP/}
  if [ -f "$SRC/$rel" ]; then from="$SRC/$rel"; else from=$(find "$R" -type f -name "$(basename "$rel")" | head -1); fi
  if [ -n "$from" ] && [ -f "$from" ]; then mkdir -p "$OUT/$(dirname "$rel")"; cp "$from" "$OUT/$rel"; FONTS="$FONTS $rel"; echo "OK $rel <- ${from#$R/}" >> "$OUT/fonts_map.txt"
  else echo "MISSING $rel" >> "$OUT/fonts_map.txt"; MISS=$((MISS+1)); fi
done
cp "$KIT/main.cpp" "$OUT/main.cpp"
{
  echo 'cmake_minimum_required(VERSION 3.21)'
  echo 'project(genui_host LANGUAGES CXX)'
  echo 'find_package(Qt6 6.8 REQUIRED COMPONENTS Gui Qml Quick)'
  echo 'qt_standard_project_setup(REQUIRES 6.8)'
  echo 'qt_add_executable(genui_host main.cpp)'
  [ -n "$SING" ] && echo "set_source_files_properties($SING PROPERTIES QT_QML_SINGLETON_TYPE TRUE)"
  echo "qt_add_qml_module(genui_host URI QGroundControl.GCP VERSION 1.0 RESOURCE_PREFIX /qml NO_CACHEGEN NO_LINT"
  echo "  QML_FILES $QML"
  [ -n "$FONTS" ] && echo "  RESOURCES $FONTS"
  echo ')'
  echo 'target_link_libraries(genui_host PRIVATE Qt6::Gui Qt6::Qml Qt6::Quick)'
} > "$OUT/CMakeLists.txt"
grep -ohE '\bGcp[A-Z][A-Za-z]+\b' "$OUT"/*.qml | sort -u > "$OUT/referenced_types.txt"
(cd "$OUT" && find . -type f ! -name SRC.sha256 -print0 | sort -z | xargs -0 sha256sum > SRC.sha256)
cat "$OUT/fonts_map.txt"; echo "singletons:$SING"; echo "missing_fonts=$MISS"
[ "$MISS" -eq 0 ] || exit 4
