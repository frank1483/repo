# MVP 共用安裝器與插槽（v1）

把 UI agent、MVP 插槽與兩個外掛包（AiAlerts 告警、AiMission 任務）一次裝進**全新的正式 UI 副本**。正式 UI 原始資料夾不動。

```bash
bash ui_agent/mvp/install_mvp_into_ui.sh --check <UI 副本>   # 先預演，副本不變
bash ui_agent/mvp/install_mvp_into_ui.sh <UI 副本>           # 真的安裝
bash ui_agent/mvp/install_mvp_into_ui.sh --skip AiMission <UI 副本>   # 某個外掛先不裝（插槽留空）
```

## 安裝內容
- UI agent：呼叫既有的 `ui_agent/install_into_ui.sh`（16 個資產、6 份 patch，檢查不變）。
- 插槽 patch `patch/elan_gcp_mvp_slots.patch`（5 個檔）：
  - `GcpMainShell.qml`：浮動層（z 90，在 UI agent 之下），Loader 載入 `AiAlerts/GcpAiAlertsPanel.qml`，右上 16 px；傳入 `apiBase`、`alertManager`（正式 UI 的 GcpAlertManager）、`shell`、`envValue`，並綁定 `vehicleId`。
  - `GcpMissionPlannerPage.qml`：地圖上、工具列右側的區域，Loader 載入 `AiMission/GcpMissionAiPanel.qml`；傳入 `missionController`、`map`、`apiBase`、`envValue`，並綁定 `activeVehicle`。
  - `GcpTelemetrySubNav.qml`／`GcpTelemetryPage.qml`：任務外掛有 `AiMission/GcpMissionReportView.qml` 時，多一個「智慧任務報告」子頁（enum 加在最後，原本 0–7 的索引不變）。
  - `CMakeLists.txt`：加 `MvpSlots/GcpMvpInstalled.js` 與外掛清單標記行。
- 外掛包（`mvp_plugins_v1.txt`）：每包有自己的資料夾、檔名規則、資產清單與 LF 雜湊清冊，由各功能串維護：
  - AiAlerts：`gcs_demo/alerts/qml/`，檔名 `GcpAiAlerts*`。
  - AiMission：`gcs_demo/qml/`，檔名 `GcpMissionAi*`、`GcpMissionCore*`、`GcpMissionReport*`。
- 安裝器產生 `GCP/MvpSlots/GcpMvpInstalled.js`（實際裝了哪些檔）；插槽只在檔案存在時啟用。外掛只要宣告想收的屬性，沒宣告的不會報錯。
- 外掛透過 XMLHttpRequest 連本機 `gcs_demo.server`（預設 127.0.0.1:8765，可用環境變數 `GCS_MVP_API_URL` 改）。

## 保護
只接受乾淨副本（已有 Agent／AiAlerts／AiMission／MvpSlots 或殘留安裝狀態都拒絕）；檢查安裝器自身 4 檔與每個外掛檔的 LF 雜湊；外掛檔名不可和既有 UI 檔名重複（QML 型別會撞名）；上鎖；全部在預演目錄組好才替換；失敗或中斷時還原原本的 GCP 與交接文件。原 GCP 備份留在 `.mvp-install.*/original-GCP`。

外掛更新時，對應的功能串更新自己的資產清單與雜湊清冊即可；插槽 patch、範本、外掛設定有改動時，要重算 `install_mvp_payload_v1.sha256`。

## 測試
- `python3 -I ui_agent/test/run_install_mvp_controls.py <未安裝的樣本> <新證據資料夾>`：11 個情境。
- `python -I ui_agent/test/run_harness_mvp_slots.py <完整安裝副本> <--skip 全部的副本> <新證據資料夾>`：PySide6 離屏，確認外掛經插槽載入並拿到屬性；沒裝時插槽不啟用。
- 真正的 CMake 編譯在 Ubuntu 上進行（`ui_agent/ubuntu_build_demo.sh`，由 MVP 串整理步驟）。
