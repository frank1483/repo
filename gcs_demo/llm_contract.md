# 三功能共用 LLM 介面（草案 v0，任務規劃串提出，2026-10-27 台灣時間 21:10）

目的：UI agent、智慧告警、任務規劃／任務報告三個 demo 最後共用同一個可抽換的輕量模型。
原則：演算法先算、先決定能不能做；模型只在演算法給的選項裡挑、或把已算好的事實寫成白話。模型掛掉時每個功能都要能用規則退回。

## 1. 後端（Python，標準庫即可）

```python
class LLMBackend:
    name: str
    def complete_json(self, system: str, user: str, schema: dict, timeout_s: float = 60) -> dict: ...
    # 回傳 {"ok": bool, "data": dict|None, "raw": str, "latency_s": float, "error": str|None}
```

實作三種，用環境變數切換，不改程式：

| GCS_LLM_BACKEND | 用途 | 其他變數 |
| --- | --- | --- |
| `openai`（預設） | vLLM / llama.cpp server / Ollama 的 `/v1/chat/completions`（實驗室 RTX6000 或 Genio 上的本機服務） | `GCS_LLM_URL`（例 http://127.0.0.1:8000/v1）、`GCS_LLM_MODEL` |
| `ollama` | Ollama 原生 `/api/chat`，`format=json` | 同上 |
| `none` | 不呼叫模型，全部走規則 | — |

固定 temperature=0、輸出 JSON。每次呼叫記錄 backend、model、prompt hash、原始回覆、延遲。

## 2. 共同決策格式（模型只能選 ID）

```json
{"decision": "SELECT|HOLD|CLARIFY", "choice_id": "C2", "reason_zh": "一句話", "evidence_ids": ["E3"]}
```

- 演算法提供 `candidates`（每個有 `id`、已算好的數字）與 `evidence`（每個有 `id`）。
- 模型回的 `choice_id` 不在清單、`evidence_ids` 引用不存在的證據 → 判無效，退回規則選擇。
- 模型輸出永遠是「建議」，畫面要使用者按確認才生效（UI 改版面也一樣，可復原）。

## 3. 文字生成（報告、告警說明）

`complete_json` 的 schema 為 `{"summary_zh": str, "suggestions": [{"text_zh": str, "evidence_ids": [..]}]}`；
每條建議必須引用演算法算出的 evidence id，沒有引用的句子丟掉。

程式位置：GitHub frank1483/repo 分支 `claude/project-thread-ovsufa` 的 `gcs_demo/llm.py`（任務規劃串先寫，其他兩串可直接 import 或複製）。

## 4. 補充（v0.1，UI agent 串意見）

APK 內的 QML 不能 import Python，所以共用介面以 **HTTP 層** 為準：同一個 OpenAI 相容 `/v1/chat/completions` 端點、同一份決策 JSON。Python 的 llm.py 與 QML 端各自實作。任務規劃／報告的演算法以本機 JSON API（`gcs_demo/server.py`）提供，QML 用 XMLHttpRequest 呼叫。

## 5. 補充（v0.2，UI agent 串提出，2026-10-28 台灣時間 15:25；任務規劃串同意）

- 決策 JSON 增加**選填**欄位 `steps: [{"choice_id": "…"}]`，最多 3 步；每個 ID 都必須在候選清單內，否則整份退回規則。只有一步時仍用 `choice_id`。使用者 10/28 同意 UI agent 可多步。
- 任務規劃／重規劃**不使用** `steps`：一次只選一個候選（或 HOLD）；若模型回了 `steps`，任務規劃端忽略它，只看 `choice_id`。
- 呼叫端可送 `response_format: {"type":"json_schema", ...}`（候選 ID 做成 enum）；伺服器不支援時退回 `json_object`。現有的 Python `llm.py` 不需更改，向下相容。

## 6. 補充（v0.3，「讓 MVP Demo 實際搭載 LLM」串，使用者 2026-11-02 21:27 台灣時間勾選同意）

- Demo 定位為 MVP：各功能**預設要接模型**（不再預設 `none`），連不到模型才退回規則，畫面標示「模型／規則」。
- 所有功能改連**共用 LLM 閘道** `gcs_demo/llm_gateway.py`（分支 `claude/project-thread-wum8aq`），只改網址：
  - Python：`GCS_LLM_BACKEND=openai`、`GCS_LLM_URL=http://127.0.0.1:8090/f/<功能>/v1`、`GCS_LLM_MODEL=gemma4:e2b`
  - QML UI agent：openai 模式，網址 `http://127.0.0.1:8090/f/ui/v1`
  - `<功能>` = `ui | alerts | mission | report | recognition`
- 閘道單一佇列，優先順序（使用者定）：**UI > 告警 > 任務規劃 > 報告 > 辨識切換**；進行中的呼叫不中斷。
- 逾時預算（秒，含排隊）：ui 20、alerts 30、mission 60、report 90、recognition 30；排隊超時回 504、不送模型，功能端退回規則。
- 閘道一律 temperature 0、think:false、要求 JSON（有 json_schema 就交給 Ollama format）；每次呼叫寫一行 JSONL（功能、排隊秒數、模型秒數、prompt hash、原始回覆全文、錯誤）。
- 告警：**分級一律由演算法先出**（為達 <2 秒），模型說明與建議非同步後補。
- 換到 Genio 520 板上推論時，只換閘道上游（`GCS_GATEWAY_UPSTREAM=openai` 接 llama-server 等），功能端不改。

## 7. 補充（v0.4，閘道期限／取消契約，2026-11-06 台灣時間；因 Codex 指出 ui 20 s 預算與 HTTP 等待 25 s 不一致）

- **有效期限** = min(功能預算, 呼叫端標頭 `X-GCS-Deadline-Ms`)。呼叫端只能縮短、不能放寬；無效值（非數字、≤0、NaN）忽略。功能預算不變：ui 20 s、alerts 30、mission 60、report 90、recognition 30。
- **回應時間**：閘道最晚在有效期限送出 HTTP 回應（移除舊的「預算＋5 秒」），逾時回 `504`、`error.type = "deadline"`。
- **取消**：期限到或呼叫端斷線 → 還在排隊的不送模型（紀錄 `expired in queue` 或 `cancelled before start: client_gone`）；已送出的由閘道**強制關閉上游連線**（計時器 shutdown socket，不依賴 urllib 的單次 socket timeout），Ollama 偵測斷線會停止推論。晚到的結果不交付，紀錄 `delivered=false`、`late_discarded=true`。
- **UI 修復總上限 32 s**（動作 12 s＋修復最多 20 s）：UI 端每次呼叫帶 `X-GCS-Deadline-Ms = 剩餘總時間`，閘道保證不超過；UI 端自己的 abort 也會被閘道偵測為斷線而取消上游。
- 新紀錄欄位：`deadline_s`（送出時剩餘秒數）、`delivered`、`late_discarded`、`cancel_reason`。

## 8. 修訂（v0.4.1，依 Codex 審查 GATEWAY_REVIEW_0417，2026-11-06 台灣時間）

- **終態同鎖判定**：每次呼叫是一個狀態機（queued → running → completed／cancelled），開始送模型、交回結果、呼叫端放棄都在同一把鎖內對照同一個時鐘判定。**期限後才回來的結果一律不認領、不交付**（記 `claimed=false`、`late_discarded=true`）；移除 v0.4 的「最後一刻再多等 1 秒」。期限前已完成的照常交付，呼叫端不必等紀錄寫完。
- **取消與連線建立同步**：已取消就不連線；連線建立後才發現已取消 → 立刻關閉、不送出（`sent_upstream=false`，錯誤 `cancelled during connect`）；送出中取消 → shutdown 該 socket。取消改用回呼，不再為每次呼叫開等待執行緒。
- **欄位語意**：`claimed` = 期限前完成、可交給 HTTP 層；另記一行 `{"event":"http_write","job_id","status","write_ok"}` 表示回應有沒有寫進 socket（`write_ok=true` 不保證對方已讀取）。取代 v0.4 的 `delivered`。
- **部署假設（待驗證）**：「上游連線被關閉後，Ollama／llama-server 會停止推論」目前只在假上游驗證過，**尚未在真模型上證實**；第 7 節的對應說法降為假設。

## 9. 修訂（v0.4.2，依 Codex 複審 GATEWAY_REVIEW_0423）

- 成功結果在認領的同一刻就叫醒呼叫端；紀錄之後才寫，**交付不等紀錄**（呼叫端讀紀錄要自己等它落檔）。
- 送出前的唯一同步點 `claim_send()`：與 `abort()` 用同一把鎖，且 shutdown 也在鎖內完成。取消先拿到鎖 → 0 個 POST；送出先通過 → 之後的取消以 shutdown 中斷傳輸與等待回應（此時上游可能已收到請求）。

## 10. 修訂（v0.4.3，依 Codex 複審 GATEWAY_REVIEW_0426 的 P2）

- 上游連線有明確階段：idle → connected（socket 已發布）→ sending（通過 claim_send，請求可能已到上游）→ received（回應已讀完）。被中斷時以當下階段判定，紀錄 `sent_upstream`（sending／received 為 true）與 `upstream_phase`，不再由錯誤字串推斷。回應讀完後才取消 → `sent_upstream=true`、`upstream_phase="received"`、`claimed=false`。
