"""ADR-0002 G0 第二輪覆核修正（CODEX-APP-0438，`proposals/CODEX/adr0002_g0_mail_0503_cli/findings.md`）。
規則版，開發自檢，不是正式 G1。竄改與崩潰一律在副本上做。"""
import os
import shutil
import threading
import unittest
from unittest import mock

from . import commit_layer as cl
from . import coverage as cv
from . import test_g0 as G0
from .energy import Vehicle, Wind
from .route_recheck import make_route_recheck
from .test_commit_layer import HOME, PTS, SQUARE, ok
from .test_commit_layer import Base as CLBase
from .test_g0 import rewrite
from .test_g0c import TV
from .test_preview_api import Base as PVBase


def ptr(root, ab):
    return os.path.join(root, "active", f"ptr-{ab}.json")


# ---------------- #1 被拒指標原樣保存、非物件尾行 ----------------
class PreserveRejected(CLBase):
    def _two(self):
        self.apply()
        cl.boot(self.root)
        dst = os.path.join(self.tmp, "p")
        shutil.copytree(self.root, dst)
        ptrs = sorted(cl.ActiveStore(dst).read_ptrs(), key=lambda x: -x[1]["seq"])
        return dst, ptrs[0], ptrs[1]

    def test_pointer_with_unverifiable_checkpoint_preserved_before_overwrite(self):
        dst, newest, older = self._two()
        with open(ptr(dst, newest[0]), "rb") as f:
            orig = f.read()
        p = os.path.join(dst, "active", f"seg-{newest[1]['segment_id']}", "checkpoint.jsonl")
        rewrite(p, lambda r: dict(r, data={"x": 1}) if r.get("part") == "slot_state" else r)
        c, rep = cl.boot(dst)
        saved = os.path.join(dst, "active", f"ptr-{newest[0]}.rejected-0.json")
        with open(saved, "rb") as f:
            self.assertEqual(f.read(), orig)                # 自身合法、但檢查點無法核證的那份，也整檔保留

    def test_oversized_pointer_preserved_whole(self):
        dst, newest, older = self._two()
        junk = b"z" * (cl.TEST_VALUES["pointer_read_cap_bytes"] * 3)
        with open(ptr(dst, newest[0]), "wb") as f:
            f.write(junk)
        c, rep = cl.boot(dst)
        with open(os.path.join(dst, "active", f"ptr-{newest[0]}.rejected-0.json"), "rb") as f:
            self.assertEqual(f.read(), junk)                # 不截斷

    def test_non_object_tail_line_in_previous_segment(self):
        self.apply()
        c, rep = cl.boot(self.root)
        dst = os.path.join(self.tmp, "t")
        shutil.copytree(self.root, dst)
        st = cl.ActiveStore(dst)
        prev = st.read_checkpoint(rep["segment"], st.best_ptr()[1]["checkpoint_hash"])["prev_segment_id"]
        with open(os.path.join(dst, "active", f"seg-{prev}", "coordinator.jsonl"), "ab") as f:
            f.write(b"[1, 2]\n")
        c2, rep2 = cl.boot(dst)                             # 不丟 AttributeError，照尾 hash 不符凍結
        self.assertIn("checkpoint_tail_hash_mismatch", rep2["frozen"])


# ---------------- #2 指標判定只讀一輪 ----------------
class SingleRead(CLBase):
    def test_boot_reads_pointer_status_once(self):
        self.apply()
        with mock.patch.object(cl.ActiveStore, "read_ptr_status", autospec=True,
                               side_effect=cl.ActiveStore.read_ptr_status) as m:
            c, rep = cl.boot(self.root)
        self.assertEqual(m.call_count, 1)
        self.assertGreater(rep["scan"]["lines"], 0)


# ---------------- #3 租約內重驗、BEFORE 行、undo 預留、回滾發布 ----------------
class LeaseRecheck(CLBase):
    def _hold_lease_then(self, fn, during):
        self.assertTrue(self.c.lease.acquire(timeout=1))
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", fn()))
        t.start()
        import time
        time.sleep(0.1)
        during()
        self.c.lease.release()
        t.join(10)
        return out["r"]

    def test_slot_frozen_while_waiting_lease(self):
        r = self._hold_lease_then(lambda: self.apply("t-f"),
                                  lambda: self.c._freeze("home", "test_freeze"))
        self.assertEqual(r["code"], "COMMIT_FROZEN")

    def test_same_tx_completed_while_waiting_returns_cached(self):
        seen = {"t-same": {"action": "WRITE", "tx_id": "t-same", "cached": True}}
        r = self._hold_lease_then(lambda: self.apply("t-same"), lambda: self.c.results.update(seen))
        self.assertTrue(r.get("cached"))

    def test_existing_root_as_before_line_checked(self):
        big = [{"id": str(i), "lat": 24.0, "lon": 121.0, "pad": "x" * 400} for i in range(300)]
        self.assertEqual(self.apply("t-big", points=big)["action"], "WRITE")
        cap = cl._line_len({"kind": "SNAPSHOT", "tx_id": "t-small", "role": "BEFORE", "slot_id": "home",
                            "root": self.c.word.current().route("home")}) - 1
        with TV(line_cap_bytes=cap):                        # 新航線很小，但既有根當 BEFORE 會超過
            r = self.apply("t-small")
        self.assertEqual(r["reasons"], ["encoded_line"])

    def test_undo_terminal_uses_reserve(self):
        self.apply("A")

        def squeeze():
            self.c.store.budget.disk_budget = self.c.store.budget.used() + 1024 * 1024
        self.hooks.actions["undo:before_publish"] = squeeze
        r = self.c.undo("u1")
        self.hooks.actions.clear()
        self.assertEqual(r["action"], "WRITE")

    def test_rollback_publish_failure_freezes(self):
        def fail():
            raise OSError("disk")
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = fail
        with mock.patch.object(self.c.word, "cas_gen", return_value=False):
            r = self.apply("t-rb")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.slot_state["home"]["state"], "FROZEN")


# ---------------- #4 耗盡後的發布 ----------------
class Exhaustion(CLBase):
    def _exhaust(self):
        self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
        try:
            self.c.ingest.event("policy", {"v": "x"})
        except cl.CommitError:
            pass

    def test_exhausted_after_P_marks_needs_reverify(self):
        self.hooks.actions["tx:after_cas"] = self._exhaust
        r = self.apply("t-p")
        self.hooks.actions.clear()
        self.assertEqual(r["action"], "WRITE")
        self.assertTrue(r["needs_reverify"])
        self.assertEqual(r["reasons"], ["W_EPOCH_EXHAUSTED"])

    def test_new_structure_transactions_rejected_after_exhaustion(self):
        self.apply("A")
        self._exhaust()
        self.assertEqual(self.c.ui_apply("x", {"l": 1})["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(self.c.undo("u")["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(self.apply("B")["code"], "W_EPOCH_EXHAUSTED")


class ServiceEntry(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def test_feeder_exhaustion_at_service_entry(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        self.coord.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
        self.sess.mission["no_fly"] = [{"id": "Z", "lat": 25.0, "lon": 122.0, "radius_m": 1.0}]   # 讓 poll 觸發新事件
        r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        self.assertEqual((r["transaction"]["action"], r["transaction"]["code"]), ("BLOCK", "W_EPOCH_EXHAUSTED"))
        self.assertEqual(self.svc.tokens[tok]["state"], "CONSUMED")
        self.assertIsNone(self.coord.word.current().route("home"))


# ---------------- #5 換版的同一臨界區 ----------------
class VersionSwitch(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def test_presented_waits_for_version_switch_then_stale(self):
        p = self.preview()
        ch1, tok1 = self._confirm(p, rev=1)
        out, started, gate = {}, threading.Event(), threading.Event()

        def pause():                                        # 換版在臨界區內暫停
            started.set()
            gate.wait(5)
        self.svc._pause = pause

        def switch():
            self.ep += 1
            b = {"boot_epoch": 7, "request_epoch": 10 ** 6, "session_id": self.sid, "preview_ref": p["preview_ref"],
                 "draft_id": "d1", "draft_rev": 2, "target_slot_id": "home",
                 "target_generation": self.coord.word.current().root_gen}
            out["sw"] = self.raw("POST", "/api/preview/apply_check", b)
        t = threading.Thread(target=switch)
        t.start()
        started.wait(5)
        del self.svc._pause
        acquired = self.svc.tok_lock.acquire(blocking=False)
        self.assertFalse(acquired)                          # 換版持有鎖時，其他人不能在中間核對或發證
        gate.set()
        t.join(10)
        self.ep = 10 ** 6
        js = self.call("/api/preview/presented", {"shown_hash": ch1["shown_hash"], "apply_intent_id": ch1["apply_intent_id"],
                                                  "target_slot_id": "home", "window_id": "w", "frame_id": "f"}, expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")
        self.assertEqual(self.svc.tokens[tok1]["state"], "REVOKED")

    def test_stale_generation_has_no_side_effect(self):
        p = self.preview()
        self._confirm(p, rev=1)
        before = dict(self.svc.current_preview)
        js = self.call("/api/preview/apply_check", {"preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": 5,
                                                    "target_slot_id": "home", "target_generation": 999}, expect=400)
        self.assertEqual(js["error"]["code"], "TARGET_STALE")
        self.assertEqual(self.svc.current_preview, before)

    def test_older_rev_on_other_preview_rejected(self):
        p1 = self.preview()
        self._confirm(p1, rev=3)
        p2 = self.preview(reserve=30)
        js = self.call("/api/preview/apply_check", {"preview_ref": p2["preview_ref"], "draft_id": "d1", "draft_rev": 2,
                                                    "target_slot_id": "home",
                                                    "target_generation": self.coord.word.current().root_gen}, expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")


# ---------------- #6 機型與定位 ----------------
class SnapshotVehicle(unittest.TestCase):
    def setUp(self):
        g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        self.rec = cv.preview_check(g, Vehicle(), Wind(), 90, 25, [])
        self.rc = make_route_recheck(self.rec, Vehicle(), {"reserve_req_pct": 25, "max_alt_m": 120})

    def S(self, **kw):
        s = {"battery": 90.0, "wind": {"speed_mps": 0.0, "from_deg": 0.0}, "no_fly": [],
             "limits": {"reserve_req_pct": 25, "max_alt_m": 120}, "position": (0.0, 0.0)}
        s.update(kw)
        return s

    def test_full_vehicle_in_snapshot_is_used(self):
        v = Vehicle(airframe_profile={"type": "multirotor", "power": {}}).to_dict()
        self.assertEqual(self.rc(self.S(vehicle=v))["domain"], "airframe_not_legacy_multirotor")
        small = Vehicle(battery_wh=1.0).to_dict()           # 快照中的機型容量很小 → 上界用它，擋下
        v2 = self.rc(self.S(vehicle=small))
        self.assertEqual(v2["action"], "BLOCK")
        self.assertTrue(set(v2["reasons"]) & {"BATTERY_BELOW_RESERVE", "JOINT_MARGIN_BATTERY"})

    def test_identity_mismatch_and_missing(self):
        self.assertEqual(self.rc(self.S(vehicle={"id": "OTHER"}))["domain"], "vehicle_mismatch")
        self.assertEqual(self.rc(self.S(vehicle=None))["domain"], "vehicle_missing")

    def test_position_required(self):
        self.assertEqual(self.rc(self.S(position=None))["domain"], "position_missing_or_nonfinite")


if __name__ == "__main__":
    unittest.main()
