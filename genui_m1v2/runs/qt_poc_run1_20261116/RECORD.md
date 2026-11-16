# QJSEngine 載入 PoC 第 1 次（2026-11-16，雲端，PySide6 6.8.3＝筆電同版 Qt 6.8.3）

- 程式 commit 見 ENV.txt。只跑一次，輸出原樣保留（qt.json、node.json、compare.out）。
- **四個 `.pragma library` 檔都在 QML 裡載入成功**，沒有載入錯誤。
- 電量 29 案、K-6 排版 6 種高度、答案句、竄改檢查：Qt 與 node **完全相同**。
- **Gate 全部回 `GATE_CAPABILITY_FAIL`**：能力檢查不過，所以 169 句都沒判。

## 事後診斷（另跑小指令看引擎行為，沒有重跑 PoC）

| 寫法 | Qt 6.8.3 | node |
|---|---|---|
| `"Ａ".normalize("NFKC")` | A（正常） | A |
| `Array.from("𠀀").length` | **2**（按 UTF-16 切） | 1 |
| `[..."𠀀"].length`、`for…of` | 1（正常） | 1 |
| `Array.prototype.sort` 同值順序 | **不穩定** | 穩定 |

- 能力檢查發揮了作用：引擎的 `Array.from` 不照碼位切，Gate 拒絕啟用，而不是默默算錯長度。
- 修法：改用 `for…of` 走碼位；能力檢查改驗這個寫法。
- sort 不穩定：本版大部分排序已有明確的同值規則；`alertHistory` 只依時間排序，同一時間的告警順序在 Qt 上可能和 Python 不同，下一版補「同時間依到達順序」。
- 修正放下一版（gate-m1-0.2.1、tools-m1-0.2.2），新目錄 qt_poc_run2、m1v2_run3。
