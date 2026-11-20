# qt_widgets_verify_host04：重驗 host03 的三項（bind-m1-0.4.4）

host03 run1：GenuiW2Series.qml 的行內註解吃掉三元運算式的「: null」，W2 整個載入失敗（4 fail），而收集程式沒把「Expected token」算成警告。0.4.4 修好語法，靜態檢查會抓這類錯；collect_h.py 改成帶「file://…:行號」的行一律算警告。

## 沿用 host03：host02 再驗 W2 標籤上下順序與正式字型（bind-m1-0.4.3）

host02 run1：7 個舊警告沒再出現，但 W3 多 1 個同類警告；W2 在 160 高時「保留」與「目前」上下顛倒；W2 左側刻度用了系統字型。三項都在 bind-m1-0.4.3 修正，本包加驗順序與字型。

## 沿用 host02：host01 再驗「資料接上過程沒有警告」與「W2 在 1280 寬完整顯示差距」（bind-m1-0.4.2、layout-m1-0.5）

依使用者 11/20 21:02：「下一輪確認兩件事：從元件載入到資料接上的過程中，原本 7 個警告都未再出現，以及 W2 在 1280 px 下完整顯示差距。」最窄支援寬度維持 1280 px。
- 每案先讓元件在資料未接上（bound＝null）時建立，200 ms 後才接上資料，再等 800 ms 量測截圖。整段的 qml 警告都算失敗。
- W2：1280 寬、排版實際給的尺寸（1080／600／400 高）；「目前…」加差距那一段與「保留…」必須完整（沒有省略、沒裁切、在框內）。
- host01 的 6 案照舊。小主程式與 host01 相同做法，src／build 開新目錄。

以下沿用 host01 說明：


依使用者 11/20 16:40：「下一輪用主程式載入正式字型後截圖，確認 W4 最窄時 R1 仍完整可讀，以及 W1 在最矮支援高度下，安全提示、主要事實和『未查』同時出現時都看得到。」

- real02 用 `qml -I` 載入時，正式主題的 FontLoader（qrc:/qml/QGroundControl/GCP/fonts/...）載不到。這裡用 CMake 編一個只給驗證用的小主程式：把允許清單的 11 個 QML 檔與 FontLoader 用到的字型照 qrc 路徑編進程式資源。原檔只複製、不改、不進 repo。完整 QGC 整合在 APK 時做。
- 不下載、不安裝：缺 cmake 或編譯器就停（exit 5），回報後再問使用者。
- 最窄支援寬度（假設）：工作區最窄 1280。驗兩種：排版實際給 W4 的最窄寬度，和目錄最小 3 欄（1280 下 308 px，高度用內容最小高度）。
- 最矮支援高度：排版（含內容最小高度）成功的最小視窗高度，逐 1 px 往下找；再矮 1 px 的錯誤也記下。安全情境：safe1（電量樣本不足 → 1 條安全提示）、safe2（再加告警缺段 → 2 條）。
- 截圖含正式 UI 外觀，只留在筆電與 PC，不傳出。

只跑一次，輸出原樣保留。在本資料夾執行（R＝正式原檔，S＝新的原始碼目錄，B＝新的建置目錄）：

```
R=~/elan_gcp_ui_official_20261120/ELAN_GCP_ui; S=~/genui_host_src_host04_20261120; B=~/genui_host_build_host04_20261120
bash make_host_src.sh "$R" "$S" "$PWD" > make_src.txt 2>&1; echo "exit=$?" >> make_src.txt
bash build_host.sh "$S" "$B" > build.txt 2>&1; echo "exit=$?" >> build.txt
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 120 "$B/genui_host" "$PWD/host_verify.qml" > h_raw.txt 2>&1; echo "exit=$?" >> h_raw.txt
python3 collect_h.py h_raw.txt h.json > compare_h.txt; echo "exit=$?" >> compare_h.txt
cp "$S/fonts_map.txt" "$S/SRC.sha256" "$S/CMakeLists.txt" "$S/referenced_types.txt" .
```

前一步失敗就停在那一步，不改腳本重跑；修正另開 host05。

判定：見 collect_h.py 開頭。另請人眼看截圖：W4 的 R1 句子完整、W1 三種文字都在、沒有方塊字。
