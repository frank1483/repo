"""ADR-0002 第二輪：A、B 共用的「必要成果清單」與成果摘要（演算法說明 v3.6 §1–§2；使用者 2026-11-20 07:14）。

成果狀態由程式從實際成果算出；A 用它決定現在能做什麼，B 用它驗證計畫能不能做完、執行後驗收。
- produced：成果存在（例如預覽不論合格與否都算「已產生」）。
- 方向完成（satisfied）另由 agent_m4b._dir_done 判定（例如 plan 要預覽合格）。
- 合法略過：預覽不合格時，首頁提案不算缺。
"""
from __future__ import annotations

PRODUCES = {"QUERY_AREA": "area_record", "GEN_COVERAGE": "coverage_route", "VERIFY_PREVIEW": "route_preview",
            "PROPOSE_HOME_ROUTE": "home_proposal", "UI_LAYOUT_PROPOSE": "layout_proposal",
            "UI_THEME_PROPOSE": "color_proposal", "MODEL_SWITCH_PROPOSE": "model_proposal",
            "MANUAL_SEARCH": "manual_claims", "QA_LOOKUP": "qa_claims", "REPORT_DRAFT": "report_draft",
            "DECLINE_FLIGHT": "flight_notice"}
NEEDS = {"GEN_COVERAGE": ["area_record"], "VERIFY_PREVIEW": ["coverage_route"], "PROPOSE_HOME_ROUTE": ["route_preview_pass"]}
DIR_REQUIRED = {"plan": ["area_record", "coverage_route", "route_preview"], "ui": ["home_proposal"],
                "layout": ["layout_proposal"], "color": ["color_proposal"], "model": ["model_proposal"],
                "manual": ["manual_claims"], "qa": ["qa_claims"], "report": ["report_draft"],
                "flight_request": ["flight_notice"], "chat": []}
ZH = {"area_record": "區域紀錄", "coverage_route": "覆蓋航點", "route_preview": "預覽驗算結果",
      "route_preview_pass": "合格的預覽", "home_proposal": "首頁航線提案", "layout_proposal": "版面提案",
      "color_proposal": "主題提案", "model_proposal": "模型切換提案", "manual_claims": "手冊出處",
      "qa_claims": "問答出處", "report_draft": "報告草稿", "flight_notice": "飛控固定說明"}
ACTION_ZH = {"QUERY_AREA": "查詢巡檢區域（需要：區域 ID；產生：區域紀錄）",
             "GEN_COVERAGE": "生成覆蓋航點（需要：區域紀錄；產生：覆蓋航點）",
             "VERIFY_PREVIEW": "預覽驗算（需要：覆蓋航點；產生：預覽，含合格／不合格與預估電量）",
             "PROPOSE_HOME_ROUTE": "把航線放到首頁並開確認視窗（需要：合格的預覽；ID 用 U100）",
             "UI_LAYOUT_PROPOSE": "調整版面並開確認視窗（需要：一個參數 P，P001 不帶元件，其他 P 帶一個元件 C；params 填 value）",
             "UI_THEME_PROPOSE": "切換主題並開確認視窗（需要：一個主題 T）",
             "MODEL_SWITCH_PROPOSE": "切換模型或辨識類別並開確認視窗（需要：一個 M）",
             "MANUAL_SEARCH": "查手冊並附出處（不需要 ID）", "QA_LOOKUP": "查詢資料回答（不需要 ID）",
             "REPORT_DRAFT": "產生報告草稿（不需要 ID）", "DECLINE_FLIGHT": "回覆飛控需用指令區的固定說明（不需要 ID）"}


def have_from(artifacts, proposals):
    """由實際成果算出 {成果: 摘要}。"""
    A = artifacts or {}
    h = {}
    if "area_record" in A:
        h["area_record"] = f"{A['area_record'].get('id')}（{A['area_record'].get('ref')}）"
    if "coverage_route" in A:
        h["coverage_route"] = A["coverage_route"].get("ref")
    rp = A.get("route_preview")
    if rp:
        pct = rp.get("est_end_pct")
        h["route_preview"] = (f"{'合格' if rp.get('verdict') == 'pass' else '不合格'}，預估落地電量 {pct:.1f}%（預覽 {rp.get('ref')}）"
                              if pct is not None else f"{rp.get('verdict')}（預覽 {rp.get('ref')}）")
        if rp.get("verdict") == "pass":
            h["route_preview_pass"] = h["route_preview"]
    for p in proposals or []:
        key = {"ui": "home_proposal", "layout": "layout_proposal", "color": "color_proposal",
               "model": "model_proposal"}.get(p.get("direction"))
        if key:
            h[key] = f"{p['action']} {'、'.join(p['ids'])} {''.join(p['params'].values())}".strip()
    for k in ("manual_claims", "qa_claims", "report_draft", "flight_notice"):
        if k in A:
            h[k] = A[k].get("verdict") or "已產生"
    return h


def legit_skip(direction, have):
    """預覽不合格時，首頁提案屬合法略過。"""
    return direction == "ui" and "route_preview" in have and "route_preview_pass" not in have


def missing(direction, have):
    if legit_skip(direction, have):
        return []
    return [k for k in DIR_REQUIRED.get(direction, []) if k not in have]


def executable(direction, actions, have):
    """現在能做的動作：輸入都具備、而且產物還沒有。"""
    out = []
    for a in actions:
        if any(n not in have for n in NEEDS.get(a, [])):
            continue
        if PRODUCES.get(a) in have:
            continue
        out.append(a)
    return out


def summary(directions, have, statuses=None):
    """白話成果摘要（同時給提示與紀錄）。"""
    lines = []
    done = [f"{ZH[k]}：{v}" for k, v in have.items() if k != "route_preview_pass"]
    lines.append("已有：" + ("；".join(done) if done else "（還沒有任何成果）"))
    for d in directions:
        if legit_skip(d, have):
            lines.append(f"{d}：預覽不合格，依規則不放首頁（合法略過）")
            continue
        m = missing(d, have)
        if m:
            lines.append(f"{d} 還缺：" + "→".join(ZH[k] for k in m))
        else:
            lines.append(f"{d}：必要成果已齊")
    return "\n".join(lines)


def simulate(steps, have):
    """B 的執行前完整性：依步驟順序模擬產物（when 只要在成立的分支上可達）。回傳模擬後的 have 與缺輸入的步驟。"""
    h = dict(have)
    bad = []
    for s in steps:
        a = s["action"]
        need = NEEDS.get(a, [])
        if any(n not in h for n in need):
            bad.append((s["id"], [n for n in need if n not in h]))
            continue
        prod = PRODUCES.get(a)
        if prod:
            h[prod] = "（計畫中）"
        if a == "VERIFY_PREVIEW":
            h["route_preview_pass"] = "（計畫中：假設合格分支）"
    return h, bad
