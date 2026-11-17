"""ADR-0002 M1 提交層的固定案例（提交層演算法說明 v1 §8；G0 清單 A-1～A-4、B-3）。規則版，不需要真模型。
首次執行由 Claude 負責，結果與失敗原樣保留。崩潰案例一律在「副本」上跑啟動恢復，原目錄不動。"""
import json
import os
import shutil
import tempfile
import threading
import unittest

from . import commit_layer as cl
from . import coverage as cv
from .energy import Vehicle, Wind
from .planner import _to_ll
from .route_recheck import make_route_recheck

HOME = {"lat": 24.0, "lon": 121.0}
O = (24.0, 121.0)


def ll(x, y):
    a, b = _to_ll(O, (x, y))
    return {"lat": a, "lon": b}


SQUARE = [ll(0, 0), ll(100, 0), ll(100, 100), ll(0, 100)]
PTS = [{"id": "H", "lat": 24.0, "lon": 121.0}]


def ok(_S):
    return {"action": "WRITE", "reasons": []}


def seed(c, battery=90.0):
    c.ingest.event("no_fly", [])
    c.ingest.event("policy", {"v": 1})
    c.ingest.event("limits", {"reserve_req_pct": 25, "max_alt_m": 120})
    c.ingest.event("area", {"id": "A1"})
    c.ingest.event("vehicle", {"id": "UAV-01"})
    c.ingest.event("battery", battery)
    c.ingest.event("wind", {"speed_mps": 0.0, "from_deg": 0.0})
    c.ingest.event("position", (0.0, 0.0))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cl_")
        self.root = os.path.join(self.tmp, "store")
        self.hooks = cl.Hooks()
        cl.init_store(self.root, self.hooks)
        self.c, _ = cl.boot(self.root, self.hooks)
        seed(self.c)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def apply(self, tx="t1", slot="home", recheck=ok, points=None):
        return self.c.route_apply(tx, slot, "r-" + tx, points or PTS, "d1", 1, recheck)

    def copy_and_boot(self, name="copy"):
        dst = os.path.join(self.tmp, name)
        shutil.copytree(self.root, dst)
        return cl.boot(dst), dst


class Basic(Base):
    def test_apply_publishes_route_and_undo_together(self):
        r = self.apply()
        self.assertEqual(r["action"], "WRITE")
        d = self.c.word.current()
        self.assertEqual(d.route("home")["route_id"], "r-t1")
        self.assertEqual(d.undo_head.entry["tx_id"], "t1")
        self.assertEqual(d.undo_head.entry["after"], d.route("home"))

    def test_idempotent_tx(self):
        self.assertIs(self.apply(), self.apply())

    def test_redisplay_and_block_do_not_switch(self):
        g0 = self.c.word.current().root_gen
        r = self.apply("t2", recheck=lambda S: {"action": "REDISPLAY", "reasons": ["DIFF"]})
        self.assertEqual(r["action"], "REDISPLAY")
        r = self.apply("t3", recheck=lambda S: {"action": "BLOCK", "reasons": ["NFZ_CROSSING"]})
        self.assertEqual(r["action"], "BLOCK")
        self.assertEqual(self.c.word.current().root_gen, g0)
        self.assertIsNone(self.c.word.current().route("home"))

    def test_checkpoint_exceeds_single_line_cap(self):
        big = [{"id": str(i), "lat": 24.0, "lon": 121.0, "pad": "x" * 200} for i in range(2000)]
        r = self.apply("big", points=big)
        self.assertEqual(r["action"], "BLOCK")
        self.assertEqual(r["code"], "LIMIT_EXCEEDED")
        self.assertIsNone(self.c.word.current().route("home"))


class Ingest(Base):
    def test_band_event_only_beyond_epsilon(self):
        n = self.c.ingest.events
        self.c.ingest.sample("battery", 89.8)
        self.assertEqual(self.c.ingest.events, n)
        self.c.ingest.sample("battery", 89.4)
        self.assertEqual(self.c.ingest.events, n + 1)

    def test_multiple_ingest_writers_contend(self):
        _, s0 = self.c.word.read()

        def w():
            for i in range(500):
                self.c.ingest.event("policy", {"v": i})
        ts = [threading.Thread(target=w) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(self.c.word.read()[1], s0 + 4000)

    def test_coherent_source_snapshot(self):
        stop = threading.Event()

        import time

        def w():
            n = 0
            while not stop.is_set():
                n += 1
                self.c.ingest.event("no_fly", [{"n": n}])
                self.c.ingest.event("policy", {"n": n})
                time.sleep(0.0005)
        t = threading.Thread(target=w)
        t.start()
        try:
            for _ in range(100):
                try:
                    _, S = self.c.ingest.snapshot(timeout_ms=50)
                except cl.CommitError:
                    continue
                a = S["no_fly"][0]["n"] if S["no_fly"] else 0
                b = S["policy"].get("n", 0)
                self.assertIn(a - b, (0, 1))
        finally:
            stop.set()
            t.join()

    def test_ingest_received_before_P_but_seq_pending(self):
        self.c.ingest._state["no_fly"]["ready"] = False   # 已宣告、值尚未寫完
        r = self.apply()
        self.assertEqual(r["action"], "BLOCK")
        self.assertEqual(r["code"], "INPUT_NOT_CURRENT")
        self.assertIsNone(self.c.word.current().route("home"))


class Linearization(Base):
    def test_ingest_between_final_compare_and_P(self):
        calls = []
        fired = []

        def inject():
            if not fired:
                fired.append(1)
                self.c.ingest.event("no_fly", [{"id": "Z9"}])
        self.hooks.actions["tx:before_cas"] = inject

        def recheck(S):
            calls.append(list(S["no_fly"]))
            return {"action": "BLOCK", "reasons": ["NFZ_CROSSING"]} if S["no_fly"] else ok(S)
        r = self.apply(recheck=recheck)
        self.assertIn("tx:cas_failed", self.hooks.trace)
        self.assertEqual(r["action"], "BLOCK")            # 新禁航區已納入重驗
        self.assertIsNone(self.c.word.current().route("home"))
        self.assertEqual(len(calls), 2)

    def test_commit_completes_under_continuous_telemetry(self):
        stop = threading.Event()

        def w():
            v = 90.0
            while not stop.is_set():
                v = 90.0 if v < 89.9 else 89.8          # 都在 ε 內
                self.c.ingest.sample("battery", v)
        t = threading.Thread(target=w)
        t.start()
        try:
            r = self.apply()
        finally:
            stop.set()
            t.join()
        self.assertEqual(r["action"], "WRITE")

    def test_post_P_response_has_needs_reverify(self):
        self.hooks.actions["tx:after_cas"] = lambda: self.c.ingest.event("no_fly", [{"id": "Z9"}])
        r = self.apply(recheck=lambda S: {"action": "BLOCK", "reasons": ["NFZ_CROSSING"]} if S["no_fly"] else ok(S))
        self.assertEqual(r["action"], "WRITE")
        self.assertTrue(r["needs_reverify"])
        self.assertIn("NFZ_CROSSING", r["reasons"])


class UndoAndUi(Base):
    def test_mixed_transaction_undo_lifo(self):
        self.apply("A")
        self.c.ui_apply("X", {"layout": 2})
        self.c.route_apply("B", "home", "r-B", PTS, "d1", 2, ok)
        self.assertEqual(self.c.undo("u1")["undid"], "B")
        self.assertEqual(self.c.word.current().route("home")["route_id"], "r-A")
        self.assertEqual(self.c.undo("u2")["undid"], "X")
        self.assertIsNone(self.c.word.current().ui_root)
        self.assertEqual(self.c.undo("u3")["undid"], "A")
        self.assertIsNone(self.c.word.current().route("home"))
        self.assertEqual(self.c.undo("u4")["code"], "UNDO_EMPTY")

    def test_undo_restores_with_needs_reverify(self):
        self.apply("A")
        self.c.route_apply("B", "home", "r-B", PTS, "d1", 2, ok)
        self.c.undo("u1")
        self.assertTrue(self.c.word.current().route("home")["needs_reverify"])

    def test_genui_active_durable_then_W_CAS_failure(self):
        self.hooks.actions["ui:active_durable"] = lambda: self.c.ingest.event("no_fly", [{"id": "Z"}])
        r = self.c.ui_apply("X", {"layout": 3})
        self.assertEqual(r["action"], "WRITE")
        self.assertEqual(self.c.word.current().ui_root, {"layout": 3})

    def test_route_publish_and_undo_head_atomic(self):
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                d = self.c.word.current()
                h = d.undo_head
                if h and h.entry["tx_kind"] == "route_apply" and d.route("home") != h.entry["after"]:
                    bad.append(d.root_gen)
        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(30):
                self.c.route_apply(f"t{i}", "home", f"r{i}", PTS, "d1", i, ok)
                self.c.ingest.event("policy", {"v": i})
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, [])
        for d in self.c.word.desc.values():                # reader_never_sees_mixed_descriptor
            h = d.undo_head
            if h and h.entry["tx_kind"] == "route_apply":
                self.assertEqual(d.route("home"), h.entry["after"])

    def test_rollback_does_not_expose_new_undo_head(self):
        self.apply("A")
        head_before = self.c.word.current().undo_head

        def fail():
            raise OSError("disk")
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = fail
        r = self.c.route_apply("B", "home", "r-B", PTS, "d1", 2, ok)
        self.assertEqual(r["code"], "ROLLED_BACK")
        d = self.c.word.current()
        self.assertIs(d.undo_head, head_before)
        self.assertEqual(d.route("home")["route_id"], "r-A")
        self.assertTrue(d.route("home")["needs_reverify"])


class Recovery(Base):
    def crash_at(self, point, tx="t1"):
        def boom():
            raise cl.SimulatedCrash(point)
        self.hooks.actions[point] = boom
        with self.assertRaises(cl.SimulatedCrash):
            self.apply(tx)
        del self.hooks.actions[point]
        if self.c.lease.locked():
            self.c.lease.release()

    def test_crash_after_prepared_uses_before(self):
        self.crash_at("tx:after_prepared")
        (c2, rep), _ = self.copy_and_boot()
        self.assertIsNone(c2.word.current().route("home"))
        self.assertTrue(any(x.get("action") == "use_before" for x in rep["recovery"]))

    def test_crash_after_committed_before_end_freezes(self):
        self.crash_at("tx:after_committed")
        (c2, rep), _ = self.copy_and_boot()
        self.assertEqual(c2.slot_state["home"]["state"], "FROZEN")

    def test_committed_root_survives_repeated_boots(self):
        self.apply()
        c, _ = cl.boot(self.root)
        c, _ = cl.boot(self.root)
        c, _ = cl.boot(self.root)
        r = c.word.current().route("home")
        self.assertEqual(r["route_id"], "r-t1")
        self.assertTrue(r["needs_reverify"])           # boot_restores_committed_root_across_generation

    def _make_frozen(self):
        def fail():
            raise OSError("disk")
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = fail
        self.hooks.actions["before_write:route.jsonl:ROLLED_BACK"] = fail
        r = self.apply("F")
        self.hooks.actions.clear()
        return r

    def test_frozen_terminal_survives_two_boots_and_checkpoint(self):
        r = self._make_frozen()
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        c, _ = cl.boot(self.root)
        self.assertEqual(c.slot_state["home"]["state"], "FROZEN")
        c, _ = cl.boot(self.root)
        self.assertEqual(c.slot_state["home"]["state"], "FROZEN")
        seed(c)
        self.assertEqual(c.route_apply("G", "home", "r-G", PTS, "d1", 3, ok)["code"], "COMMIT_FROZEN")

    def test_boot_aborted_restores_base(self):
        self.apply("t2", recheck=lambda S: {"action": "BLOCK", "reasons": ["X"]})
        (c2, _), _ = self.copy_and_boot()
        self.assertIsNone(c2.word.current().route("home"))
        self.assertNotIn("home", c2.slot_state)

    def test_boot_rolled_back_requires_rollback_evidence(self):
        self.apply("A")
        def fail():
            raise OSError("disk")
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = fail
        self.c.route_apply("B", "home", "r-B", PTS, "d1", 2, ok)
        self.hooks.actions.clear()
        (c2, _), _ = self.copy_and_boot("ok")
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-A")
        dst = os.path.join(self.tmp, "tampered")
        shutil.copytree(self.root, dst)
        seg = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        p = os.path.join(dst, "active", f"seg-{seg}", "route.jsonl")
        with open(p, encoding="utf-8") as f:
            lines = [l for l in f if '"ROLLED_BACK"' not in l]
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines)
        c3, _ = cl.boot(dst)
        self.assertEqual(c3.slot_state["home"]["state"], "FROZEN")

    def test_crash_during_checkpoint_creation_selects_last_valid_segment(self):
        self.apply()
        dst = os.path.join(self.tmp, "ck")
        shutil.copytree(self.root, dst)
        h = cl.Hooks()

        def boom():
            raise cl.SimulatedCrash("ptr")
        h.actions["ptr:before_replace"] = boom
        with self.assertRaises(cl.SimulatedCrash):
            cl.boot(dst, h)
        c2, rep = cl.boot(dst)                         # last_valid_segment_selected_after_crash
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-t1")
        segs = sorted(int(d[4:]) for d in os.listdir(os.path.join(dst, "active")) if d.startswith("seg-"))
        self.assertEqual(rep["segment"], segs[-1])      # 不完整分段保留，新分段用新編號

    def test_checkpoint_tail_hash_mismatch_freezes(self):
        self.apply()
        c2, rep = cl.boot(self.root)
        dst = os.path.join(self.tmp, "tail")
        shutil.copytree(self.root, dst)
        prev = cl.ActiveStore(dst).read_checkpoint(rep["segment"], cl.ActiveStore(dst).best_ptr()[1]["checkpoint_hash"])["prev_segment_id"]
        p = os.path.join(dst, "active", f"seg-{prev}", "coordinator.jsonl")
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write('{"tampered": true}\n')
        c3, rep3 = cl.boot(dst)
        self.assertIn("checkpoint_tail_hash_mismatch", rep3["frozen"])
        self.assertEqual(c3.slot_state["home"]["state"], "FROZEN")

    def test_partial_line_preserved_and_reported(self):
        self.apply()
        seg = cl.ActiveStore(self.root).best_ptr()[1]["segment_id"]
        p = os.path.join(self.root, "active", f"seg-{seg}", "route.jsonl")
        with open(p, "ab") as f:
            f.write(b'{"partial":')
        size = os.path.getsize(p)
        (c2, rep), dst = self.copy_and_boot()
        self.assertTrue(any("bad_lines" in x for x in rep["recovery"]))
        self.assertEqual(os.path.getsize(os.path.join(dst, "active", f"seg-{seg}", "route.jsonl")), size)

    def test_storage_budget_read_only(self):
        used = self.c.store.budget.used()
        self.c.store.budget.disk_budget = used + 1000
        self.c.store.budget.reserve = 500
        r = self.apply("big2")
        self.assertEqual(r["action"], "BLOCK")
        self.assertEqual(r["code"], "STORE_READ_ONLY")


class JointMargin(unittest.TestCase):
    """接 cg-v2：聯合安全餘裕與差異重顯（route_recheck）。"""

    def setUp(self):
        self.g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        self.rec = cv.preview_check(self.g, Vehicle(), Wind(), 90, 25, [])
        self.base = {"reserve_req_pct": 25, "max_alt_m": 120}

    def S(self, battery, wind=0.0):
        return {"battery": battery, "wind": {"speed_mps": wind, "from_deg": 0.0}, "no_fly": [],
                "limits": {"reserve_req_pct": 25, "max_alt_m": 120}, "position": (0, 0)}

    def test_combined_epsilon_margin(self):
        used = 90 - self.rec["est_end_pct"]
        rc = make_route_recheck(self.rec, Vehicle(), self.base)
        self.assertEqual(rc(self.S(25 + used + 0.5))["reasons"], ["JOINT_MARGIN_BATTERY"])
        self.assertNotEqual(rc(self.S(25 + used + 3))["action"], "BLOCK")

    def test_shown_version_small_change_writes(self):
        shown = cv.apply_check(self.rec, vehicle=Vehicle(), wind=Wind(), takeoff_pct=75, reserve_req_pct=25,
                               no_fly=[])
        rc = make_route_recheck(self.rec, Vehicle(), self.base, shown=shown)
        self.assertEqual(rc(self.S(74.8))["action"], "WRITE")
        self.assertEqual(rc(self.S(70))["action"], "REDISPLAY")

    def test_nfz_block_before_redisplay(self):
        z = [{"id": "Z9", **ll(50, 30), "radius_m": 5.0}]
        rc = make_route_recheck(self.rec, Vehicle(), self.base)
        S = self.S(89)
        S["no_fly"] = z
        v = rc(S)
        self.assertEqual(v["action"], "BLOCK")
        self.assertIn("NFZ_CROSSING", v["reasons"])
        self.assertEqual(v["hint"], "NEW_PREVIEW")

    def test_end_to_end_with_coordinator(self):
        tmp = tempfile.mkdtemp(prefix="cl_e2e_")
        try:
            root = os.path.join(tmp, "s")
            cl.init_store(root)
            c, _ = cl.boot(root)
            seed(c, battery=89.0)
            rc = make_route_recheck(self.rec, Vehicle(), self.base)

            def recheck(S):
                return rc(dict(S, limits=S["limits"]))
            r = c.route_apply("e1", "home", self.g["route_id"], self.rec["route"], "d1", 1, recheck)
            self.assertEqual(r["action"], "WRITE")
            self.assertEqual(c.word.current().route("home")["route_id"], self.g["route_id"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
