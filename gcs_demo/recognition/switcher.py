"""切換交易與復原。

流程：指令 → 場域（domain_profile.resolve_domain）→ 候選（selector）→ 提案（待使用者確認）
→ 確認後「先載入新模型並試跑一張測試畫面」，成功才換掉舊的；失敗就保留舊模型。
每次成功切換把前一狀態推進復原堆疊；undo 回到前一個場域與模型（重新驗證 SHA256 後載入）。
所有事件記成 JSON 列，給任務報告（功能2）用。
"""
from __future__ import annotations

import time

from ..domain_profile import load_classes, load_domains, resolve_domain
from . import drivers as D
from . import registry as R
from . import selector as S

TEST_FRAME = {"frame_id": "warmup", "objects": []}


class Switcher:
    def __init__(self, domains=None, model_dir=R.MODEL_DIR, backend=None, device="demo-host", clock=time.time):
        self.alias, self.class_zh = load_classes()
        self.domains = domains or load_domains()
        self.drivers = D.default_drivers(self.alias)
        self.model_dir, self.device, self.backend, self.clock = model_dir, device, backend, clock
        self.domain_id = None
        self.model_id = None
        self.session = None
        self.history = []
        self.events = []
        self.proposals = {}
        self._seq = 0

    # ---- 查詢 ----
    def rows(self):
        return R.scan(self.drivers, self.model_dir, self.device)

    def _log(self, kind, **kw):
        ev = {"t": round(self.clock(), 3), "kind": kind, "domain": self.domain_id, "model": self.model_id, **kw}
        self.events.append(ev)
        return ev

    # ---- 提案 ----
    def propose(self, text=None, domain_id=None):
        t0 = time.perf_counter()
        if domain_id is None:
            res = resolve_domain(text, self.domains)
            if res["decision"] == "CLARIFY":
                ms = round((time.perf_counter() - t0) * 1000, 3)
                self._log("clarify", text=text, judge_ms=ms)
                return {"status": "CLARIFY", "resolution": res, "judge_ms": ms}
            domain_id = res["domain_id"]
        else:
            if domain_id not in self.domains:
                raise ValueError(f"未知場域 {domain_id}")
            res = {"decision": "SELECT", "domain_id": domain_id, "scores": {}, "hits": {}}
        domain = self.domains[domain_id]
        ev = S.evaluate(domain, self.rows(), self.alias, self.model_id, self.class_zh)
        model_id, source, reason, llm_rec = ev["choice"], "rule", ev["reason_zh"], None
        if ev["decision"] == "SELECT":
            model_id, source, reason, llm_rec = S.llm_pick(self.backend, domain, ev)
        status = ev["decision"] if model_id or ev["decision"] == "HOLD" else "HOLD"
        ms = round((time.perf_counter() - t0) * 1000, 3)
        self._seq += 1
        pid = f"P{self._seq}"
        prop = {"status": status, "proposal_id": pid, "resolution": res, "domain_id": domain_id,
                "domain_name_zh": domain["name_zh"], "ui_template": domain["ui_template"],
                "model_id": model_id if status != "HOLD" else self.model_id, "source": source,
                "reason_zh": reason, "evaluation": ev, "judge_ms": ms,
                "llm": {k: llm_rec.get(k) for k in ("ok", "error", "latency_s")} if llm_rec else None}
        self.proposals[pid] = prop
        self._log("propose", text=text, proposal=pid, to_domain=domain_id, to_model=prop["model_id"],
                  status=status, source=source, judge_ms=ms)
        return prop

    # ---- 套用（使用者按確認後）----
    def _load(self, model_id):
        row = next((r for r in self.rows() if r["id"] == model_id), None)
        if row is None or not row["installed"]:
            raise RuntimeError("模型不可用：" + ("；".join(row["problems"]) if row else "找不到"))
        m = row["manifest"]
        sess = self.drivers[m["runtime"]].load(m, row["path"])
        sess.infer(TEST_FRAME)  # 試跑：失敗會丟例外，舊模型不受影響
        return sess

    def apply(self, proposal_id):
        prop = self.proposals.pop(proposal_id, None)
        if prop is None:
            raise KeyError("提案不存在或已使用")
        if prop["status"] == "HOLD":
            # 沒有可用模型時仍切場域（UI 模板照切），辨識維持原模型
            self.history.append((self.domain_id, self.model_id))
            self.domain_id = prop["domain_id"]
            self._log("apply", proposal=proposal_id, ok=True, note="HOLD：只切場域，辨識模型不變")
            return {"ok": True, "domain_id": self.domain_id, "model_id": self.model_id}
        target = prop["model_id"]
        new_sess = self.session if target == self.model_id else None
        if new_sess is None:
            t0 = time.perf_counter()
            try:
                new_sess = self._load(target)
            except Exception as e:  # noqa: BLE001 - 任何載入錯誤都保留舊模型
                self._log("apply", proposal=proposal_id, ok=False, error=str(e))
                return {"ok": False, "error": str(e), "domain_id": self.domain_id, "model_id": self.model_id}
            load_ms = round((time.perf_counter() - t0) * 1000, 3)
        else:
            load_ms = 0.0
        self.history.append((self.domain_id, self.model_id))
        old = self.session
        self.session, self.domain_id, self.model_id = new_sess, prop["domain_id"], target
        if old is not None and old is not new_sess:
            old.close()
        self._log("apply", proposal=proposal_id, ok=True, load_ms=load_ms)
        return {"ok": True, "domain_id": self.domain_id, "model_id": self.model_id, "load_ms": load_ms}

    def undo(self):
        if not self.history:
            return {"ok": False, "error": "沒有可復原的切換"}
        prev_domain, prev_model = self.history[-1]
        try:
            sess = self._load(prev_model) if prev_model and prev_model != self.model_id else (
                self.session if prev_model else None)
        except Exception as e:  # noqa: BLE001
            self._log("undo", ok=False, error=str(e))
            return {"ok": False, "error": str(e)}
        self.history.pop()
        old = self.session
        self.session, self.domain_id, self.model_id = sess, prev_domain, prev_model
        if old is not None and old is not sess:
            old.close()
        self._log("undo", ok=True)
        return {"ok": True, "domain_id": self.domain_id, "model_id": self.model_id}

    # ---- 辨識 ----
    def detect(self, frame):
        """回傳與任務報告共用格式的辨識列；低於場域信心門檻的丟掉。"""
        if self.session is None:
            return []
        th = self.domains[self.domain_id]["recognition"]["conf_threshold"] if self.domain_id else 0.5
        out = []
        for d in self.session.infer(frame):
            if d["conf"] < th:
                continue
            out.append({"t": frame.get("t"), "frame_id": frame["frame_id"], "vehicle_id": frame.get("vehicle_id"),
                        "domain": self.domain_id, "model_id": self.model_id, "class": d["class"],
                        "class_zh": self.class_zh.get(d["class"], d["class"]), "conf": d["conf"],
                        "bbox": d["bbox"], "lat": frame.get("lat"), "lon": frame.get("lon"), "track_id": None})
        return out
