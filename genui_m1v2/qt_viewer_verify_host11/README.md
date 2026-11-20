# qt_viewer_verify_host11：引文視窗 viewer-m1-0.2（不透明、內容不壓標題列、驗真的捲動）

host10 run1：程式判定全過，但看圖有標題列半透明疊字、蓋到第一張卡；三段一屏放得下，捲動沒驗到。本包加這三項檢查與長內容情境。

## 沿用 host10：引文視窗重驗（host09 run1 驗證檔用了保留字 long，載入失敗，原樣保留）

## 沿用 host09：「查看手冊引文」視窗（viewer-m1-0.1、skel-m1-0.3）

依引文視窗說明 v1（使用者 11/21 03:08「引文視窗照建議」）§8。小主程式與 host01～08 相同做法；offscreen 即可（不需要模糊）。
限制：offscreen 沒有真的滑鼠點擊與按鍵，開啟用骨架點擊區呼叫的同一個函式 openViewer()，返回鍵用視窗的 backPressed()、按鈕用 closeRequested("button")。
截圖含正式 UI 外觀，只放 PC。只跑一次，輸出原樣保留。在本資料夾執行：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host11_20261121; B=~/genui_host_build_host11_20261121
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
~/Qt/6.8.3/gcc_64/bin/qmllint -I "$B" -I ../qml/widgets -I ../qml/skeleton viewer_verify.qml ../qml/skeleton/*.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
grep -qE "Unexpected token|Expected token|SyntaxError" lint.txt && { echo "lint syntax error: stop"; exit 9; }
QT_QPA_PLATFORM=offscreen timeout 90 "$B/genui_host" "$PWD/viewer_verify.qml" > v_raw.txt 2>&1; echo "exit=$?" >> v_raw.txt
python3 collect_v.py v_raw.txt v.json > compare_v.txt; echo "exit=$?" >> compare_v.txt
```
make_src 或 build 失敗就停；lint 有語法錯誤（Unexpected／Expected token）就停；其他 lint 訊息只記錄。修正另開 host12。
