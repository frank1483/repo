# 任務外掛包 GCP/AiMission v1（MVP 桌面版）

依使用者 2026-11-13 確認的設計 v1（8 項全勾，https://claude.ai/artifact/KiJk3eeYj7eQGpbWDanyk6）。由共用安裝器 `ui_agent/mvp/install_mvp_into_ui.sh` 裝進正式 UI 的**全新副本**，原檔不動。

- 資產（install_assets_mission_v1.txt）：GcpMissionAiCore.js、GcpMissionAiPanel.qml、GcpMissionReportView.qml；雜湊 install_payload_mission_v1.sha256（LF 正規化後 SHA256）。檔案改了要同步更新兩份清單。
- 插槽：規劃頁地圖上載入 `AiMission/GcpMissionAiPanel.qml`（傳入 missionController、map、apiBase=GCS_MVP_API_URL、envValue，綁定 activeVehicle）；遙測頁「智慧任務報告」子頁載入 `AiMission/GcpMissionReportView.qml`。
- 資料流：面板讀規劃頁航點 → POST /api/plan {mission, wind}（gcs_demo.server :8765）→ 伺服器演算法產生候選、經閘道 :8090 讓模型在候選內選；報告子頁讀 GET /api/report。面板不直接連模型（GCS_LLM_URL 是 UI agent 的路由，不用）。
- 伺服器沒開：顯示「AI 服務未連線」並停用按鈕；QML 沒有規則備援。
- 套用：只改航點順序或拿掉選配點（removeVisualItem／insertSimpleMissionItem），每次可復原；規劃後航點被改過就要求重新規劃。不送飛行指令。
- 「模擬飛行與報告」是模擬；真實飛行報告與 CSV/KML/KMZ 匯出在報告 v2。
- 舊的 JS 核心版面板改名為 GcpMissionAiPanelJs.qml（不在清單內、不安裝；留給之後的 APK）。
- 測試：`node gcs_demo/qml/test/test_mission_ai_core.js`（6 案）；`python3 -m unittest gcs_demo.test_mission_input`（5 案）；離屏 `gcs_demo/qml/test/mission_ai/run_offscreen.py`（需 PySide6，對真 server）。
