#!/bin/bash
# 從正式 UI 原檔（只讀）抽出允許清單的純 QML 檔，組成不含 C++ 的 QGroundControl.GCP 測試模組（使用者 11/19 Q3：只複製、不改、不進 repo）。
# 用法：bash make_real_module.sh <ELAN_GCP_ui 路徑> <輸出目錄（必須不存在）>
set -eu
SRC="$1/GCP"; OUT="$2/QGroundControl/GCP"
[ -d "$SRC" ] || { echo "no $SRC"; exit 2; }
[ -e "$2" ] && { echo "$2 already exists"; exit 3; }
mkdir -p "$OUT"
FILES="GcpTheme.qml GcpThemeColor.qml GcpThemeFont.qml GcpThemeRadius.qml GcpThemeSpacing.qml GcpThemeLayout.qml GcpThemeMotion.qml GcpThemeSwatches.qml Controls/GcpCard.qml Controls/GcpPanel.qml Controls/GcpTelemetryMetricCard.qml"
echo "module QGroundControl.GCP" > "$OUT/qmldir"
for f in $FILES; do
  b=$(basename "$f"); cp "$SRC/$f" "$OUT/$b"; t=${b%.qml}
  if grep -q '^[[:space:]]*pragma[[:space:]]\+Singleton' "$OUT/$b"; then echo "singleton $t 1.0 $b" >> "$OUT/qmldir"; else echo "$t 1.0 $b" >> "$OUT/qmldir"; fi
done
# 原檔若用到其他 GCP 型別（不在允許清單），列出來供判讀，不自動補
grep -ohE '\bGcp[A-Z][A-Za-z]+\b' "$OUT"/*.qml | sort -u > "$2/referenced_types.txt"
cd "$OUT" && sha256sum *.qml qmldir > "$2/MODULE.sha256"
cat "$OUT/qmldir"
