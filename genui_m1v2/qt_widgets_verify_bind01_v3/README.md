# qt_widgets_verify_bind01_v3：W1～W5 轉接元件在 Qt 6.8.3 的畫面驗證（替身 GCP 模組）

v3：v2 全部元件沒載入（GenuiWidget 用相對檔名，Qt 從入口檔目錄找；元件改 bind-m1-0.1.1 用 Qt.resolvedUrl），collect 加判「No such file」等錯誤行，並加 near 情境（v2 的 long 情境本來就不會出 W4）。v2：v1 的 widgets_verify.qml 第 18 行屬性名稱用大寫 S，QML 載入失敗（v1 紀錄保留）；v2 改成 sd，另先跑 qmllint。只跑一次，輸出原樣保留。在本資料夾執行：

```
~/Qt/6.8.3/gcc_64/bin/qmllint -I ../test/qt_stub -I ../qml/widgets ../qml/widgets/*.qml ../test/qt_stub/QGroundControl/GCP/*.qml widgets_verify.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 90 ~/Qt/6.8.3/gcc_64/bin/qml -I ../test/qt_stub widgets_verify.qml > w_raw.txt 2>&1; echo "exit=$?" >> w_raw.txt
fc-list :lang=zh family >> fonts.txt 2>&1; echo "exit=$?" >> fonts.txt
python3 collect_w.py w_raw.txt w.json > compare_w.txt; echo "exit=$?" >> compare_w.txt
```

- qmllint 只記錄、不擋（替身模組的型別資訊不完整，可能有假警告）；之後判讀。
- 判定：每個框都載入、ok、沒有 overflow；W2 重畫 ≤ 3 次；18 張截圖都存；沒有 qml 錯誤或警告。
- 中文字型：替身主題用 "Noto Sans CJK TC"；fonts.txt 列出筆電有哪些中文字型。請人眼看截圖有沒有方塊字。
- 不驗：正式 GCP 原檔的外觀（替身模組只有允許清單的屬性）。正式原檔整合另做。
