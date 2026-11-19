#!/bin/sh
# W 元件 run1：node 單元測試＋靜態檢查，各一次。用法：sh test/run_bind1.sh runs/<目錄>
out="$1"; mkdir -p "$out"; cd "$(dirname "$0")/.."
git rev-parse HEAD > "$out/COMMIT"
node test/test_bind_v1.js > "$out/test_bind_v1.txt" 2>&1; echo "exit=$?" >> "$out/test_bind_v1.txt"
python3 test/check_widgets.py > "$out/check_widgets.txt" 2>&1; echo "exit=$?" >> "$out/check_widgets.txt"
sha256sum qml/GenuiBind.js qml/widgets/*.qml test/test_bind_v1.js test/check_widgets.py > "$out/SHA256SUMS"
