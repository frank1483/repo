# qt_widgets_verify_real02：W1～W5 改用正式 GCP 原檔（允許清單的純 QML 檔）在 Qt 6.8.3 的畫面驗證

real02（bind-m1-0.3）：real01 看圖不及格（W 元件直接用各頁專用的大字級，重疊、裁切），元件改用通用級距；檢查程式加文字幾何判定（每個文字物件不得超出框、彼此不得重疊、不得被裁切；被「…」省略只記錄），並把「Cannot load」算進警告。real01：情境、判定與 bind03 相同（bind-m1-0.2.2），只把替身模組換成從正式原檔抽出的 GcpTheme*、GcpCard、GcpPanel、GcpTelemetryMetricCard。
正式 QGroundControl.GCP 是含 C++ 的靜態模組，不能直接 -I 載入；這裡只抽允許清單的純 QML 檔、手寫 qmldir（make_real_module.sh），原檔不改、不進 repo。
GcpTelemetryChartPanel 不抽（用到 QGC 的 unitsConversion；W2 本來就是精簡版）。字型 FontLoader 若指向程式內資源可能載不到，會出現在 qml 警告裡，照實判讀。
只跑一次，輸出原樣保留。在本資料夾執行（R=正式原檔，M=新的模組目錄）：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; M=~/gcp_real_module_real02_20261120
bash make_real_module.sh "$R" "$M" > make_module.txt 2>&1; echo "exit=$?" >> make_module.txt
~/Qt/6.8.3/gcc_64/bin/qmllint -I "$M" -I ../qml/widgets ../qml/widgets/*.qml widgets_verify.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 90 ~/Qt/6.8.3/gcc_64/bin/qml -I "$M" widgets_verify.qml > w_raw.txt 2>&1; echo "exit=$?" >> w_raw.txt
python3 collect_w.py w_raw.txt w.json > compare_w.txt; echo "exit=$?" >> compare_w.txt
cp "$M/referenced_types.txt" "$M/MODULE.sha256" .
```


- qmllint 只記錄、不擋（替身模組的型別資訊不完整，可能有假警告）；之後判讀。
- 判定：每個框都載入、ok、沒有 overflow；W2 重畫 ≤ 3 次；18 張截圖都存；沒有 qml 錯誤或警告。
- 中文字型：替身主題用 "Noto Sans CJK TC"；fonts.txt 列出筆電有哪些中文字型。請人眼看截圖有沒有方塊字。
- 不驗：正式 GCP 原檔的外觀（替身模組只有允許清單的屬性）。正式原檔整合另做。
