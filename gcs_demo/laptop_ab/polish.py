"""LLM 潤飾回覆的接點（A、B 共用）。

使用者 2026-11-23：A、B 都要潤飾（R1、R2、R4 照建議，R3 追問句也潤飾），不設開關。
潤飾演算法（v3.12）由 ADR-0002 討論串撰寫並經使用者確認；程式交付後換掉下面的 polish()。
在那之前固定回模板，並標明原因，面板照樣顯示「模板」來源。
"""
from __future__ import annotations

STATUS = "pending_program"        # 換成正式程式後改成 "v3.12"


def describe():
    return {"status": STATUS, "note": "潤飾程式尚未接上（等 ADR-0002 v3.12 定案），目前一律用模板回覆"}


def polish(result, model, calls_log):
    """回傳 {"reply", "source": "model_polish"|"template", "reason"}；模型呼叫要記進 calls_log。"""
    return skipped(result, "潤飾程式尚未接上（v3.12 待定案）")


def skipped(result, reason):
    return {"reply": (result or {}).get("reply_zh") or "", "source": "template", "reason": reason}
