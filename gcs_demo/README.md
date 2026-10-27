# 任務規劃與智慧任務報告 demo

只用 Python 3.9+ 標準庫，不需安裝套件。

```bash
git clone -b claude/project-thread-ovsufa https://github.com/frank1483/repo.git
cd repo
python3 -m gcs_demo.server --port 8765          # 規則模式（不接模型）
# 瀏覽器開 http://127.0.0.1:8765/
python3 -m unittest tests.test_gcs_demo          # 測試
```

接模型（三功能共用的可抽換介面，見 `llm.py`）：

```bash
# vLLM / llama.cpp server / Ollama 的 OpenAI 相容端點
GCS_LLM_BACKEND=openai GCS_LLM_URL=http://127.0.0.1:8000/v1 GCS_LLM_MODEL=<模型名> python3 -m gcs_demo.server
# Ollama 原生
GCS_LLM_BACKEND=ollama GCS_LLM_URL=http://127.0.0.1:11434 GCS_LLM_MODEL=gemma3:1b python3 -m gcs_demo.server
```

在 JupyterLab 裡跑：伺服器起在 8765 後，可用 jupyter-server-proxy 的 `/user/<帳號>/proxy/8765/` 開畫面（若 server 有裝）。

## 流程

1. **出發前規劃**：演算法產生候選航線（照輸入順序、最短距離、最省電順序〔含風〕、最省電速度、只做必要目標），每條都算距離、時間、能耗、落地電量、禁航區與高度檢查。規則先選一條；有模型時由模型在候選內挑（H-a），選了不存在的 ID 就退回規則。
2. **飛行中預測告警＋重規劃**：模擬第 5 分鐘風速增強。系統用「起飛後實際/預估耗電比」修正剩餘航線估算，若照原計畫落地電量會低於保留值就先發告警，並給出 LOCAL（保留順序局部修補、刪選配目標）、FULL（剩餘重排、改速）、部分完成後返航、立即返航等候選。
3. **智慧任務報告**：演算法算出事實（完成率、實際 vs 預估耗電、最耗電航段、逆風影響、風況變化、重規劃與告警紀錄、最省電速度），規則產生建議，每條建議都附事實編號；模型只能改寫與排序，沒有引用事實的句子會被丟掉。報告算出新的耗電修正係數，可一鍵帶入下一次規劃。

## 檔案

| 檔案 | 內容 |
| --- | --- |
| `energy.py` | 多旋翼能耗模型（告警串共用：`estimate_route_energy`、`rtl_energy`） |
| `planner.py` | 候選產生、限制檢查、LOCAL/FULL 重規劃 |
| `llm.py` | 可抽換模型後端與 H-a 選擇（`pick_candidate`） |
| `sim.py` | 飛行模擬（真實耗電比預估多 15%、中途風變大） |
| `report.py` | 智慧任務報告與建議 |
| `server.py`、`web/index.html` | JSON API 與示範畫面；QGC/QML 之後可直接呼叫同一組 API |

## 沒有 jupyter-server-proxy 時：單檔版

```bash
python3 -m gcs_demo.export gcs_demo_static.html
```
在 JupyterLab 檔案列表對產生的 HTML 按右鍵 → Open in New Browser Tab（或下載到自己電腦用瀏覽器開）。
預設風況下所有候選組合都已預先算好（含模型選擇，若有設定 GCS_LLM_*），操作和伺服器版相同，但不能改風速。
