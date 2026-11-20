# qt_trans_verify_host08：在筆電實體螢幕上驗真正的模糊（skel-m1-0.2）

使用者 11/20 21:56 在選擇卡選「筆電實體螢幕跑一次」。在筆電已登入的桌面開一個約 1 分鐘的視窗截圖，用 GPU 畫模糊；不改設定、不下載。
先確認有已登入的桌面工作階段可以用（X11：/tmp/.X11-unix/X0 與該使用者的 XAUTHORITY；Wayland：WAYLAND_DISPLAY）。找不到就停下回報，不自己開工作階段、不改顯示設定。
判定照 collect_t.py：effect_ok 必須是 true（有 GPU 後端），t60 比 before 模糊、t120 最模糊且已換成 B、t300 與 critical 清楚、告警列不受影響；沒有 qml 警告。
截圖只放 PC。

只跑一次，在本資料夾執行（X11 的例子；Wayland 改 QT_QPA_PLATFORM=wayland 並帶 WAYLAND_DISPLAY、XDG_RUNTIME_DIR）：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host08_20261120; B=~/genui_host_build_host08_20261120
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
(who; ls -l /tmp/.X11-unix 2>&1; echo "WAYLAND=$WAYLAND_DISPLAY") > session.txt 2>&1
mkdir runC && cd runC && DISPLAY=:0 QT_QPA_PLATFORM=xcb timeout 90 "$B/genui_host" "$PWD/../trans_verify.qml" > t_raw.txt 2>&1; echo "exit=$?" >> t_raw.txt
python3 ../collect_t.py t_raw.txt t.json > compare_t.txt; echo "exit=$?" >> compare_t.txt; cd ..
cp "$S/fonts_map.txt" "$S/SRC.sha256" .
```

make_src 或 build 失敗就停。修正另開 host09。
