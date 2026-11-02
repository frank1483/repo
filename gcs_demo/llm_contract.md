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
