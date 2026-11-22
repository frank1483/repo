"""ADR-0002 G0 覆核修正（CODEX-APP-0437 的 6 點，`proposals/CODEX/adr0002_g0_mail_0502_cli/findings.md`）。
規則版，開發自檢，不是正式 G1。竄改與崩潰一律在副本上做。"""
import json
import os
import shutil
import threading
import unittest
from unittest import mock

from . import commit_layer as cl
from . import coverage as cv
from .energy import Vehicle, Wind
from .route_recheck import make_route_recheck
from .test_commit_layer import HOME, PTS, SQUARE, ok, seed
from .test_commit_layer import Base as CLBase
from . import test_g0 as G0
from .test_g0 import rewrite
from .test_g0b import listing
from .test_g0c import TV
from .test_preview_api import Base as PVBase


def ptr_path(root, ab):
    return os.path.join(root, "active", f"ptr-{ab}.json")


# ---------------- #1 指標退回 ----------------
class PointerFallback(CLBase):
    def _setup(self):
        self.apply()
        cl.boot(self.root)                                  # A、B 兩份指標都存在
        dst = os.path.join(self.tmp, "fb")
        shutil.copytree(self.root, dst)
        ptrs = sorted(cl.ActiveStore(dst).read_ptrs(), key=lambda x: -x[1]["seq"])
        newest, older = ptrs[0], ptrs[1]
        p = os.path.join(dst, "active", f"seg-{newest[1]['segment_id']}", "checkpoint.jsonl")
        rewrite(p, lambda r: dict(r, data={"tampered": 1}) if r.get("part") == "slot_state" else r)
        return dst, newest, older

    def test_fallback_keeps_the_verified_pointer(self):
        dst, newest, older = self._setup()
        with open(ptr_path(dst, older[0]), "rb") as f:
            kept = f.read()
        c, rep = cl.boot(dst)
        self.assertEqual(rep["pointer_used"]["pointer"], older[0])
        with open(ptr_path(dst, older[0]), "rb") as f:
            self.assertEqual(f.read(), kept)                # 唯一可核證的那份沒被覆蓋
        self.assertEqual(c.word.current().route("home")["route_id"], "r-t1")

    def test_reboot_after_fallback_and_new_checkpoint_fails_again(self):
        dst, newest, older = self._setup()
        c, rep = cl.boot(dst)                               # 第一次退回，新指標寫進原本壞的那一份
        c2, rep2 = cl.boot(dst)                             # 再開機：用新的那份
        self.assertEqual(rep2["pointer_used"]["segment_id"], rep["segment"])
        # 新檢查點再失效 → 仍能退回到仍保留的那一份
        p = os.path.join(dst, "active", f"seg-{rep2['segment']}", "checkpoint.jsonl")
        rewrite(p, lambda r: dict(r, data={"tampered": 2}) if r.get("part") == "slot_state" else r)
        c3, rep3 = cl.boot(dst)
        self.assertNotEqual(rep3.get("mode"), "RESTRICTED_READ_ONLY")
        self.assertEqual(rep3["pointer_used"]["segment_id"], rep["segment"])

    def test_rejected_pointer_reported_and_preserved(self):
        self.apply()
        cl.boot(self.root)
        dst = os.path.join(self.tmp, "rj")
        shutil.copytree(self.root, dst)
        ptrs = sorted(cl.ActiveStore(dst).read_ptrs(), key=lambda x: -x[1]["seq"])
        bad = ptrs[0][0]
        with open(ptr_path(dst, bad), "wb") as f:
            f.write(b"[1, 2, 3]")                           # 非物件 JSON
        c, rep = cl.boot(dst)
        self.assertIn({"pointer": bad, "segment_id": None, "reason": "bad_shape"}, rep["pointer_rejected"])
        saved = [n for n in os.listdir(os.path.join(dst, "active")) if n.startswith(f"ptr-{bad}.rejected-")]
        self.assertEqual(len(saved), 1)                     # 被覆蓋前另存，不刪除
        with open(os.path.join(dst, "active", saved[0]), "rb") as f:
            self.assertEqual(f.read(), b"[1, 2, 3]")

    def test_non_object_json_line_is_bad_line_not_crash(self):
        self.apply()
        seg = cl.ActiveStore(self.root).best_ptr()[1]["segment_id"]
        with open(os.path.join(self.root, "active", f"seg-{seg}", "route.jsonl"), "ab") as f:
            f.write(b"[1, 2]\n")
        good, bad = cl.Journal.read(os.path.join(self.root, "active", f"seg-{seg}", "route.jsonl"))
        self.assertTrue(any(b["reason"] == "sha_or_json" for b in bad))


# ---------------- #2 掃描與寫入 ----------------
class ScanAndWrite(CLBase):
    def test_pointer_reads_counted_in_scan(self):
        self.apply()
        sc = cl.ScanBudget()
        cl.ActiveStore(self.root).read_ptr_status(sc)
        self.assertGreaterEqual(sc.lines, 1)
        self.assertGreater(sc.bytes, 0)

    def test_oversized_pointer_file_bounded(self):
        self.apply()
        dst = os.path.join(self.tmp, "big")
        shutil.copytree(self.root, dst)
        ab = cl.ActiveStore(dst).best_ptr()[0]
        with open(ptr_path(dst, ab), "wb") as f:
            f.write(b" " * (cl.TEST_VALUES["pointer_read_cap_bytes"] + 10))
        st = {a: s for a, s, _ in cl.ActiveStore(dst).read_ptr_status()}
        self.assertEqual(st[ab], "too_large")

    def test_tail_read_counts_lines(self):
        self.apply()
        c, rep = cl.boot(self.root)
        sc = cl.ScanBudget()
        cl.ActiveStore(self.root).tail_hash(rep["segment"] - 1, sc)
        self.assertGreater(sc.lines, 0)

    def test_write_phase_failure_reported_separately(self):
        self.apply()
        dst = os.path.join(self.tmp, "wf")
        shutil.copytree(self.root, dst)
        h = cl.Hooks()

        def boom():
            raise OSError("disk")
        h.actions["fsync:checkpoint.jsonl:CHECKPOINT_MANIFEST"] = boom
        c, rep = cl.boot(dst, h)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual(rep["write_failure"]["stage"], "checkpoint")
        self.assertNotIn("scan_limit", rep)

    def test_free_space_query_failure_is_closed(self):
        with mock.patch.object(cl.shutil, "disk_usage", side_effect=OSError("no")):
            r = self.apply("t-q")
        self.assertEqual(r["code"], "STORE_READ_ONLY")


# ---------------- #3 准入在租約內、ID、封套、BEFORE 無 PREPARED ----------------
class AdmissionInLease(CLBase):
    def test_concurrent_new_slots_cannot_exceed_limit(self):
        with TV(max_route_slots=2):
            self.c.route_apply("t-a", "a", "r-a", PTS, "d1", 1, ok)
            gate, started = threading.Event(), threading.Event()

            def slow(S):
                started.set()
                gate.wait(5)
                return ok(S)
            out = {}
            t1 = threading.Thread(target=lambda: out.setdefault("b", self.c.route_apply("t-b", "b", "r-b", PTS, "d1", 1, slow)))
            t1.start()
            started.wait(5)
            t2 = threading.Thread(target=lambda: out.setdefault("c", self.c.route_apply("t-c", "c", "r-c", PTS, "d1", 1, ok)))
            t2.start()
            gate.set()
            t1.join(10)
            t2.join(10)
        self.assertEqual(out["b"]["action"], "WRITE")
        self.assertEqual((out["c"]["code"], out["c"]["reasons"]), ("LIMIT_EXCEEDED", ["route_slots"]))
        self.assertEqual(len(self.c.word.current().route_roots), 2)

    def test_id_charset_ascii_only(self):
        r = self.c.route_apply("交易" * 10, "home", "r", PTS, "d1", 1, ok)
        self.assertEqual(r["code"], "LIMIT_EXCEEDED")
        r = self.c.route_apply("t-ok", "home", "r", PTS, "d1", -1, ok)
        self.assertEqual(r["reasons"], ["draft_rev_range"])

    def test_full_encoded_line_checked_before_write(self):
        before = listing(self.root)
        pts = [{"id": str(i), "lat": 24.0, "lon": 121.0, "pad": "x" * 520} for i in range(480)]
        with TV(point_cap_bytes=600):                       # 預設值下 480×512 B 放得下（餘 14,400 B）；放寬單點才會整行超限
            r = self.apply("t-line", points=pts)
        self.assertEqual(r["reasons"], ["encoded_line"])
        self.assertEqual(listing(self.root), before)

    def test_abort_terminal_uses_reserve(self):
        def squeeze():                                      # 進入提交層之後，一般額度才用完
            self.c.store.budget.disk_budget = self.c.store.budget.used() + 1024 * 1024
        self.hooks.actions["tx:after_prepared"] = squeeze
        r = self.apply("t-ab", recheck=lambda S: {"action": "BLOCK", "reasons": ["X"]})
        self.hooks.actions.clear()
        self.assertEqual(r["action"], "BLOCK")
        seg = cl.ActiveStore(self.root).best_ptr()[1]["segment_id"]
        recs, _ = cl.Journal.read(os.path.join(self.root, "active", f"seg-{seg}", "coordinator.jsonl"))
        self.assertTrue(any(x["kind"] == "END" and x["tx_id"] == "t-ab" and x["outcome"] == "ABORTED" for x in recs))

    def test_before_without_prepared_freezes(self):
        self.apply("A")
        self.apply("B", recheck=lambda S: {"action": "BLOCK", "reasons": ["X"]})
        dst = os.path.join(self.tmp, "np")
        shutil.copytree(self.root, dst)
        seg = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        rewrite(os.path.join(dst, "active", f"seg-{seg}", "route.jsonl"),
                lambda r: None if r["tx_id"] == "B" and r["kind"] in ("ABORTED", "PREPARED") else r)
        rewrite(os.path.join(dst, "active", f"seg-{seg}", "coordinator.jsonl"),
                lambda r: dict(r, kind_terminal_sha=None) if r["kind"] == "END" and r["tx_id"] == "B" else r)
        c, _ = cl.boot(dst)
        self.assertEqual(c.slot_state["home"]["reason"], "before_snapshot_unverifiable")


# ---------------- #4 W 與入站 ----------------
class WordAndIngest(CLBase):
    def test_last_usable_generation_reserves_rollback(self):
        g = self.c.word.root_gen
        with TV(root_gen_bits=1):                           # 2^1＝2：g＝0 時 0＋2 ≥ 2 → 預留不足
            r = self.apply("t-last")
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(self.c.word.root_gen, g)

    def test_cas_rejects_width_overflow(self):
        d = self.c.word.current()
        with TV(root_gen_bits=0):
            nd = cl.Descriptor(d.root_gen + 1, d.global_seq, d.ui_root, d.route_roots, d.undo_head)
            self.assertFalse(self.c.word.cas_gen(d.root_gen, nd))

    def test_seq_exhausted_after_snapshot_blocks_publish(self):
        def exhaust():
            self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
            try:
                self.c.ingest.event("policy", {"v": 99})
            except cl.CommitError:
                pass
        self.hooks.actions["tx:after_recheck"] = exhaust
        r = self.apply("t-ex")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        self.assertIsNone(self.c.word.current().route("home"))
        st = self.c.ingest._state["policy"]
        self.assertEqual(st["pending"], 0)                   # pending 不殘留
        self.assertFalse(st["ready"])

    def test_classify_and_seq_are_atomic(self):
        """判帶與取序號在同一個臨界區：以 _beyond_eps 期間插入事件模擬，插入的事件必須等到判帶結束。"""
        ing = self.c.ingest
        real = ing._beyond_eps
        order = []

        def slow_beyond(src, new, ref):
            order.append(("classify", ref))
            t = threading.Thread(target=lambda: (ing.event("battery", 70.0), order.append(("event", None))))
            t.start()
            t.join(0.2)                                    # 事件拿不到鎖 → 不會在判帶中途改 ref
            order.append(("event_done_during_classify", not t.is_alive()))
            self._t = t
            return real(src, new, ref)
        with mock.patch.object(ing, "_beyond_eps", side_effect=slow_beyond):
            ing.sample("battery", 89.8)
        self._t.join(5)
        self.assertEqual(order[-2], ("event_done_during_classify", False))
        _, S = ing.snapshot(timeout_ms=200)
        self.assertEqual(S["battery"], 70.0)                 # 事件序號較新


# ---------------- #5 權杖綁定目前版本 ----------------
class TokenBinding(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def test_old_screen_cannot_reissue_after_new_draft_rev(self):
        p = self.preview()
        ch1, tok1 = self._confirm(p, rev=1)
        self._confirm(p, rev=2)                              # 同一預覽、新草稿版本
        js = self.call("/api/preview/presented", {"shown_hash": ch1["shown_hash"], "apply_intent_id": ch1["apply_intent_id"],
                                                  "target_slot_id": "home", "window_id": "w1", "frame_id": "f9"}, expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")
        js = self.call("/api/preview/commit", self.body(ch1, tok1), expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")

    def test_older_draft_rev_rejected(self):
        p = self.preview()
        self._confirm(p, rev=3)
        js = self.call("/api/preview/apply_check", {"preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": 2,
                                                    "target_slot_id": "home",
                                                    "target_generation": self.coord.word.current().root_gen}, expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")

    def test_supersede_racing_issuance_never_yields_live_token(self):
        p = self.preview()
        ch = self.call("/api/preview/apply_check", {"preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": 1,
                                                    "target_slot_id": "home",
                                                    "target_generation": self.coord.word.current().root_gen})["data"]["check"]
        real = self.svc._binding_current

        def racing(sh, principal):                           # 在鎖內核對前，另一個生產端搶先撤銷
            threading.Thread(target=lambda: self.svc.supersede_preview(p["preview_ref"], "race")).start()
            return real(sh, principal)
        with mock.patch.object(self.svc, "_binding_current", side_effect=racing):
            st, js, _ = self.raw("POST", "/api/preview/presented",
                                 {"boot_epoch": 7, "request_epoch": 999, "session_id": self.sid,
                                  "shown_hash": ch["shown_hash"], "apply_intent_id": ch["apply_intent_id"],
                                  "target_slot_id": "home", "window_id": "w", "frame_id": "f"})
        import time
        time.sleep(0.2)
        live = [t for t in self.svc.tokens.values() if t["preview"] == p["preview_ref"] and t["state"] == "ISSUED"]
        self.assertEqual(live, [])                            # 撤銷不論先後，結束時沒有可用權杖

    def test_deadline_equal_is_expired(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        t = self.svc.tokens[tok]
        self.svc.now = lambda: t["expires"]
        js = self.call("/api/preview/commit", self.body(ch, tok), expect=400)
        self.assertEqual(js["error"]["code"], "CONFIRM_TOKEN_STALE")


# ---------------- #6 適用域接到入口 ----------------
class DomainAtEntry(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def test_profile_vehicle_blocked_through_service(self):
        p = self.preview()
        ch, tok = self._confirm(p)
        real = self.sess.vehicle
        self.sess.vehicle = lambda: Vehicle(airframe_profile={"type": "multirotor", "power": {}})
        try:
            r = self.call("/api/preview/commit", self.body(ch, tok))["data"]
        finally:
            self.sess.vehicle = real
        self.assertEqual(r["transaction"]["action"], "BLOCK")
        self.assertIn("JOINT_MARGIN_UNVERIFIED", r["transaction"]["reasons"])
        self.assertIsNone(self.coord.word.current().route("home"))

    def test_nonfinite_snapshot_blocked(self):
        g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        rec = cv.preview_check(g, Vehicle(), Wind(), 90, 25, [])
        rc = make_route_recheck(rec, Vehicle(), {"reserve_req_pct": 25, "max_alt_m": 120})
        S = {"battery": float("nan"), "wind": {"speed_mps": 0.0, "from_deg": 0.0}, "no_fly": [],
             "limits": {"reserve_req_pct": 25, "max_alt_m": 120}, "position": (0, 0)}
        self.assertEqual(rc(S)["domain"], "snapshot_nonfinite")
        S["battery"], S["wind"]["speed_mps"] = 90.0, 99.0
        self.assertEqual(rc(S)["domain"], "snapshot_out_of_range")


if __name__ == "__main__":
    unittest.main()
