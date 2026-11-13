# 0428 分批交付 1：逐來源入口與診斷層

基底 d161a57e8cc97eccc9e291ba984c7ba5b1b3822b。這是新增入口與十組未執行控制，
**尚未接到 PredictiveAlertEngine／bridge，不能宣稱 legacy 全快照 UNKNOWN 已修好**。
原 predict.py 的全快照 `_input_error` 與航點 clamp 在此批保留，待下一批獨立修改。

輸入：`SourceInputs.put(source, value, sensed_t, recv_t, valid=...)`，時間必須同一
單調秒數域，來源 TTL 沿用已核准 Freshness 表／明確設定覆寫。通用來源值的格式與
物理範圍由上游驗證後填 valid，不在這裡猜。MAVLink 電流有單獨入口，強制明確
SYS_STATUS／BATTERY_STATUS、10mA 單位及機型上下限；只有 -1 缺值，-5 保留 -0.05A。
新無效樣本取代舊有效樣本，避免偷用舊電流；重複／亂序樣本不改現值或有效性。

輸出：`readiness(required, now)` 回傳這一個消費者所宣告來源的 ready／unknown、
缺失來源清單及逐項診斷。從未收到的來源 value/timestamps 都為 null，沒有假最後值。
每項保留 sensed/recv 時間、各自 age、TTL、invalid/expired/future/missing 原因與丟棄數。
比較 sensed 與 recv 兩種 age；在 sensed<=recv 的共同時間域，同 TTL 下 sensed 是較嚴格
條件，不能用新接收時間替舊量測續命。TTL 等號仍有效，只有大於才過期。

限制：沒有自訂門檻／修改機型檔；測試的 -1..10A 僅 fixture。沒有預設不完整的
P1-P5必要來源表，也沒有把未知來源補成正常。下一批須由引擎按實際演算法依賴宣告
必要來源（含能量、速度、航點等）、將來源無效只傳到相依預測器、處理歷史與校正
採樣時間、event sensed/recv provenance，再接bridge。不得僅在update外包readiness
之後仍用全域 `_input_error`，那不會完成逐預測器UNKNOWN。

Claude 首次執行：乾淨基底先核對129原檔清冊與本補丁雜湊，`git apply --check
--whitespace=error`、套用一次；Python AST parse兩個新檔後，只首跑新增
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest gcs_demo.alerts.test_source_inputs_0433`。
預期10項，保留stdout/stderr/exit和首敗。本批未動runtime呼叫路徑，不重跑既有通過套件。
下一批引擎整合後再做受影響引擎控制，battery合併／HOLD／allowed_ids等仍後排。

此入口是工程草稿，尚未執行；非模型品質、飛行、感測、板端或人工批准證據。
