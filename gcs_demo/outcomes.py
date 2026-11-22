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


def layout_key(p):
    """提案的版面鍵：(元件或 None, 參數, 值)。"""
    cs = [i for i in p["ids"] if i.startswith("C")]
    ps = [i for i in p["ids"] if i.startswith("P")]
    return (cs[0] if cs else None, ps[0] if ps else None, p["params"].get("value"))


def have_from(artifacts, proposals, layout_items=None):
    """由實際成果算出 {成果: 摘要}。layout_items（v3.9 §3）＝原句解析出的必要版面項目；
    有項目時，全部項目都有 PROPOSED 提案才算「版面提案」已產生，缺項記在 _layout_missing。"""
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
    items = [tuple(x) for x in (layout_items or []) if x[1] and x[2]]
    if items:
        got = {layout_key(p) for p in proposals or [] if p.get("direction") == "layout" and p.get("state") == "PROPOSED"}
        miss = [x for x in items if x not in got]
        h.pop("layout_proposal", None)
        if miss:
            h["_layout_missing"] = miss
        else:
            h["layout_proposal"] = "、".join(f"{c or ''}{'＋' if c else ''}{pp}＝{v}" for c, pp, v in items)
    for k in ("manual_claims", "qa_claims", "report_draft", "flight_notice"):
        if k in A:
            v = A[k].get("verdict")
            h[k] = ("工具未接，沒有取得證據" if (k == "qa_claims" and v != "ok") else
                    "沒有找到相關片段" if (k == "manual_claims" and v != "ok") else v or "已產生")
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
    done = [f"{ZH[k]}：{v}" for k, v in have.items() if k not in ("route_preview_pass", "_layout_missing")]
    lines.append("已有：" + ("；".join(done) if done else "（還沒有任何成果）"))
    for d in directions:
        if legit_skip(d, have):
            lines.append(f"{d}：預覽不合格，依規則不放首頁（合法略過）")
            continue
        m = missing(d, have)
        if d == "layout" and have.get("_layout_missing"):
            lines.append("layout 還缺這些版面提案：" + "；".join(
                f"{c + '＋' if c else ''}{pp}，value＝{v}" for c, pp, v in have["_layout_missing"]))
        elif m:
            lines.append(f"{d} 還缺：" + "→".join(ZH[k] for k in m))
        else:
            lines.append(f"{d}：必要成果已齊")
    return "\n".join(lines)


def input_sig(action, have):
    """動作的輸入狀態（A 去重用）：該動作需要的輸入目前的值。"""
    return tuple((n, have.get(n)) for n in NEEDS.get(action, []))


def simulate_steps(steps, outs, have, known=()):
    """B 的執行前可達性（v4，CODEX-APP-0415）：分支條件沿「取得結果、條件、等待套用」三種相依傳遞；純順序（after）不傳。
    每個可達步驟帶一組「條件」{預覽步驟: pass／fail}＝自己的 when、需要合格預覽時對該預覽的 pass，
    再加上所有 bind／after／when 來源步驟的條件。同一個預覽同時要求 pass 與 fail → 沒有共同可達分支 → 不可達。
    已執行的預覽步驟用實際判定：條件和實際判定相反 → 不可達。
    steps＝依序的計畫步驟；outs＝已執行步驟的實際輸出 {step_id: {欄位: 值}}；have＝目前全域成果。
    回傳 (可達步驟的模擬產物 {step_id: set(成果)}, 不可達步驟 [(id, 原因)])。"""
    prod = {sid: set(o) for sid, o in (outs or {}).items()}
    cond = {sid: {} for sid in prod}
    actual = {}
    for sid, o in (outs or {}).items():
        rp = (o or {}).get("route_preview") or {}
        if rp.get("verdict") in ("pass", "fail"):
            actual[sid] = rp["verdict"]
            if rp["verdict"] == "pass":
                prod[sid].add("route_preview_pass")
    bad = []

    def merge(c, k, v):
        if c.get(k, v) != v:
            return f"同時要求 {k} 合格與不合格，沒有共同可達的分支"
        if actual.get(k, v) != v:
            return f"{k} 的實際預覽是{'合格' if actual[k] == 'pass' else '不合格'}，這個條件不會成立"
        c[k] = v
        return None

    for st in steps:
        sid, a = st["id"], st["action"]
        if sid in prod:
            continue
        why, c = None, {}
        srcs = set()                                      # v4：只有取得結果（bind）、條件（when）、等待套用（require）傳遞條件
        for x in st.get("after") or []:                   # after＝純順序：來源略過也算結束（同執行器 TERMINAL_OK），不傳條件
            if x not in prod and x not in known and not any(y["id"] == x for y in steps):
                why = f"after 指的 {x} 不存在"
        for x in (st.get("require") or {}):               # require：來源必須真的會產生提案，條件一路傳下來
            srcs.add(x)
        for slot, ref in (st.get("bind") or {}).items():
            src, field = ref.split(".", 1)
            srcs.add(src)
            if src not in prod or field not in prod[src]:
                why = f"bind {slot} 指的 {src}.{field} 不會產生"
                break
        when = st.get("when")
        if why is None and when:
            src, branch = when.split(".", 1)[0], when.rsplit("==", 1)[1]
            srcs.add(src)
            if src not in prod or "route_preview" not in prod[src]:
                why = f"when 指的 {src} 不會產生預覽"
            else:
                why = merge(c, src, branch)
        if why is None and "route_preview_pass" in NEEDS.get(a, []):
            src = ((st.get("bind") or {}).get("preview") or "").split(".", 1)[0]
            if not src or src not in prod:
                why = "需要合格預覽，但沒有 bind 到預覽步驟"
            else:
                why = merge(c, src, "pass")
                if why and "沒有共同" in why:
                    why = f"只在 {src} 不合格時才做，但這個動作需要 {src} 合格，永遠不會成立"
        if why is None:
            for x in srcs:                               # 來源步驟的條件一路傳下來
                if x not in prod:
                    why = f"引用的 {x} 不可達"
                    break
                for k, v in cond.get(x, {}).items():
                    why = merge(c, k, v)
                    if why:
                        break
                if why:
                    break
        if why is None:
            for n in NEEDS.get(a, []):
                if n == "route_preview_pass":
                    continue
                if not any(n in v for v in prod.values()) and n not in have:
                    why = f"缺輸入 {ZH[n]}"
        if why:
            bad.append((sid, why))
            continue
        p = {PRODUCES[a]} if a in PRODUCES else set()
        if a == "VERIFY_PREVIEW":
            p.add("route_preview_pass")                 # 合格分支可能（實際判定未知）
        prod[sid] = p
        cond[sid] = c
    return prod, bad


def simulate(steps, have):
    """（保留舊介面給既有測試）"""
    prod, bad = simulate_steps(steps, {}, have)
    h = dict(have)
    for v in prod.values():
        for k in v:
            h[k] = "（計畫中）"
    return h, [(i, [w]) for i, w in bad]
