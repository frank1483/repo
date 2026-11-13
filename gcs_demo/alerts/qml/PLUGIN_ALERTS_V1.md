# 告警外掛包 GCP/AiAlerts v1（MVP 桌面版）

給 UI 串的共用安裝器 install_mvp_into_ui.sh 使用。只裝進正式 UI 的**全新副本**，原檔不動。

- 資產（install_assets_alerts_v1.txt，前綴 GcpAiAlerts）：GcpAiAlertsCore.js、GcpAiAlertsPanel.qml → 副本的 `GCP/AiAlerts/`，並列入 GCP/CMakeLists.txt（`AiAlerts/<檔名>`，沒有 singleton）。
- 雜湊：install_payload_alerts_v1.sha256（LF 正規化後 SHA256）。
- 插槽：主畫面浮動層，Loader `source: "AiAlerts/GcpAiAlertsPanel.qml"`，預設錨在地圖右上（右、上各留 16 px）。沒裝外掛時 Loader 空著。
- 寫入正式 UI 告警清單（使用者 2026-11-13 決定）：插槽設定 `alertManager`（GcpAlertManager 單例，非正式 UI 時 null）、`envValue`、`vehicleId`。面板以「alert_id＋等級」為條件 key 記住 addConditionAlert 回傳的 id，不重複新增；升降級時舊列 resolveCondition、新列 add；告警解除或消失時 resolveCondition；示範情境重設時全部 resolve。等級 注意→5、警告→4、嚴重→2，source「預測告警」。列上訊息是發出當下的規則文字，模型說明只在面板補（避免嚴重等級重複語音）。
- 可設屬性：`apiBase`（預設 http://127.0.0.1:8765）、`pollMs`（1000）、`panelScale`、`fs` 與配色。
- 後端：`python3 -m gcs_demo.server --port 8765`；要讓說明真的呼叫模型，gateway（:8090，gemma4:e2b）也要先啟動。後端沒開時面板顯示「告警伺服器未連線」，按鈕停用。
- 行為（使用者 2026-11-13 確認）：右上浮動、可拖曳／縮放／收合但不能隱藏；嚴重等級不能按「知道了」收起；示範情境用按鈕啟動（reset→plan→start），不自動播放；容量判斷顯示「停用（MVP）」。不送任何飛行指令。
- 測試：`node gcs_demo/alerts/qml/test/test_alerts_core.js`（12 案，含告警清單同步）；`python3 -m unittest gcs_demo.alerts.qml.test.test_server_contract`；qmllint 無警告；PySide6 6.x 離屏載入、對真 server 按示範情境，面板出現 1 張「嚴重／規則」卡，假 GcpAlertManager 收到 1 次 addConditionAlert(2, 預測告警, …)（容器內沒開 gateway，所以是規則文字）。
