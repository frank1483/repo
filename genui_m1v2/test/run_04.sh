#!/bin/bash
# 0.4 正式執行：每個測試只跑一次，輸出原樣存進 runs/m1v2_04_run1_20261118/
set -u
cd "$(dirname "$0")/.."
D=runs/m1v2_04_run1_20261118
mkdir "$D" || exit 1
git rev-parse HEAD > "$D/COMMIT.txt"; node --version > "$D/ENV.txt"; python3 --version >> "$D/ENV.txt"
for t in test_v4.js test_blocks_v2.js; do node test/$t > "$D/$t.txt" 2>&1; echo "rc=$?" >> "$D/$t.txt"; done
python3 -I test/test_eval_host_v2.py > "$D/test_eval_host_v2.txt" 2>&1; echo "rc=$?" >> "$D/test_eval_host_v2.txt"
for v in vectors_v2.json vectors_v3.json vectors_v4.json vectors_v5.json; do
  b=${v%.json}
  node golden/run_js.js $v > "$D/js_$b.json" 2> "$D/js_$b.err"
  python3 -I golden/reference.py $v > "$D/py_$b.json" 2> "$D/py_$b.err"
  python3 -I golden/compare.py "$D/js_$b.json" "$D/py_$b.json" > "$D/compare_$b.txt" 2>&1; echo "rc=$?" >> "$D/compare_$b.txt"
  for side in js py; do python3 -I golden/check_expect_v2.py golden/$v "$D/${side}_$b.json" golden/expect_overrides_v3v4_for_0.4.json > "$D/expect_${side}_$b.txt" 2>&1; echo "rc=$?" >> "$D/expect_${side}_$b.txt"; done
done
cd "$D" && sha256sum * > SHA256SUMS
