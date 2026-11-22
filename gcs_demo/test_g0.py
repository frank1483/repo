"""ADR-0002 G0 契約稿 v1 的配套案例（arch_review/rounds/adr0002_G0_evidence_20261123/G0_契約稿_v1.md）。
規則版，不需要真模型。這是開發自檢，不是正式 G1。崩潰案例一律在副本上跑啟動恢復。"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from . import commit_layer as cl
from . import coverage as cv
from .energy import Vehicle, Wind
from .route_recheck import make_route_recheck
from .test_commit_layer import PTS, SQUARE, HOME, ll, ok, seed
from .test_commit_layer import Base as CLBase
from .test_preview_api import Base as PVBase


def rewrite(path, fn):
    """依 fn(rec)→rec|None 改寫 journal（每行重算 sha256，讓行本身合法；None＝刪除）。"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rec = fn(rec)
            if rec is None:
                continue
            body = {k: v for k, v in rec.items() if k != "sha256"}
            body["sha256"] = cl._sha(body)
            out.append(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)


def seg_file(root, name):
    seg = cl.ActiveStore(root).best_ptr()[1]["segment_id"]
    return os.path.join(root, "active", f"seg-{seg}", name)


# ---------------- G0-2 ----------------
class IngestPending(CLBase):
    def _blocked_writer(self, src, value, gate, exc=None):
        h = cl.Hooks()
        started = threading.Event()

        def wait():
            started.set()
            gate.wait(5)
        h.actions[f"ingest:{src}:announced"] = wait
        if exc:
            def boom():
                raise exc
            h.actions[f"ingest:{src}:before_write"] = boom
        err = []

        def run():
            try:
                self.c.ingest.event(src, value, h)
            except Exception as e:  # noqa: BLE001
                err.append(e)
        t = threading.Thread(target=run)
        t.start()
        started.wait(5)
        return t, err

    def test_same_source_two_writers_interleaved(self):
        gate = threading.Event()
        t, _ = self._blocked_writer("no_fly", [{"id": "A"}], gate)
        self.c.ingest.event("no_fly", [{"id": "B"}])        # 第二個 writer 先寫完
        st = self.c.ingest._state["no_fly"]
        self.assertEqual(st["pending"], 1)
        self.assertFalse(st["ready"])                       # 舊版會在這裡誤判為就緒
        with self.assertRaises(cl.CommitError):
            self.c.ingest.snapshot(timeout_ms=50)
        gate.set()
        t.join()
        self.assertTrue(st["ready"])

    def test_same_source_out_of_order_completion_keeps_newer(self):
        gate = threading.Event()
        t, _ = self._blocked_writer("no_fly", [{"id": "OLD"}], gate)
        self.c.ingest.event("no_fly", [{"id": "NEW"}])
        gate.set()
        t.join()
        _, S = self.c.ingest.snapshot(timeout_ms=200)
        self.assertEqual(S["no_fly"], [{"id": "NEW"}])

    def test_writer_abnormal_exit_keeps_source_not_ready(self):
        gate = threading.Event()
        gate.set()
        t, err = self._blocked_writer("policy", {"v": 9}, gate, exc=RuntimeError("crash"))
        t.join()
        self.assertTrue(err)
        st = self.c.ingest._state["policy"]
        self.assertTrue(st["stale"])
        self.assertFalse(st["ready"])
        r = self.apply()
        self.assertEqual((r["action"], r["code"]), ("BLOCK", "INPUT_NOT_CURRENT"))
        self.c.ingest.event("policy", {"v": 10})            # 之後更新的寫入成功 → 恢復就緒
        self.assertTrue(st["ready"])
        self.assertEqual(self.apply("t2")["action"], "WRITE")


# ---------------- G0-3 ----------------
class JointEpsilon(unittest.TestCase):
    def setUp(self):
        self.g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        self.rec = cv.preview_check(self.g, Vehicle(), Wind(), 90, 25, [])
        self.base = {"reserve_req_pct": 25, "max_alt_m": 120}

    def S(self, battery, speed=3.0, frm=0.0, no_fly=None):
        return {"battery": battery, "wind": {"speed_mps": speed, "from_deg": frm}, "no_fly": no_fly or [],
                "limits": {"reserve_req_pct": 25, "max_alt_m": 120}, "position": (0, 0)}

    def _edge_battery(self, rc, speed=3.0, frm=0.0):
        """找出剛好通過的最低起飛電量（0.1 個百分點步進）。"""
        b = 100.0
        while b > 26 and rc(self.S(b - 0.1, speed, frm))["action"] != "BLOCK":
            b -= 0.1
        return round(b, 1)

    def test_combined_epsilon_wind_speed(self):
        no = make_route_recheck(self.rec, Vehicle(), self.base, eps={"wind_speed": 0.0, "wind_dir": 0.0})
        yes = make_route_recheck(self.rec, Vehicle(), self.base, eps={"wind_speed": 3.0, "wind_dir": 0.0})
        b = self._edge_battery(no)
        self.assertNotEqual(no(self.S(b))["action"], "BLOCK")
        self.assertEqual(yes(self.S(b))["reasons"], ["JOINT_MARGIN_BATTERY"])   # 風速多 ε → 擋下

    def test_combined_epsilon_wind_direction(self):
        no = make_route_recheck(self.rec, Vehicle(), self.base, eps={"wind_speed": 0.0, "wind_dir": 0.0})
        yes = make_route_recheck(self.rec, Vehicle(), self.base, eps={"wind_speed": 0.0, "wind_dir": 90.0})
        b_no = self._edge_battery(no, speed=6.0, frm=0.0)
        b_yes = self._edge_battery(yes, speed=6.0, frm=0.0)
        self.assertGreaterEqual(b_yes, b_no)               # 風向 ±ε 取最壞 → 需要的電量不會比較少
        self.assertEqual(yes(self.S(b_yes - 0.1, 6.0, 0.0))["reasons"], ["JOINT_MARGIN_BATTERY"])

    def test_combined_epsilon_position_nfz_buffer(self):
        def crosses(r, eps_pos):
            z = [{"id": "Z", **ll(50, -30), "radius_m": r}]
            rc = make_route_recheck(self.rec, Vehicle(), self.base, eps={"position_m": eps_pos})
            return rc(self.S(95, no_fly=z))["action"] == "BLOCK"
        r = 0.0
        while not crosses(r, 0.0) and r < 80:
            r += 0.5
        self.assertTrue(r < 80)
        self.assertFalse(crosses(r - 3.0, 0.0))            # 外擴前不穿越
        self.assertTrue(crosses(r - 3.0, 5.0))             # 定位 ε＝5 m 外擴後穿越 → 擋下

    def test_finalize_attempts_exhausted_blocks(self):
        tmp = tempfile.mkdtemp(prefix="g0_fin_")
        try:
            root = os.path.join(tmp, "s")
            h = cl.Hooks()
            cl.init_store(root, h)
            c, _ = cl.boot(root, h)
            seed(c)
            n = []
            h.actions["tx:before_cas"] = lambda: c.ingest.event("policy", {"n": len(n)})

            def rc(S):
                n.append(1)
                return ok(S)
            r = c.route_apply("t", "home", "r", PTS, "d1", 1, rc)
            self.assertEqual((r["action"], r["code"]), ("BLOCK", "INPUT_NOT_CURRENT"))
            self.assertEqual(len(n), cl.TEST_VALUES["max_finalize_attempts"])
            self.assertIsNone(c.word.current().route("home"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------- G0-4、G0-6 ----------------
class BootRecovery(CLBase):
    def _aborted_store(self):
        self.apply("A")
        r = self.apply("B", recheck=lambda S: {"action": "BLOCK", "reasons": ["X"]})
        self.assertEqual(r["action"], "BLOCK")
        dst = os.path.join(self.tmp, "ab")
        shutil.copytree(self.root, dst)
        return dst

    def test_aborted_end_without_kind_terminal_uses_before_with_recovery(self):
        dst = self._aborted_store()
        rewrite(seg_file(dst, "route.jsonl"), lambda r: None if (r["kind"], r["tx_id"]) == ("ABORTED", "B") else r)
        rewrite(seg_file(dst, "coordinator.jsonl"),
                lambda r: dict(r, kind_terminal_sha=None) if r["kind"] == "END" and r["tx_id"] == "B" else r)
        c, rep = cl.boot(dst)
        self.assertEqual(c.word.current().route("home")["route_id"], "r-A")
        self.assertNotIn("home", {k for k, v in c.slot_state.items() if v["state"] == "FROZEN"})
        self.assertTrue(any(x.get("why") == "aborted_without_kind_terminal" for x in rep["recovery"]))
        recs, _ = cl.Journal.read(seg_file(dst, "coordinator.jsonl"))
        self.assertTrue(any(r["kind"] == "RECOVERY" and r["tx_id"] == "B" for r in recs))

    def test_aborted_terminal_hash_mismatch_freezes(self):
        dst = self._aborted_store()
        rewrite(seg_file(dst, "route.jsonl"),
                lambda r: dict(r, reasons=["TAMPERED"]) if (r["kind"], r["tx_id"]) == ("ABORTED", "B") else r)
        c, rep = cl.boot(dst)
        self.assertEqual(c.slot_state["home"]["state"], "FROZEN")
        self.assertEqual(c.slot_state["home"]["reason"], "aborted_mismatch")

    def test_aborted_end_claims_missing_terminal_freezes(self):
        dst = self._aborted_store()
        rewrite(seg_file(dst, "route.jsonl"), lambda r: None if (r["kind"], r["tx_id"]) == ("ABORTED", "B") else r)
        c, _ = cl.boot(dst)
        self.assertEqual(c.slot_state["home"]["reason"], "aborted_terminal_missing")

    def test_begin_without_end_writes_recovery(self):
        def boom():
            raise cl.SimulatedCrash("x")
        self.hooks.actions["tx:after_prepared"] = boom
        with self.assertRaises(cl.SimulatedCrash):
            self.apply("C")
        self.hooks.actions.clear()
        if self.c.lease.locked():
            self.c.lease.release()
        dst = os.path.join(self.tmp, "be")
        shutil.copytree(self.root, dst)
        cl.boot(dst)
        recs, _ = cl.Journal.read(seg_file(dst, "coordinator.jsonl"))
        self.assertTrue(any(r["kind"] == "RECOVERY" and r["why"] == "begin_without_end" for r in recs))

    def _listing(self, root):
        out = {}
        for d, _, fs in os.walk(root):
            for f in fs:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, root)] = cl.hashlib.sha256(fh.read()).hexdigest()
        return out

    def test_both_pointers_invalid_boots_restricted_read_only(self):
        self.apply()
        dst = os.path.join(self.tmp, "ro")
        shutil.copytree(self.root, dst)
        for ab in "AB":
            p = os.path.join(dst, "active", f"ptr-{ab}.json")
            if os.path.exists(p):
                with open(p, "ab") as f:
                    f.write(b"x")
        c, rep = cl.boot(dst)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertTrue(c.read_only)
        self.assertEqual(c.route_apply("t9", "home", "r9", PTS, "d1", 1, ok)["code"], "STORE_READ_ONLY")
        self.assertEqual(c.undo("u9")["code"], "STORE_READ_ONLY")
        self.assertEqual(c.ui_apply("x9", {"l": 1})["code"], "STORE_READ_ONLY")
        self.assertTrue({d["result"] for d in rep["diagnostics"]["pointers"]} <= {"hash_mismatch", "unreadable", "missing"})
        self.assertTrue(rep["diagnostics"]["segments"])

    def test_restricted_mode_writes_nothing(self):
        self.apply()
        dst = os.path.join(self.tmp, "ro2")
        shutil.copytree(self.root, dst)
        for ab in "AB":
            p = os.path.join(dst, "active", f"ptr-{ab}.json")
            if os.path.exists(p):
                with open(p, "wb") as f:
                    f.write(b"{bad")
        before = self._listing(dst)
        c, _ = cl.boot(dst)
        c.route_apply("t9", "home", "r9", PTS, "d1", 1, ok)
        self.assertEqual(self._listing(dst), before)

    def test_blank_store_requires_init(self):
        dst = os.path.join(self.tmp, "blank")
        os.makedirs(os.path.join(dst, "active"))
        with self.assertRaises(cl.CommitError) as e:
            cl.boot(dst)
        self.assertEqual(e.exception.code, "STORE_UNINITIALIZED")


# ---------------- G0-7、G0-8 ----------------
class CheckpointFaults(CLBase):
    def _crash_boot(self, point, nth=1):
        self.apply()
        dst = os.path.join(self.tmp, "ck-" + point.replace(":", "_") + str(nth))
        shutil.copytree(self.root, dst)
        base_seg = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        h = cl.Hooks()
        cnt = []

        def boom():
            cnt.append(1)
            if len(cnt) == nth:
                raise cl.SimulatedCrash(point)
        h.actions[point] = boom
        with self.assertRaises(cl.SimulatedCrash):
            cl.boot(dst, h)
        chosen = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        c2, _ = cl.boot(dst)
        return base_seg, chosen, c2

    def _check_old(self, point, nth=1):
        base, chosen, c2 = self._crash_boot(point, nth)
        self.assertEqual(chosen, base)                      # 指標仍指舊分段
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-t1")

    def test_crash_mid_checkpoint_chunks(self):
        self._check_old("before_write:checkpoint.jsonl:CHUNK", nth=2)

    def test_crash_before_manifest_durable(self):
        self._check_old("fsync:checkpoint.jsonl:CHECKPOINT_MANIFEST")

    def test_crash_after_manifest_before_pointer(self):
        self._check_old("ptr:before_write")

    def test_crash_before_pointer_replace(self):
        self._check_old("ptr:before_replace")

    def test_crash_after_pointer_replace(self):
        base, chosen, c2 = self._crash_boot("ptr:after_replace")
        self.assertNotEqual(chosen, base)                   # 指標已切到新分段
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-t1")

    def test_multi_slot_checkpoint_exceeds_line_cap_recovers(self):
        big = [{"id": str(i), "lat": 24.0, "lon": 121.0, "pad": "x" * 200} for i in range(400)]
        for s in ("home", "slot2", "slot3"):
            r = self.c.route_apply("t-" + s, s, "r-" + s, big, "d1", 1, ok)
            self.assertEqual(r["action"], "WRITE")
        c1, rep1 = cl.boot(self.root)
        p = os.path.join(self.root, "active", f"seg-{rep1['segment']}", "checkpoint.jsonl")
        self.assertGreater(os.path.getsize(p), cl.TEST_VALUES["line_cap_bytes"])   # 合計超過單行上限
        c2, _ = cl.boot(self.root)
        for s in ("home", "slot2", "slot3"):
            self.assertEqual(c2.word.current().route(s)["route_id"], "r-" + s)


# ---------------- G0-9、G0-11 ----------------
class TokenRevocation(PVBase):
    def _confirm(self, p, rev=1):
        ch = self.call("/api/preview/apply_check", {"preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": rev,
                                                    "target_slot_id": "home",
                                                    "target_generation": self.coord.word.current().root_gen})["data"]["check"]
        tok = self.call("/api/preview/presented", {"shown_hash": ch["shown_hash"], "apply_intent_id": ch["apply_intent_id"],
                                                   "target_slot_id": "home", "window_id": "w1", "frame_id": "f1"})["data"]
        return ch, tok["confirm_token"]

    def body(self, ch, tok, nonce="n1"):
        return {"target_slot_id": "home", "nonce": nonce, "apply_intent_id": ch["apply_intent_id"],
                "shown_hash": ch["shown_hash"], "confirm_token": tok}

    def test_superseded_by_new_preview_revokes_tokens(self):
        p1 = self.preview()
        ch1, tok1 = self._confirm(p1)
        p2 = self.preview(reserve=30)                       # 輸入不同 → 新的預覽 ID
        self.assertNotEqual(p1["preview_ref"], p2["preview_ref"])
        self.call("/api/preview/apply_check", {"preview_ref": p2["preview_ref"], "draft_id": "d1", "draft_rev": 1,
                                               "target_slot_id": "home",
                                               "target_generation": self.coord.word.current().root_gen})
        js = self.call("/api/preview/commit", self.body(ch1, tok1), expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_superseded_while_waiting_lease_blocks_commit(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.assertTrue(self.coord.lease.acquire(timeout=1))
        out = {}

        def run():
            self.ep += 1
            b = dict({"boot_epoch": 7, "request_epoch": self.ep, "session_id": self.sid}, **self.body(ch, tok))
            out["r"] = self.raw("POST", "/api/preview/commit", b)
        t = threading.Thread(target=run)
        t.start()
        for _ in range(500):                                 # 等提交受理（權杖轉 INFLIGHT）且卡在租約
            if self.svc.tokens[tok]["state"] == "INFLIGHT":
                break
            time.sleep(0.01)
        time.sleep(0.1)
        self.svc.supersede_preview(p["preview_ref"], "test")
        self.coord.lease.release()
        t.join(10)
        st, js, _ = out["r"]
        self.assertEqual(js["data"]["transaction"]["action"], "BLOCK")
        self.assertEqual(js["data"]["transaction"]["code"], "CONFIRM_TOKEN_STALE")
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_superseded_during_recheck_blocks_commit(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.coord.hooks.actions["tx:after_recheck"] = lambda: self.svc.supersede_preview(p["preview_ref"], "test")
        r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.coord.hooks.actions.clear()
        self.assertEqual((r["transaction"]["action"], r["transaction"]["code"]), ("BLOCK", "CONFIRM_TOKEN_STALE"))
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_superseded_after_P_keeps_committed(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.coord.hooks.actions["tx:after_cas"] = lambda: self.svc.supersede_preview(p["preview_ref"], "test")
        r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.coord.hooks.actions.clear()
        self.assertEqual(r["transaction"]["action"], "WRITE")
        self.assertIsNotNone(self.coord.word.current().route("home"))
        self.assertEqual(self.svc.tokens[tok]["state"], "CONSUMED")

    def test_expired_token_rejected_at_accept(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        real = self.svc.now
        self.svc.now = lambda: real() + 601
        js = self.call("/api/preview/commit", self.body(ch, tok), expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_token_expires_before_publish_blocks(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        real = self.svc.now

        def expire():
            self.svc.now = lambda: real() + 601
        self.coord.hooks.actions["tx:after_recheck"] = expire
        r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.coord.hooks.actions.clear()
        self.assertEqual((r["transaction"]["action"], r["transaction"]["code"]), ("BLOCK", "CONFIRM_TOKEN_STALE"))
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_completed_idempotent_resend_after_expiry_returns_original(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        r1 = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.assertEqual(r1["transaction"]["action"], "WRITE")
        real = self.svc.now
        self.svc.now = lambda: real() + 601
        r2 = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.assertEqual(r1, r2)
        js = self.call("/api/preview/commit", dict(self.body(ch, tok), shown_hash="x" * 64), expect=400)
        self.assertEqual(js["error"]["code"], "NONCE_CONFLICT")


# ---------------- G0-10 ----------------
class CancelConfirm(unittest.TestCase):
    def _parked(self):
        from .agent_controller import Controller
        from .test_agent_controller import FakeModel, Tools, allowed_of

        def raw(call):
            if "回覆的意圖" in call["messages"][1]["content"]:
                return '{"value":"CANCEL"}'
            al = allowed_of(call)
            work = [a for a in al if a not in ("FINISH", "HOLD")]
            return json.dumps({"value": work[0] if work else "FINISH"})
        c = Controller(Tools(area="NONE"), FakeModel(["plan"], raw=raw))
        r = c.request("北側巡檢")
        q0 = r["questions"]
        self.assertTrue(q0)
        r2 = c.resume_text(r["task_id"], "算了不要了")
        self.assertEqual(r2["questions"][0]["field"], "cancel_confirm")
        return c, r["task_id"], r["status"], q0

    def test_cancel_confirm_false_restores_original_question(self):
        c, tid, s0, q0 = self._parked()
        r3 = c.resume(tid, [{"field": "cancel_confirm", "value": False}])
        self.assertEqual(r3["status"], s0)
        self.assertEqual(r3["questions"], q0)

    def test_cancel_confirm_expiry_respected(self):
        c, tid, _, _ = self._parked()
        real = c.clock
        c.clock = lambda: real() + 601
        r3 = c.resume(tid, [{"field": "cancel_confirm", "value": False}])
        self.assertEqual(r3["status"], "EXPIRED")
        self.assertEqual(r3["questions"], [])


if __name__ == "__main__":
    unittest.main()
