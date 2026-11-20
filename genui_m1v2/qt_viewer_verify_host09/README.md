# qt_viewer_verify_host09：「查看手冊引文」視窗（viewer-m1-0.1、skel-m1-0.3）

依引文視窗說明 v1（使用者 11/21 03:08「引文視窗照建議」）§8。小主程式與 host01～08 相同做法；offscreen 即可（不需要模糊）。
限制：offscreen 沒有真的滑鼠點擊與按鍵，開啟用骨架點擊區呼叫的同一個函式 openViewer()，返回鍵用視窗的 backPressed()、按鈕用 closeRequested("button")。
截圖含正式 UI 外觀，只放 PC。只跑一次，輸出原樣保留。在本資料夾執行：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host09_20261121; B=~/genui_host_build_host09_20261121
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
~/Qt/6.8.3/gcc_64/bin/qmllint -I "$B" -I ../qml/widgets -I ../qml/skeleton viewer_verify.qml ../qml/skeleton/*.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
QT_QPA_PLATFORM=offscreen timeout 90 "$B/genui_host" "$PWD/viewer_verify.qml" > v_raw.txt 2>&1; echo "exit=$?" >> v_raw.txt
python3 collect_v.py v_raw.txt v.json > compare_v.txt; echo "exit=$?" >> compare_v.txt
```
make_src 或 build 失敗就停；lint 只記錄。修正另開 host10。
