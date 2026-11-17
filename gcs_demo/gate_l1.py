"""Agent 入口 Gate 第 1 層（ADR-0001 §2 第 1～4 條；ADR-0002 D-13）。

整句只要有一個子句是飛控命令就 HOLD；查詢詞與問句只豁免它所在的子句，不豁免整句。
與 QML ui_agent/qml/GcpAgentCore.js 的 preGate 共用 gate_l1_vectors_v1.json。
"""
from __future__ import annotations

import re

MAX_LEN = 200
CMD_WORDS = ["起飛", "降落", "返航", "解鎖", "上鎖", "懸停", "開始任務", "執行任務", "暫停任務", "拍照", "錄影",
             "takeoff", "land"]
QUERY_HINTS = ["在哪", "哪裡", "哪里", "顯示", "多少", "什麼", "是否", "怎麼", "如何", "查詢", "查询", "設定", "設置",
               "頁", "畫面", "打開", "開啟", "查看", "進入", "前往", "參數", "保護", "嗎", "能不能", "可不可以",
               "？", "?"]
NOUN_EXCEPTIONS = ["返航點", "降落點", "起飛點", "返航高度", "返航電量", "返航速度", "返航距離", "電量", "电量"]
SPLIT = re.compile(r"[，,。；;]|然後|然后|再|並|并")


def _norm(s):
    return re.sub(r"[\s　]+", " ", str(s or "").lower()).strip()


def gate(text):
    """回傳 {'status': INVALID_INPUT|TOO_LONG|HOLD|PASS, 'clause'?: 觸發的子句}。"""
    raw = _norm(text)
    if not raw or not re.search(r"[0-9a-z一-鿿]", raw):
        return {"status": "INVALID_INPUT"}
    if len(str(text)) > MAX_LEN:
        return {"status": "TOO_LONG", "message_zh": "輸入過長，請拆成短句"}   # 不截斷、不路由
    for clause in [c.strip() for c in SPLIT.split(raw) if c and c.strip()]:
        cmd = clause
        for n in sorted(NOUN_EXCEPTIONS, key=len, reverse=True):
            cmd = cmd.replace(n, " ")
        if any(w in cmd for w in CMD_WORDS) and not any(q in clause for q in QUERY_HINTS):
            return {"status": "HOLD", "clause": clause,
                    "message_zh": "我不會送飛行或相機指令，請用畫面上的指令區（需滑動確認）"}
    return {"status": "PASS"}
