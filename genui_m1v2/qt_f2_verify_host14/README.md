# qt_f2_verify_host14：F2 偏離航線距離在筆電 Qt JS 引擎上的逐位比對

依 F2 說明 v1（f2_deviation_v1，使用者 11/21 03:08 裁決）§6 驗證計畫：雲端 node 14 個手算案例全過、與 Python 參考實作逐位相同；本包在筆電 Qt 6.8.3 的 JS 引擎上跑同一組輸入，
和 node 輸出（expected_js.json）逐位比對，另查回答句。只用 QtQuick，不碰正式 UI；沿用 host13 已編好的小主程式（只讀使用，不重編）。只跑一次，輸出原樣保留。輸入 f2_cases_data.js 由 test/f2_cases.js 轉出。在本資料夾執行：

```
B=~/genui_host_build_host13_20261121
test -x "$B/genui_host" || { echo "host13 build missing: stop"; exit 8; }
QT_QPA_PLATFORM=offscreen timeout 60 "$B/genui_host" "$PWD/f2_verify.qml" > f2_raw.txt 2>&1; echo "exit=$?" >> f2_raw.txt
python3 collect_f2.py f2_raw.txt f2.json > compare_f2.txt; echo "exit=$?" >> compare_f2.txt
```
沒有 host13 的 build 就停。修正另開 host15。
