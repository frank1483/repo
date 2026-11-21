# qt_f2route_verify_host15：F2 接進問答流程（gate-m1-0.5、tools-m1-0.6、claims-m1-0.6）筆電驗證

依「F2 接進問答流程說明 v2」§4（使用者 11/21 12:51、13:11 裁決）。雲端 test_f2_route_v1 69 項全過、Gate 既有 330 句結果不變。
本包在筆電 Qt 上：33 句意圖判斷與 4 個情境（ok_record、explicit、deferred、mismatch）的結果要和 node（expected_node.json）逐項相同；
再看 4 個情境的工作區截圖（正式主題、1280×600）：W1 每行完整、成功情境 W1＋W2、無法取得只有 W1、deferred 的 W1 最後一行是「未查：飛行時間。請另外再問一次。」。
做法同 host13（重新產生 src／build，不沿用舊 build）。截圖含正式 UI 外觀，只放 PC。只跑一次，輸出原樣保留。在本資料夾執行：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host15_20261121; B=~/genui_host_build_host15_20261121
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
~/Qt/6.8.3/gcc_64/bin/qmllint -I "$B" -I ../qml/widgets -I ../qml/skeleton f2route_verify.qml ../qml/skeleton/*.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
grep -qE "Unexpected token|Expected token|SyntaxError" lint.txt && { echo "lint syntax error: stop"; exit 9; }
QT_QPA_PLATFORM=offscreen timeout 90 "$B/genui_host" "$PWD/f2route_verify.qml" > f2r_raw.txt 2>&1; echo "exit=$?" >> f2r_raw.txt
python3 collect_f2r.py f2r_raw.txt f2r.json > compare_f2r.txt; echo "exit=$?" >> compare_f2r.txt
```
make_src 或 build 失敗就停；lint 有語法錯誤（Unexpected／Expected token）就停；其他 lint 訊息只記錄。修正另開 host16。
