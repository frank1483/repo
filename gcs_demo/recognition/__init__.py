"""功能3：依場域切換本機已安裝的影像辨識模型（demo 草案 v0）。

drivers.py   執行方式介面（stub / onnx / tflite / neuron），只列本機真的能跑的
registry.py  已安裝模型清單：manifest + 檔案存在 + SHA256 相符 + driver 可用
selector.py  場域 → 候選過濾、評分、規則選擇；模型只在候選內選
switcher.py  切換交易（先載入、試跑成功才換）、可復原、事件紀錄（給任務報告）
"""
