"""ADR-0002 G0 第 5 節上限的程式執行（Codex `G0_第5節上限計算_v1.md`；使用者 2026-11-23 02:49「凍結前讓程式真正執行這些上限」）。
規則版，開發自檢，不是正式 G1。數值都是測試用值。"""
import os
import shutil
import unittest
from unittest import mock

from . import commit_layer as cl
from .test_commit_layer import PTS, ok
from .test_commit_layer import Base as CLBase
from .test_g0b import listing


class TV:
    """暫時改 TEST_VALUES，離開時還原。"""

    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = cl.TEST_VALUES[k]
            cl.TEST_VALUES[k] = v

    def __exit__(self, *a):
        cl.TEST_VALUES.update(self.old)


def max_point(i):
    """單點 canonical 編碼剛好不超過 512 B 的合規點（128 字元 ID）。"""
    base = {"id": (str(i) + "x" * 128)[:128], "lat": 24.000000000001, "lon": 121.000000000001, "alt": 120.0,
            "kind": "target", "pad": ""}
    n = len(cl._jsonb(base))
    base["pad"] = "p" * (512 - n)
    assert len(cl._jsonb(base)) == 512
    return base


class ReservePlan(unittest.TestCase):
    def test_plan_is_15_of_16_mib(self):
        p = cl.reserve_plan()
        M = 1024 * 1024
        self.assertEqual(p["parts"]["checkpoint"], 35 * 256 * 1024)          # (32＋3) × 256 KiB＝8.75 MiB
        self.assertEqual(p["parts"]["recovery"], 2 * M)
        self.assertEqual(p["parts"]["terminals"], 4 * M)
        self.assertEqual(p["parts"]["pointers"], M // 4)
        self.assertEqual(p["total"], 15 * M)
        self.assertLessEqual(p["total"], p["reserve"])

    def test_boot_refuses_when_reserve_smaller_than_plan(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="g0c_")
        try:
            root = os.path.join(tmp, "s")
            cl.init_store(root)
            with TV(max_route_slots=40):                                       # (40＋3)×256 KiB＋6.25 MiB＞16 MiB
                with self.assertRaises(cl.CommitError) as e:
                    cl.boot(root)
            self.assertEqual(e.exception.code, "RESERVE_TOO_SMALL")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Admission(CLBase):
    def test_slot_limit(self):
        with TV(max_route_slots=3):
            for s in ("home", "s2", "s3"):
                self.assertEqual(self.c.route_apply("t-" + s, s, "r-" + s, PTS, "d1", 1, ok)["action"], "WRITE")
            before = listing(self.root)
            r = self.c.route_apply("t-s4", "s4", "r-s4", PTS, "d1", 1, ok)
            self.assertEqual((r["code"], r["reasons"]), ("LIMIT_EXCEEDED", ["route_slots"]))
            self.assertEqual(listing(self.root), before)                     # 受理時拒絕：不寫檔
            self.assertEqual(self.c.route_apply("t-h2", "home", "r-h2", PTS, "d1", 2, ok)["action"], "WRITE")

    def test_points_and_point_size(self):
        before = listing(self.root)
        pts = [{"id": str(i), "lat": 24.0, "lon": 121.0} for i in range(481)]
        self.assertEqual(self.apply("p1", points=pts)["reasons"], ["route_points"])
        big = [dict(max_point(0), pad=max_point(0)["pad"] + "y")]
        self.assertEqual(self.apply("p2", points=big)["reasons"], ["point_size"])
        self.assertEqual(listing(self.root), before)

    def test_max_compliant_route_fits_line_cap(self):
        """最大合規 fixture：480 點、每點剛好 512 B、128 字元 ID → SNAPSHOT 與檢查點塊都在 256 KiB 內，可恢復。"""
        pts = [max_point(i) for i in range(480)]
        tid = "T" * 128
        r = self.c.route_apply(tid, "home", "R" * 128, pts, "D" * 128, 2 ** 53 - 1, ok)
        self.assertEqual(r["action"], "WRITE")
        c2, _ = cl.boot(self.root)
        self.assertEqual(len(c2.word.current().route("home")["points"]), 480)

    def test_id_length(self):
        r = self.c.route_apply("t" * 129, "home", "r", PTS, "d1", 1, ok)
        self.assertEqual(r["reasons"], ["tx_id_length"])

    def test_recovery_line_within_512(self):
        rec = {"kind": "RECOVERY", "tx_id": "T" * 128, "action": "use_before", "why": "aborted_without_kind_terminal",
               "from_segment": 2 ** 64 - 1}
        j = cl.Journal(os.path.join(self.tmp, "r.jsonl"))
        body = j.append(rec, max_bytes=cl.TEST_VALUES["recovery_line_cap_bytes"])
        self.assertTrue(body["sha256"])
        with self.assertRaises(cl.CommitError):
            j.append(dict(rec, why="w" * 300), max_bytes=cl.TEST_VALUES["recovery_line_cap_bytes"])


class BootScanBudget(CLBase):
    def _copy(self, name):
        self.apply()
        dst = os.path.join(self.tmp, name)
        shutil.copytree(self.root, dst)
        return dst

    def test_cumulative_bytes_over_limit_restricted(self):
        dst = self._copy("sb")
        seg = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        sizes = sum(os.path.getsize(os.path.join(dst, "active", f"seg-{seg}", f))
                    for f in os.listdir(os.path.join(dst, "active", f"seg-{seg}")))
        biggest = max(os.path.getsize(os.path.join(dst, "active", f"seg-{seg}", f))
                      for f in os.listdir(os.path.join(dst, "active", f"seg-{seg}")))
        before = listing(dst)
        with TV(boot_scan_bytes=(biggest + sizes) // 2):                     # 每個檔都在上限內，累計才超過
            self.assertGreater(sizes, (biggest + sizes) // 2)
            c, rep = cl.boot(dst)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")
        self.assertEqual(rep["scan_limit"]["code"], "BOOT_SCAN_LIMIT")
        self.assertEqual(listing(dst), before)
        self.assertEqual(c.route_apply("x", "home", "r", PTS, "d1", 1, ok)["code"], "STORE_READ_ONLY")

    def test_cumulative_lines_over_limit_restricted(self):
        dst = self._copy("sl")
        with TV(boot_scan_lines=3):
            c, rep = cl.boot(dst)
        self.assertEqual(rep["mode"], "RESTRICTED_READ_ONLY")

    def test_time_over_limit_restricted(self):
        dst = self._copy("st")
        with TV(boot_scan_seconds=-1.0):
            c, rep = cl.boot(dst)
        self.assertEqual(rep["scan_limit"]["code"], "BOOT_SCAN_LIMIT")

    def test_normal_boot_reports_scan_usage(self):
        dst = self._copy("ok")
        c, rep = cl.boot(dst)
        self.assertGreater(rep["scan"]["bytes"], 0)
        self.assertLessEqual(rep["scan"]["bytes"], cl.TEST_VALUES["boot_scan_bytes"])


class ReserveUse(CLBase):
    def test_boot_uses_reserve_when_normal_admission_full(self):
        used = self.c.store.budget.used()
        with TV(disk_budget_bytes=used + 1024 * 1024, terminal_reserve_bytes=16 * 1024 ** 2):
            # 一般寫入額度已經是負的（used＋1 MiB − 16 MiB），只有預留模式可以寫
            self.c.store.budget.disk_budget = used + 1024 * 1024
            r = self.apply("t-full")
            self.assertEqual(r["code"], "STORE_READ_ONLY")
            c2, rep = cl.boot(self.root)                                    # BOOT 動用預留寫檢查點與指標
            self.assertNotEqual(rep.get("mode"), "RESTRICTED_READ_ONLY")
            self.assertEqual(c2.route_apply("t2", "home", "r2", PTS, "d1", 1, ok)["code"], "STORE_READ_ONLY")

    def test_filesystem_free_space_checked(self):
        fake = shutil._ntuple_diskusage(10 ** 12, 10 ** 12 - 1024, 1024) if hasattr(shutil, "_ntuple_diskusage") \
            else type("U", (), {"free": 1024})()
        with mock.patch.object(cl.shutil, "disk_usage", return_value=fake):
            r = self.apply("t-free")
        self.assertEqual(r["code"], "STORE_READ_ONLY")
        self.assertIsNone(self.c.word.current().route("home"))


class WordWidth(CLBase):
    def test_safety_seq_exhausted_marks_source_not_ready(self):
        self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
        with self.assertRaises(cl.CommitError) as e:
            self.c.ingest.event("policy", {"v": 2})
        self.assertEqual(e.exception.code, "W_EPOCH_EXHAUSTED")

    def test_root_gen_exhausted_blocks_before_write(self):
        before = listing(self.root)
        with TV(root_gen_bits=0):                                            # 0＋1 ≥ 2^0 → 再發布就會溢位
            r = self.apply("t-w")
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        self.assertEqual(listing(self.root), before)


if __name__ == "__main__":
    unittest.main()
