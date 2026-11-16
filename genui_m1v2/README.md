# GenUI m1v2（探索，genui_m1 的下一版）

狀態：**探索**。舊版 `genui_m1/` 與它的 run 紀錄都不動。ADR-0001 仍是 Proposed；不接真模型。

依據：契約附件 v3（使用者已確認 V3-1～V3-9）、附件 v3.1 草案（未確認，只有 §K-3' 手冊引用的確認範圍由使用者 2026-11-16 12:48 裁決）、Codex 補核 run2a／run2b。

## 和 genui_m1 的差異

| 檔案 | 改了什麼 | 對應 |
|---|---|---|
| `qml/GenuiGate.js` | 能力檢查（無 NFKC 或碼位走訪就不啟用）；中文範圍含擴充字；子句只用標點、換行、多字連接詞切；逐一看飛控動詞是不是被問；規則 11 只取正分類別（`CLARIFY_ONE`）；Router 回傳 `omitted_tools` | v3.1 §A'；C-01、C-02；V3-F01、F02 |
| `qml/GenuiTools.js` | 電量：W 固定、保留值 0～100 含 100 且一律判定、過期與樣本不足都記、ETA 原因、邊界容差、輸出可畫序列 F3 與截距；飛行紀錄：同時戳保留到達順序、依時間等分 150 桶；手冊：排名前去重、內容詞過半才合格 | v3 §C、§L-3；v3.1 §C'、§D-6'、§L'；C-03～C-06、C-09、C-11 |
| `qml/GenuiClaims.js` | 每工具一句合併狀態句；「本次未執行」固定句；PARTIAL 0 筆計數句；`T-ETA-NA`；飛行紀錄措辭「該趟紀錄中」；截斷告知文字 | v3 §D-7；v3.1 §D-3'、§D-7'；C-07、C-08 |
| `qml/GenuiLayout.js` | binding_ref `{request_id, kind, ref}`；驗證器只看自有屬性、每種元件一個、編號依序、依資料重算 priority／required、需要資料才驗 | v3.1 §K-2'、§K-2''；C-10 |
| `golden/` | Python 對照版同步修改；比對器分清布林與數字；`vectors_v3.json` 用 Codex 列的確切輸入，預期值先寫好，`check_expect.py` 讓兩版各自比 | C-12～C-14 |
| `test/test_v2.js` | Gate、答案句、排版與驗證的固定案例 | Codex run2b §4-4～4-6、K-6 |

## 執行

```
node genui_m1v2/test/test_v2.js
node genui_m1v2/golden/run_js.js vectors_v3.json > js.json
python3 -I genui_m1v2/golden/reference.py vectors_v3.json > py.json
python3 -I genui_m1v2/golden/compare.py js.json py.json
python3 -I genui_m1v2/golden/check_expect.py genui_m1v2/golden/vectors_v3.json js.json   # py.json 也一樣
```

## 還沒做

- 沒在 QJSEngine 載入過；能力檢查與擴充字長度要在 Qt 上再驗。
- 畫面超支（§I）、交易提交點（§E'）、更新租約（§M）、Ollama 停止證據（§J）、告警計分（§F）都還沒有程式。
- 飛行紀錄的分頁、ROUTE、PROFILE、DEVIATION operation 未做。
- 手冊合格門檻 0.5、20% 是候選值〔待凍結〕。

## 0.3（2026-11-16 13:19 之後）

- Gate：T=1（calibration_v1 A1 凍結值）。
- 電量：使用者裁決 V3.1-2，R² 門檻 0.8、相鄰兩筆變化超過 5% 視窗重新起算（`detail.jump_at`）。
- 新增 `golden/vectors_v4.json`（跳變與 R² 案例）、`golden/expect_overrides_v3_for_0.3.json`（E18 因 R² 門檻改變而更新預期）、`test/test_v3.js`。
