# 預測型智慧告警（demo）

不是等數值越線才叫，而是**預測**接下來會出什麼事，提前告訴操作員，並給出算好數字的建議。

分工原則（和任務規劃、UI agent 共用）：

- **數字全部由演算法算**：能耗用三功能共用的 `gcs_demo/energy.py`，告警不另養一套。
- **LLM 只做兩件事**：把演算法的事實寫成白話；從演算法列出的「可行」建議裡挑一個 ID。
- 模型掛掉、逾時、選了清單外或不可行的選項、說明裡出現事實沒有的數字 → 退回規則，告警照發。
- 建議永遠要操作員確認才執行。

## 預測器

| 代號 | 告警 | 怎麼預測 |
| --- | --- | --- |
| P1 | 電量不足以飛完航線 | 剩餘航線＋返航能耗 × 線上校正係數（實測功率/模型功率），和可用能量比較；預測用風速含趨勢外推 |
| P2 | 即將到達最晚返航點 | 沿剩餘航線找「飛到這點再返航仍有保留電量」的最後一點，算到達時間 |
| P3 | 電池實際容量低於標稱 | 補償內阻後的單芯電壓對已用能量做回歸，外推到空電，和飛控電量% 比較（抓老化電池） |
| P4 | 航線前方可能斷訊 | 學「鏈路品質 vs 離家距離」，套到剩餘航點，找第一個低於門檻的點與到達時間 |
| P5 | 風速將超過抗風上限 | 近 3 分鐘風速線性外推 |

電量類告警的建議選項：照原航線繼續、降速到最省電速度、飛完最晚返航點後返航、立即返航、就地降落（最後手段），每個都附預估落地電量與任務完成度。告警有遲滯（連續 3 次成立才發、10 次不成立才解除），持續中只有升級或建議改變才重新說明。

## 執行

```bash
python3 -m unittest gcs_demo.alerts.test_alerts           # 10 項測試
GCS_LLM_BACKEND=none python3 -m gcs_demo.alerts.run_demo out/
# 真實模型（任一 OpenAI 相容服務或 Ollama）
GCS_LLM_BACKEND=ollama GCS_LLM_URL=http://127.0.0.1:11434 GCS_LLM_MODEL=gemma4:e2b \
  python3 -m gcs_demo.alerts.run_demo out/
```

輸出 `out/alerts_demo.html`（單檔，可直接用瀏覽器開）：同一趟風變大的任務跑兩次，「不理會告警」與「操作員採用建議」對照。

目前模擬結果（規則說明，未接模型）：

| | 首次預警 | 實際落地剩餘（占標稱） |
| --- | --- | --- |
| 風大、不理會 | 06:27，比落地早約 9 分鐘，預估落地 19% | 17.4%（低於保留 20%） |
| 風大、採用「飛完 WP14 後返航」 | 同上 | 25.9% |
| 無風（對照） | 不發電量告警 | 24.1% |

模擬資料是故意設計的情境（電池老化到標稱 86%、耗電多 10%、中途風速 3→11 m/s），不是實機資料；之後換 PX4 SITL 的 MAVLink 遙測，引擎介面不變。

## 給其他模組呼叫

```python
from gcs_demo.alerts.predict import PredictiveAlertEngine, Telemetry, Config
from gcs_demo.alerts.explain import explain

eng = PredictiveAlertEngine(route_enu, home_enu, vehicle, Config())
for ev in eng.update(Telemetry(...)):      # 每秒一次；回傳 raise / update / resolve 事件
    if ev["type"] != "resolve":
        ev["explain"] = explain(ev)          # 模型說明＋選擇（失敗自動退回規則）
eng.set_route(new_route)                    # 操作員改航線後通知引擎
```

## 接進正式 UI（Genio 520 APK）

正式 UI 的 `GCP/GcpAlertManager` 已有 `addConditionAlert(severity, source, vehicleId, message, value)` 與 `resolveCondition(id)`，告警頁、詳情抽屜、首頁徽章、緊急 Toast 都會自動吃到。規劃：

1. 把 P1–P5 移植成 C++ `GcpPredictiveAlerts`（讀 QGC `Vehicle` 的電池、風、位置與任務航點），事件轉成 `addConditionAlert`，嚴重度用 MAV_SEVERITY（2 緊急、4 警告、5 預告）。
2. 詳情抽屜加「依據」「建議選項」兩區，建議按鈕走既有的 `GuidedActionsController` 與滑動確認列。
3. 白話說明由同一個本機模型服務提供（OpenAI 相容 `/v1/chat/completions`），和 UI agent 共用。
