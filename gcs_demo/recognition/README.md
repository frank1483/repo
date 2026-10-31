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
