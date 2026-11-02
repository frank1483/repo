# 功能3：依場域切換辨識模型（demo 草案 v0）

只用 Python 3.9+ 標準庫。演算法尚待使用者確認，數字都是草案。

```bash
python3 -m gcs_demo.recognition.demo rec_demo.html   # 跑腳本並輸出可逐步播放的單檔 HTML
python3 -m unittest gcs_demo.test_recognition         # 測試
```

- 場域設定檔 `gcs_demo/domains/*.json`（農業、巡檢、多機）與功能4 情境式 UI 共用：`ui_template` 欄位給 UI agent 用，`recognition` 欄位給這裡用。類別標準名與別名在 `domains/classes.json`。
- 模型 manifest `recognition/models/<id>.json`：執行方式、模型檔、SHA256、類別、各裝置量測延遲、授權。
- 目前模型全是合成權重（`runtime: stub`），只示範切換流程；`onnx_general_missing` 示範「未下載」被排除。真實模型要先列檔名、來源、大小、授權並經使用者同意才下載。
- Genio 520 NPU（`neuron` driver）待查證 MediaTek 工具鏈後再做。
- 「多機」暫時視為作業情境：沿用通用人/車模型、每架各自辨識（待使用者確認）。

## MVP：預設接 LLM（llm_contract v0.3）

- 沒設 `GCS_LLM_BACKEND` 時，預設經共用閘道 `http://127.0.0.1:8090/f/recognition/v1`、模型 `gemma4:e2b`（閘道在分支 `claude/project-thread-wum8aq`）。連不到、逾時（30 秒）或回了不存在的候選，都退回規則並在理由標示；`GCS_LLM_BACKEND=none` 為純規則。
- LLM 只在程式排好的候選代號（M1、M2…）內選或回 HOLD，辨識模型本身仍是合成 stub。
- 冒煙測試（只準備，使用者同意 hash8 後只跑一次）：

```bash
python3 -m gcs_demo.recognition.smoke_llm --dry-run                  # 印 bundle hash8 與 3 份 prompt，不呼叫模型
python3 -m gcs_demo.recognition.smoke_llm --out <新目錄>/recog_smoke_run1   # 農業／巡檢／多機各 1 次
```
