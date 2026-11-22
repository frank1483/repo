"""ADR-0002 G0 第三輪覆核修正（CODEX-APP-0439，`proposals/CODEX/adr0002_g0_mail_0504_cli/findings.md`）。
規則版，開發自檢，不是正式 G1。"""
import os
import shutil
import threading
import time
import unittest
from unittest import mock

from . import commit_layer as cl
from . import test_g0 as G0
from .test_commit_layer import PTS, ok
from .test_commit_layer import Base as CLBase
from .test_g0c import TV
from .test_preview_api import Base as PVBase


class CountReads:
    """計算指標檔被開啟讀取的次數。"""

    def __init__(self):
        self.n = 0
        self.real = open

    def __call__(self, path, mode="r", *a, **kw):
        if "ptr-" in str(path) and "rb" in mode and not str(path).endswith(".tmp"):
            self.n += 1
        return self.real(path, mode, *a, **kw)


# ---------------- #2 超限後不重讀指標 ----------------
class ScanLimitNoReread(CLBase):
    def _boot_with_cap(self, **tv):
        self.apply()
        dst = os.path.join(self.tmp, "s" + str(len(tv)))
        shutil.copytree(self.root, dst)
        cr = CountReads()
        with TV(**tv), mock.patch("builtins.open", cr):
            c, rep = cl.boot(dst)
        return rep, cr.n

    def test_limit_while_reading_pointers(self):
        rep, n = self._boot_with_cap(boot_scan_lines=0)      # 讀第一份指標就超限
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual(n, 1)                               # 只讀過那一份，診斷不再重讀
        res = {d["pointer"]: d["result"] for d in rep["diagnostics"]["pointers"]}
        self.assertEqual(set(res.values()), {"unchecked_scan_limit"})

    def test_limit_while_reading_checkpoint(self):
        rep, n = self._boot_with_cap(boot_scan_lines=3)      # 兩份指標讀完，讀檢查點才超限
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual(n, 2)                               # 指標各讀一次
        self.assertEqual({d["result"] for d in rep["diagnostics"]["pointers"]}, {"scan_limit"})

    def test_sentinel_after_reserve_check(self):
        self.apply()
        dst = os.path.join(self.tmp, "sent")
        shutil.copytree(self.root, dst)
        real = shutil.disk_usage

        def slow(p):                                         # 預檢本身拖過期限 → 最後一道哨點擋下、不寫檔
            time.sleep(0.05)
            return real(p)
        before = sorted(os.listdir(os.path.join(dst, "active")))
        with TV(boot_scan_seconds=0.04), mock.patch.object(cl.shutil, "disk_usage", side_effect=slow):
            c, rep = cl.boot(dst)
        self.assertEqual(rep["scan_limit"]["code"], "BOOT_SCAN_LIMIT")
        self.assertEqual(sorted(os.listdir(os.path.join(dst, "active"))), before)


# ---------------- #3 BOOT 實體空間預檢、undo 收尾失敗 ----------------
class BootFreeSpaceAndUndo(CLBase):
    def test_boot_physical_free_space_precheck(self):
        self.apply()
        dst = os.path.join(self.tmp, "fs")
        shutil.copytree(self.root, dst)
        before = sorted(os.listdir(os.path.join(dst, "active")))
        fake = type("U", (), {"free": 1024 * 1024})()       # 實體只剩 1 MiB ＜ 11 MiB
        with mock.patch.object(cl.shutil, "disk_usage", return_value=fake):
            c, rep = cl.boot(dst)
        self.assertEqual(rep["write_failure"]["stage"], "reserve_check")
        self.assertEqual(sorted(os.listdir(os.path.join(dst, "active"))), before)   # 第一筆寫入前就停

    def _undo_fail_at(self, point):
        self.apply("A")
        self.apply("B")

        def boom():
            raise OSError("disk")
        self.hooks.actions[point] = boom
        r = self.c.undo("u1")
        self.hooks.actions.clear()
        return r

    def test_undo_committed_unwritable_compensates(self):
        r = self._undo_fail_at("fsync:route.jsonl:COMMITTED")
        self.assertEqual(r["code"], "ROLLED_BACK")
        self.assertEqual(self.c.word.current().route("home")["route_id"], "r-B")   # 補償回 undo 前
        c2, _ = cl.boot(self.root)
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-B")     # 重啟後一致

    def test_undo_end_unwritable_compensates(self):
        r = self._undo_fail_at("fsync:coordinator.jsonl:END")
        self.assertIn(r["code"], ("ROLLED_BACK", "COMMIT_FROZEN"))
        cur = self.c.word.current().route("home")
        c2, _ = cl.boot(self.root)
        if r["code"] == "ROLLED_BACK":
            self.assertEqual(cur["route_id"], "r-B")
            self.assertEqual(c2.word.current().route("home")["route_id"], "r-B")
        else:
            self.assertEqual(c2.slot_state["home"]["state"], "FROZEN")

    def test_undo_compensation_failure_freezes(self):
        def boom():
            raise OSError("disk")
        self.apply("A")
        self.apply("B")
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = boom
        self.hooks.actions["before_write:route.jsonl:ROLLED_BACK"] = boom
        r = self.c.undo("u1")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.slot_state["home"]["state"], "FROZEN")


# ---------------- #4 准入後、生效前耗盡 ----------------
class ExhaustBeforePublish(CLBase):
    def _exhaust(self):
        self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
        try:
            self.c.ingest.event("policy", {"v": "z"})
        except cl.CommitError:
            pass

    def test_ui_exhausted_between_admission_and_publish(self):
        g = self.c.word.root_gen
        self.hooks.actions["ui:after_begin"] = self._exhaust
        r = self.c.ui_apply("x", {"l": 1})
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(self.c.word.root_gen, g)
        self.assertIsNone(self.c.word.current().ui_root)

    def test_undo_exhausted_before_publish(self):
        self.apply("A")
        g = self.c.word.root_gen
        self.hooks.actions["undo:before_publish"] = self._exhaust
        r = self.c.undo("u")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(self.c.word.root_gen, g)
        self.assertEqual(self.c.word.current().route("home")["route_id"], "r-A")

    def test_compensation_still_allowed_after_exhaustion(self):
        self.apply("A")

        def fail():
            raise OSError("disk")
        self.hooks.actions["tx:after_cas"] = self._exhaust
        self.hooks.actions["fsync:route.jsonl:COMMITTED"] = fail
        r = self.apply("B")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "ROLLED_BACK")                       # 補償發布仍完成
        self.assertEqual(self.c.word.current().route("home")["route_id"], "r-A")


# ---------------- #5 等鎖期間世代改變 ----------------
class GenerationWhileWaiting(PVBase):
    _confirm = G0.TokenRevocation._confirm
    body = G0.TokenRevocation.body

    def test_generation_changes_while_apply_check_waits(self):
        p = self.preview()
        ch1, tok1 = self._confirm(p, rev=1)
        g = self.coord.word.current().root_gen
        before = dict(self.svc.current_preview)
        self.assertTrue(self.coord.lease.acquire(timeout=1))   # 模擬另一筆結構提交持有租約
        out = {}

        def ac():
            out["r"] = self.raw("POST", "/api/preview/apply_check",
                                {"boot_epoch": 7, "request_epoch": 10 ** 6, "session_id": self.sid,
                                 "preview_ref": p["preview_ref"], "draft_id": "d1", "draft_rev": 2,
                                 "target_slot_id": "home", "target_generation": g})
        t = threading.Thread(target=ac)
        t.start()
        time.sleep(0.2)
        d = self.coord.word.current()                          # 持租約期間發布新世代
        nd = cl.Descriptor(d.root_gen + 1, d.global_seq, {"x": 1}, d.route_roots, d.undo_head)
        self.assertTrue(self.coord.word.cas_gen(d.root_gen, nd))
        self.coord.lease.release()
        t.join(10)
        st, js, _ = out["r"]
        self.assertEqual(js["error"]["code"], "TARGET_STALE")
        self.assertEqual(self.svc.current_preview, before)     # 零副作用
        self.assertEqual(self.svc.tokens[tok1]["state"], "ISSUED")


if __name__ == "__main__":
    unittest.main()
