# qt_gui_verify_041b：0.4.1b 排版在 Qt 6.8.3 QtQuick 場景的畫面驗證

筆電無螢幕，用 offscreen＋software 繪製。只跑一次，輸出原樣保留。在本資料夾執行：

```
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 60 ~/Qt/6.8.3/gcc_64/bin/qml gui_verify.qml > gui_raw.txt 2>&1; echo "exit=$?" >> gui_raw.txt
QT_QPA_PLATFORM=offscreen ~/Qt/6.8.3/gcc_64/bin/qml --version >> gui_raw.txt 2>&1
python3 collect_gui.py gui_raw.txt expect_gui.json gui.json > compare_gui.txt; echo "exit=$?" >> compare_gui.txt
```

- 驗：6 種工作區高度（1080/600/500/400/200/120）下，引擎矩形和 node 相同；QtQuick 實際擺出的元件位置、大小與矩形相同；不超出工作區、不重疊；各存一張截圖 shot_<高度>.png。
- 不驗：正式 GenUI 元件外觀（W1～W5 包裝元件尚未做），這裡用標示框代替。
- 輸出檔：gui_raw.txt、gui.json、compare_gui.txt、shot_*.png（6 張）。
