# qt_verify_041b：在筆電 Qt 6.8.3 原生 qml 上驗 0.4.1b（JS 引擎）

不用 PySide6。只跑一次，輸出原樣保留。

```
cd <本資料夾>
QT_QPA_PLATFORM=offscreen ~/Qt/6.8.3/gcc_64/bin/qml verify.qml > qt_raw.txt 2>&1; echo "exit=$?" >> qt_raw.txt
~/Qt/6.8.3/gcc_64/bin/qml --version >> qt_raw.txt 2>&1
python3 collect_qt.py qt_raw.txt node.json qt.json > compare.txt; echo "exit=$?" >> compare.txt
```

- 需要整個 genui_m1v2 資料夾（verify.qml 用 ../qml/*.js）。
- node.json 是雲端 node 跑同一份 scenarios_v2.js 的期望值；diffs 0 才算通過。
- 涵蓋：能力檢查（NFKC、㐀、198/199 個 𠀀、穩定排序）、Gate 172 句、電量 50 例、飛行紀錄 7 例、手冊 12 例（vectors v3～v6）、K-6 計畫／排版（含 trusted、NO_TRUSTED、請求 ID 不符、竄改）、claims 固定句、同時間告警排序、contentTerms、checkApply。
- 不含 GUI 畫面；GUI 另行驗證。
