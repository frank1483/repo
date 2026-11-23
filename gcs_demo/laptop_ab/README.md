# 在編譯筆電（Ubuntu 22.04）跑方案 A／B

程式和 PC 版相同（演算法、案例、計分都沒改）。只補了 Linux 需要的部分：
- 埠歸屬：Windows 用 `netstat -ano`，Linux 改讀 `/proc/net/tcp(6)` 與 `/proc/<pid>/fd`。
- RAM 取樣：Windows 用 `tasklist`（ollama.exe），Linux 加總名為 `ollama` 的程序 VmRSS（KB）。
- 模型根與 ollama 執行檔可用 `GCS_OLLAMA_MODELS`、`GCS_OLLAMA_BIN` 指定（沒設時和 PC 原本一樣）。`RUN_INFO` 多記 `platform`、`ollama_bin`。
- 測試：`python3 -m unittest gcs_demo.test_laptop_linux`（4 項，只在 Linux 跑）。

## 筆電上的資料夾配置（執行器把來源包裡的相對路徑接在 BASE 下面）

```
~/thesis_ab/                      ← BASE（對應 PC 的「碩士論文」）
├── adr0002_impl_laptop_v1/
│   ├── repo/                     ← 這個 repo（乾淨工作樹，commit 要等於來源包 commit.txt）
│   └── runs/                     ← 輸出（腳本自動建立）
├── adr0002_algo/                 ← 從 PC 複製（約 380 KB）
├── adr0002_rag_v1/
│   ├── corpus/                   ← 從 PC 複製（約 12 MB）
│   ├── index_v1/                 ← 從 PC 複製（約 71 MB）
│   └── id_index_v1/              ← 從 PC 複製（約 412 KB）
└── adr0002_<名稱>_bundle_v1/     ← 筆電用新來源包（SHA256SUMS.txt、commit.txt、MANIFEST.md）
```

模型（放在 `~/.ollama-0.40.14/models`，和 MVP 共用 Ollama 0.40.14）：
- `gemma4:e2b`：manifest sha256 必須是 `b37049369adf…`（`gemma4_tokenizer.py` 寫死）。筆電已有一份，先用 `--check` 看是否相同；不同就從 PC 複製 manifest 與 blobs。
- `embeddinggemma-2:270m-q8_0-text`：筆電沒有。PC 版 manifest sha256 `67998e96…`，約 303 MB。

## 指令

```bash
cd ~/thesis_ab/adr0002_impl_laptop_v1/repo
bash gcs_demo/laptop_ab/run_ab_laptop.sh --check                         # 唯讀檢查
bash gcs_demo/laptop_ab/run_ab_laptop.sh --fake lap1f smoke research     # 假模型（不是 live）
bash gcs_demo/laptop_ab/run_ab_laptop.sh --live ~/thesis_ab/adr0002_<名稱>_bundle_v1 <hash8> lap1 smoke research
```

live 規則不變：Claude、Codex 對同一份來源包 SHA256 精確同意，使用者親打「同意 <hash8>」後才執行；每個輸出目錄只跑一次。
