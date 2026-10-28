# UI agent（介面助理）demo

在 ELAN GCP 新版介面的每個畫面右側加一顆「AI」按鈕。使用者用一句話說意圖，agent 會：

- **切畫面**：例如在首頁說「我想查看飛行設定」，會列出可能的畫面（系統設定 › Fly View、安全設定 › 飛行限制、設備管理 › 飛行模式…）讓使用者點；說得明確（「打開系統設定的 Fly View」）就直接切過去。
- **調整版面**：首頁 6 個與即時飛行畫面 12 個模組可以移動（九宮格位置或往上下左右移一點）、放大縮小、隱藏與重新顯示，移動時會避開其他模組、不會跑出畫面。在別的畫面下達版面指令會先自動切到即時飛行。
- **復原**：每次變更前都存一份快照（目前畫面＋子頁＋全部模組位置）。可以復原一步、復原多步（「復原兩步」）、重做、全部復原（回到 agent 介入前，這一步本身也能再復原）。套用後畫面下方會出現「復原」按鈕。

agent 只換頁與調整版面，**不送飛行或相機指令、不修改任何參數值**；換頁沿用原本的帳號權限檢查。

## 決策流程（演算法先決定，模型只挑選）

1. 規則把意圖轉成候選動作（每個有固定 ID，如 `NAV_8_11`、`LAY_windGauge_MOVE_TL`、`UNDO`）與證據（目前畫面、比對分數）。
2. 規則有把握（分數夠高且明顯領先）就直接執行，不呼叫模型。
3. 規則不確定時才問模型；模型只能回 `{"decision":"SELECT|HOLD|CLARIFY","choice_id":"候選ID","reason_zh":"…","evidence_ids":[…]}`（與三功能共用格式相同）。規則完全對不到時，把全部畫面當候選讓模型用語意挑。
4. 模型回覆不是 JSON、ID 不在候選內、引用不存在的證據、逾時 → 一律退回規則結果。
5. 安全界線（像「起飛」「返航」這類指令）與「已經在這個畫面」由規則直接回答，不交給模型。

每次決策在 log 印一行 `[GcpAgent] {...}`（意圖、規則結果、模型結果、最後決定、延遲），之後可以拿來統計。

## 檔案

| 路徑 | 內容 |
| --- | --- |
| `qml/GcpAgentCore.js` | 畫面目錄、模組目錄、意圖→候選、規則決策、模型提示與驗證、版面幾何（純 JS） |
| `qml/GcpAgentState.qml` | 單例：模組登記、版面覆寫（Scale＋Translate，不動原本 anchors）、復原／重做堆疊 |
| `qml/GcpAgentModule.qml` | 在畫面裡登記一個可調整模組 |
| `qml/GcpAgentOverlay.qml` | AI 按鈕、面板、復原提示列、模型呼叫（OpenAI 相容或 Ollama） |
| `patch/elan_gcp_ui_agent.patch` | 對正式 UI 的修改：CMakeLists 加檔案、GcpMainShell 加兩個函式與疊層、即時飛行補 id 並登記 12 個模組 |
| `patch/elan_gcp_home_modules.patch` | 首頁 6 個模組（狀態列、天氣、系統詳情、三塊啟動磚）登記；agent 掛外層，原進場動畫留內層 |
| `install_into_ui.sh` | 把上面裝進 UI **副本** |
| `test/` | `test_core.js`（node）與 `run_harness.py`（Qt 6.8.3 離屏模擬畫面） |

## 在 Ubuntu 上裝進正式 UI 的副本並編譯

不要在原本的工作目錄上做。以 git worktree 開一個副本（原目錄不受影響）：

```bash
cd ~/ELAN_GCP_ui                          # Ubuntu 上原本的 UI repo
git worktree add ../ELAN_GCP_ui_agent -b ui-agent-demo
git clone -b claude/project-thread-8cd61o https://github.com/frank1483/repo.git ~/gcs_ui_agent
~/gcs_ui_agent/ui_agent/install_into_ui.sh ~/ELAN_GCP_ui_agent
```

一鍵版：`~/gcs_ui_agent/ui_agent/ubuntu_build_demo.sh ~/ELAN_GCP_ui`（自動開副本、安裝、沿用原 build 的 Qt 路徑編譯）。

Linux 桌面版手動步驟（第一次要 configure）：

```bash
cd ~/ELAN_GCP_ui_agent
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_PREFIX_PATH=<Qt 6.8.3 gcc_64 路徑>
cmake --build build --parallel 4
GCP_PREVIEW=MainShell GCS_LLM_BACKEND=none ./build/Debug/QGroundControl     # 不登入、規則模式
```

即時飛行的 HUD 模組（姿態儀、風速計、羅盤…）要連上載具才顯示，可以先開 PX4 SIH SITL 再測。

Android APK（沿用之前的 build 目錄設定）：

```bash
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ninja -C build-android-arm64-debug apk
```

## 接模型

桌面版用環境變數；板子上在面板右上角 ⚙ 填（存在本機，重開保留）：

| 設定 | 例子 |
| --- | --- |
| `GCS_LLM_BACKEND` | `openai`（vLLM、llama.cpp server、Ollama 的 /v1）、`ollama`（原生 /api/chat）、`none`（只用規則） |
| `GCS_LLM_URL` | `http://<server>:8000/v1` |
| `GCS_LLM_MODEL` | 伺服器上的模型名稱 |
| `GCS_LLM_TIMEOUT_MS` | 預設 20000 |
| `GCS_AGENT_LLM_ALWAYS` | `1` = 每次都問模型（預設只在規則不確定時問） |

## 測試

```bash
node ui_agent/test/test_core.js                              # 決策核心 69 項
pip install PySide6==6.8.3
python -I ui_agent/test/run_harness.py /tmp/agent_out        # 模擬畫面 18 項，存截圖
```

模擬畫面用的是假的殼層與假模型伺服器（固定回覆），只驗證流程與復原邏輯，不代表正式 UI 已編譯通過或真實模型的表現。
