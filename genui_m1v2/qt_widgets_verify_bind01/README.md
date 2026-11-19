# qt_widgets_verify_bind01：W1～W5 轉接元件在 Qt 6.8.3 的畫面驗證（替身 GCP 模組）

只跑一次，輸出原樣保留。在本資料夾執行：

```
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 90 ~/Qt/6.8.3/gcc_64/bin/qml -I ../test/qt_stub widgets_verify.qml > w_raw.txt 2>&1; echo "exit=$?" >> w_raw.txt
fc-list :lang=zh family >> fonts.txt 2>&1; echo "exit=$?" >> fonts.txt
python3 collect_w.py w_raw.txt w.json > compare_w.txt; echo "exit=$?" >> compare_w.txt
```

- 判定：每個框都載入、ok、沒有 overflow；W2 重畫 ≤ 3 次；12 張截圖都存；沒有 qml 錯誤或警告。
- 中文字型：替身主題用 "Noto Sans CJK TC"；fonts.txt 列出筆電有哪些中文字型。請人眼看截圖有沒有方塊字。
- 不驗：正式 GCP 原檔的外觀（替身模組只有允許清單的屬性）。正式原檔整合另做。
