#!/bin/bash
# bind-m1-0.2.1／layout-m1-0.4 正式執行（0.2 run1 一項失敗保留）：每個測試只跑一次，輸出原樣存進 runs/bind021_run1_20261120/
set -u
cd "$(dirname "$0")/.."
D="$PWD/runs/bind021_run1_20261120"
mkdir "$D" || exit 1
git rev-parse HEAD > "$D/COMMIT.txt"; node --version > "$D/ENV.txt"; python3 --version >> "$D/ENV.txt"
for t in test_v5.js test_blocks_v2.js test_bind_v2.js test_trans_v1.js; do node test/$t > "$D/$t.txt" 2>&1; echo "rc=$?" >> "$D/$t.txt"; done
python3 -I test/check_widgets.py > "$D/check_widgets.txt" 2>&1; echo "rc=$?" >> "$D/check_widgets.txt"
sha256sum qml/*.js qml/widgets/*.qml test/test_v5.js test/test_bind_v2.js > "$D/SOURCES.sha256"
cd "$D" && sha256sum *.txt > SHA256SUMS
