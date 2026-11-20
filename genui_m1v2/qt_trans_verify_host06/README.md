# qt_trans_verify_host06：轉場接上骨架工作區（重驗）

host05 run1：驗證檔屬性名稱大寫開頭，兩種設定都載入失敗（原樣保留）。本包改名，並在執行前用 qmllint 檢查一次（只記錄，不擋）。

## 沿用 host05：轉場接上骨架工作區（skel-m1-0.1、trans-m1-0.1）

依轉場說明 v1（使用者 11/19 23:02「轉場照建議」）第 4 節第 2 步：筆電截三格（模糊進入、換內容最模糊、恢復後），另加 critical 中斷與 reduced motion。
小主程式與 host01～04 相同做法（正式 GCP 原檔與字型編進資源）。MultiEffect 要 GPU 著色器，software 後端畫不出模糊，所以跑兩種設定，各一次：
- A：offscreen，預設繪圖後端。
- B：offscreen，強制 OpenGL＋Mesa 軟體繪製（QSG_RHI_BACKEND=opengl、LIBGL_ALWAYS_SOFTWARE=1）。
任一種通過就算畫面驗收通過；兩種都記錄。邏輯檢查兩種都要過。截圖只放 PC，不傳出。

只跑一次，輸出原樣保留。在本資料夾執行：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host06_20261120; B=~/genui_host_build_host06_20261120
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
~/Qt/6.8.3/gcc_64/bin/qmllint -I "$B" -I ../qml/widgets -I ../qml/skeleton trans_verify.qml ../qml/skeleton/GenuiWorkspace.qml > lint.txt 2>&1; echo "exit=$?" >> lint.txt
mkdir runA && cd runA && QT_QPA_PLATFORM=offscreen timeout 90 "$B/genui_host" "$PWD/../trans_verify.qml" > t_raw.txt 2>&1; echo "exit=$?" >> t_raw.txt
python3 ../collect_t.py t_raw.txt t.json > compare_t.txt; echo "exit=$?" >> compare_t.txt; cd ..
mkdir runB && cd runB && QT_QPA_PLATFORM=offscreen QSG_RHI_BACKEND=opengl LIBGL_ALWAYS_SOFTWARE=1 timeout 90 "$B/genui_host" "$PWD/../trans_verify.qml" > t_raw.txt 2>&1; echo "exit=$?" >> t_raw.txt
python3 ../collect_t.py t_raw.txt t.json > compare_t.txt; echo "exit=$?" >> compare_t.txt; cd ..
cp "$S/fonts_map.txt" "$S/SRC.sha256" .
```

make_src 或 build 失敗就停；runA 失敗仍照跑 runB（兩者是不同設定，不是重跑）。修正另開 host07。
注意：trans_verify.qml 用 `$PWD/../trans_verify.qml`，所以 import 路徑以本資料夾為準（../qml）。
