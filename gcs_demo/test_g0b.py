"""ADR-0002 G0 契約稿 v2 的補件案例（Codex `G0_契約補件與覆核.md`，使用者 2026-11-23 02:31 指示先處理三處）。
規則版，開發自檢，不是正式 G1。崩潰與竄改一律在副本上做。"""
import json
import os
import shutil
import threading
import unittest

from . import commit_layer as cl
from . import coverage as cv
from .energy import Vehicle, Wind, bearing_rad, leg_estimate
from .route_recheck import headwind_bound_end_pct, make_route_recheck
from .test_commit_layer import HOME, PTS, SQUARE, ok
from .test_commit_layer import Base as CLBase
from . import test_g0 as G0
from .test_g0 import rewrite, seg_file
from .test_preview_api import Base as PVBase


def all_records(root, name):
    out = []
    base = os.path.join(root, "active")
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d, name)
        if d.startswith("seg-") and os.path.exists(p):
            out += [dict(r, _seg=d) for r in cl.Journal.read(p)[0]]
    return out


def listing(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = cl.hashlib.sha256(fh.read()).hexdigest()
    return out


# ---------------- G0-3：方向無關的保守上界 ----------------
class HeadwindBound(unittest.TestCase):
    def setUp(self):
        self.g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        self.rec = cv.preview_check(self.g, Vehicle(), Wind(), 90, 25, [])
        self.reserve = self.rec["reserve_eff_pct"] if "reserve_eff_pct" in self.rec else 25

    def test_bound_leg_airspeed_is_ground_plus_wind(self):
        pts = self.rec["route"]
        for a, b in zip(pts, pts[1:]):
            pa, pb = (a["lat"], a["lon"]), (b["lat"], b["lon"])
            e = leg_estimate(Vehicle(), pa, pb, 0, 0, 8.0, Wind(6.0, __import__("math").degrees(bearing_rad(pa, pb))))
            if e["dist_m"] >= 0.5:
                self.assertAlmostEqual(e["v_air"], 14.0, places=6)

    def test_bound_covers_every_direction(self):
        """對 0°～355°（每 5°）與兩種風速，實際估算的落地電量都 ≥ 上界（上界不會比任何方向樂觀）。"""
        for w in (3.0, 6.0):
            bound = headwind_bound_end_pct(self.rec["route"], Vehicle(), w, 90.0, 25.0)
            for d in range(0, 360, 5):
                chk = cv.apply_check(self.rec, vehicle=Vehicle(), wind=Wind(w, float(d)), takeoff_pct=90.0,
                                     reserve_req_pct=25.0, no_fly=[])
                self.assertGreaterEqual(chk["evaluation"]["est_end_pct"] + 1e-9, bound, (w, d))

    def test_recheck_uses_bound_not_samples(self):
        base = {"reserve_req_pct": 25, "max_alt_m": 120}
        rc = make_route_recheck(self.rec, Vehicle(), base)
        S = {"battery": 90.0, "wind": {"speed_mps": 3.0, "from_deg": 0.0}, "no_fly": [],
             "limits": {"reserve_req_pct": 25, "max_alt_m": 120}, "position": (0, 0)}
        e = cl.TEST_VALUES["eps"]
        bound = headwind_bound_end_pct(self.rec["route"], Vehicle(), 3.0 + e["wind_speed"], 90.0 - e["battery"], 25.0)
        need = 25.0 + cl.TEST_VALUES["joint_margin_battery_pct"]
        S2 = dict(S, battery=90.0 - (bound - need) - 0.05)    # 讓上界剛好低於門檻一點點
        v = rc(S2)
        self.assertEqual(v["reasons"], ["JOINT_MARGIN_BATTERY"])
        self.assertLess(v["worst_end_pct"], need)

    def test_non_legacy_airframe_unverified_blocks(self):
        vp = Vehicle(airframe_profile={"type": "fixed_wing", "power": {}})
        self.assertIsNone(headwind_bound_end_pct(self.rec["route"], vp, 3.0, 90.0, 25.0))


# ---------------- G0-4：RECOVERY 在新指標啟用前持久化 ----------------
class RecoveryBeforePointer(CLBase):
    def _store(self):
        self.apply("A")
        self.apply("B", recheck=lambda S: {"action": "BLOCK", "reasons": ["X"]})
        dst = os.path.join(self.tmp, "rb")
        shutil.copytree(self.root, dst)
        rewrite(seg_file(dst, "route.jsonl"), lambda r: None if (r["kind"], r["tx_id"]) == ("ABORTED", "B") else r)
        rewrite(seg_file(dst, "coordinator.jsonl"),
                lambda r: dict(r, kind_terminal_sha=None) if r["kind"] == "END" and r["tx_id"] == "B" else r)
        return dst

    def _crash(self, dst, point):
        h = cl.Hooks()

        def boom():
            raise cl.SimulatedCrash(point)
        h.actions[point] = boom
        with self.assertRaises(cl.SimulatedCrash):
            cl.boot(dst, h)

    def _recovery_in_active(self, root):
        seg = cl.ActiveStore(root).best_ptr()[1]["segment_id"]
        recs, _ = cl.Journal.read(os.path.join(root, "active", f"seg-{seg}", "coordinator.jsonl"))
        return [r for r in recs if r["kind"] == "RECOVERY" and r["tx_id"] == "B"]

    def test_crash_between_recovery_and_pointer_redoes_recovery(self):
        dst = self._store()
        self._crash(dst, "ptr:before_write")            # RECOVERY 已寫進未啟用的新分段，指標仍指舊分段
        c, rep = cl.boot(dst)                           # 第二次 BOOT 從舊分段重做恢復
        self.assertTrue(self._recovery_in_active(dst))
        self.assertEqual(c.word.current().route("home")["route_id"], "r-A")
        cl.boot(dst)                                    # 再一次 BOOT：恢復證據仍保留在先前啟用過的分段
        self.assertTrue(any(r["kind"] == "RECOVERY" and r["tx_id"] == "B"
                            for r in all_records(dst, "coordinator.jsonl")))

    def test_crash_after_pointer_keeps_recovery_evidence(self):
        dst = self._store()
        self._crash(dst, "ptr:after_replace")           # 指標已切換：新分段必須已含 RECOVERY
        self.assertTrue(self._recovery_in_active(dst))
        c, _ = cl.boot(dst)
        self.assertEqual(c.word.current().route("home")["route_id"], "r-A")


# ---------------- G0-6：指標結構與引用檢查點 ----------------
class PointerValidation(CLBase):
    def _rewrite_ptr(self, root, ab, fn):
        p = os.path.join(root, "active", f"ptr-{ab}.json")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        rec = fn(rec)
        if isinstance(rec, dict):
            body = {k: v for k, v in rec.items() if k != "sha256"}
            rec = dict(body, sha256=cl._sha(body))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f)

    def _two_ptrs(self):
        self.apply()
        cl.boot(self.root)                              # 讓 A、B 兩份指標都存在
        dst = os.path.join(self.tmp, "pv")
        shutil.copytree(self.root, dst)
        ptrs = sorted(cl.ActiveStore(dst).read_ptrs(), key=lambda x: -x[1]["seq"])
        return dst, ptrs[0], ptrs[1]

    def test_pointer_bad_shape_rejected_even_with_valid_hash(self):
        dst, newest, older = self._two_ptrs()
        self._rewrite_ptr(dst, newest[0], lambda r: dict(r, segment_id=str(r["segment_id"])))
        self.assertEqual([ab for ab, _ in cl.ActiveStore(dst).read_ptrs()], [older[0]])
        self._rewrite_ptr(dst, older[0], lambda r: dict(r, extra=1))
        c, rep = cl.boot(dst)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual({d["result"] for d in rep["diagnostics"]["pointers"]}, {"bad_shape"})

    def test_pointer_referencing_unverifiable_checkpoint_falls_back(self):
        dst, newest, older = self._two_ptrs()
        seg = newest[1]["segment_id"]
        p = os.path.join(dst, "active", f"seg-{seg}", "checkpoint.jsonl")
        rewrite(p, lambda r: dict(r, data={"tampered": True}) if r.get("part") == "slot_state" else r)
        before = listing(os.path.join(dst, "active", f"seg-{seg}"))
        c, rep = cl.boot(dst)
        self.assertEqual(rep["pointer_rejected"][0]["segment_id"], seg)
        self.assertEqual(rep["pointer_rejected"][0]["reason"], "CHECKPOINT_INVALID")
        self.assertNotEqual(rep.get("mode"), "RESTRICTED_READ_ONLY")
        self.assertEqual(listing(os.path.join(dst, "active", f"seg-{seg}")), before)   # 無法核證的分段原樣保留

    def test_both_pointers_unverifiable_checkpoint_restricted(self):
        dst, newest, older = self._two_ptrs()
        for _, rec in (newest, older):
            p = os.path.join(dst, "active", f"seg-{rec['segment_id']}", "checkpoint.jsonl")
            with open(p, "ab") as f:
                f.write(b'{"junk": 1}\n')
        before = listing(dst)
        c, rep = cl.boot(dst)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual({d["result"] for d in rep["diagnostics"]["pointers"]}, {"checkpoint_unverifiable"})
        self.assertEqual(listing(dst), before)


# ---------------- G0-9／11：零生效的口徑 ----------------
class ZeroEffect(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def _store_root(self):
        return self.coord.store.root

    def test_rejected_at_accept_changes_no_file(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        real = self.svc.now
        self.svc.now = lambda: real() + 601
        before = listing(self._store_root())
        self.call("/api/preview/commit", self.body(ch, tok), expect=400)
        self.assertEqual(listing(self._store_root()), before)        # 受理時就拒絕：活動區完全不變

    def test_aborted_in_layer_keeps_slot_draft_undo_and_logs_abort(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        d0 = self.coord.word.current()
        self.coord.hooks.actions["tx:after_recheck"] = lambda: self.svc.supersede_preview(p["preview_ref"], "t")
        r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.coord.hooks.actions.clear()
        d1 = self.coord.word.current()
        self.assertEqual(r["transaction"]["code"], "CONFIRM_TOKEN_STALE")
        self.assertEqual((d1.root_gen, d1.route_roots, d1.undo_head), (d0.root_gen, d0.route_roots, d0.undo_head))
        recs = all_records(self._store_root(), "route.jsonl")
        tx = r["transaction"]["transaction_id"]
        ab = [x for x in recs if x["tx_id"] == tx and x["kind"] == "ABORTED"]
        self.assertEqual(ab[0]["reasons"], ["CONFIRM_TOKEN_STALE"])   # 原有的追加式稽核照常保留
        ends = [x for x in all_records(self._store_root(), "coordinator.jsonl")
                if x.get("tx_id") == tx and x["kind"] == "END"]
        self.assertEqual(ends[0]["outcome"], "ABORTED")


# ---------------- G0-2：ε 內樣本與超帶事件交錯 ----------------
class EpsilonInterleave(CLBase):
    def _block(self, fn, point):
        gate, started, h = threading.Event(), threading.Event(), cl.Hooks()

        def wait():
            started.set()
            gate.wait(5)
        h.actions[point] = wait
        t = threading.Thread(target=lambda: fn(h))
        t.start()
        started.wait(5)
        return gate, t

    def test_inband_sample_newer_than_pending_event_kept(self):
        gate, t = self._block(lambda h: self.c.ingest.sample("battery", 85.0, h), "ingest:battery:announced")
        self.c.ingest.sample("battery", 89.9)              # 參考值仍是 90 → ε 內樣本，序號比待寫事件新
        self.assertEqual(self.c.ingest._state["battery"]["pending"], 1)
        gate.set()
        t.join()
        _, S = self.c.ingest.snapshot(timeout_ms=200)
        self.assertEqual(S["battery"], 89.9)               # 較舊的事件晚寫完，不覆蓋較新的樣本

    def test_inband_sample_older_than_event_keeps_event(self):
        self.c.ingest.sample("battery", 89.8)              # 先確認是 ε 內樣本（參考值 90）
        self.assertEqual(self.c.ingest._state["battery"]["ref"], 90.0)
        gate, t = self._block(lambda h: self.c.ingest.sample("battery", 89.9, h), "ingest:battery:sample_before_write")
        self.c.ingest.sample("battery", 85.0)              # 超帶事件，序號較新
        gate.set()
        t.join()
        _, S = self.c.ingest.snapshot(timeout_ms=200)
        self.assertEqual(S["battery"], 85.0)               # 較舊的 ε 內樣本晚到，不覆蓋


if __name__ == "__main__":
    unittest.main()
