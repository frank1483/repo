"""ADR-0002 G0 第四輪（CODEX-APP-0440）與使用者裁決 E-1 A、E-2（2026-11-23 10:13）。規則版，開發自檢，不是正式 G1。"""
import os
import shutil
import unittest

from . import commit_layer as cl
from .test_commit_layer import Base as CLBase


def boom():
    raise OSError("disk")


class UndoUnpersisted(CLBase):
    def _undo_with(self, points):
        self.apply("A")
        self.apply("B")
        for p in points:
            self.hooks.actions[p] = boom
        r = self.c.undo("u1")
        self.hooks.actions.clear()
        return r

    def _boot_copy(self, name):
        dst = os.path.join(self.tmp, name)
        shutil.copytree(self.root, dst)
        return cl.boot(dst)

    def test_nothing_persisted_stays_frozen_after_restart(self):
        """E-1 A：COMMITTED、ROLLED_BACK、END 都在寫入前失敗 → 當下凍結，重啟後也凍結。"""
        r = self._undo_with(["before_write:route.jsonl:COMMITTED", "before_write:route.jsonl:ROLLED_BACK",
                             "before_write:coordinator.jsonl:END"])
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.slot_state["home"]["state"], "FROZEN")
        seg = cl.ActiveStore(self.root).best_ptr()[1]["segment_id"]
        recs, _ = cl.Journal.read(os.path.join(self.root, "active", f"seg-{seg}", "route.jsonl"))
        self.assertFalse([x for x in recs if x["tx_id"] == "u1" and x["kind"] in ("COMMITTED", "ROLLED_BACK")])
        (c2, rep), = [self._boot_copy("n")]
        self.assertEqual(c2.slot_state["home"]["state"], "FROZEN")
        self.assertEqual(c2.slot_state["home"]["reason"], "undo_without_terminal")

    def test_committed_persisted_without_end_frozen_after_restart(self):
        """部分持久化：COMMITTED 已寫入、END 與補償都失敗 → 重啟後凍結（committed_without_end）。"""
        r = self._undo_with(["before_write:coordinator.jsonl:END", "before_write:route.jsonl:ROLLED_BACK"])
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        c2, _ = self._boot_copy("p")
        self.assertEqual(c2.slot_state["home"]["reason"], "committed_without_end")


class UiStubFreeze(CLBase):
    def test_frozen_ui_blocks_ui_apply_and_ui_undo(self):
        self.assertEqual(self.c.ui_apply("x1", {"l": 1})["action"], "WRITE")
        self.c._freeze("ui", "test")
        self.assertEqual(self.c.ui_apply("x2", {"l": 2})["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.undo("u-ui")["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.word.current().ui_root, {"l": 1})


class ExhaustEndReserve(CLBase):
    def test_ui_exhausted_with_normal_budget_full_still_returns_code(self):
        def squeeze_and_exhaust():
            self.c.store.budget.disk_budget = self.c.store.budget.used() + 1024 * 1024   # 一般額度用完
            self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
            try:
                self.c.ingest.event("policy", {"v": "q"})
            except cl.CommitError:
                pass
        self.hooks.actions["ui:after_begin"] = squeeze_and_exhaust
        r = self.c.ui_apply("x", {"l": 1})
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "W_EPOCH_EXHAUSTED")
        seg = cl.ActiveStore(self.root).best_ptr()[1]["segment_id"]
        recs, _ = cl.Journal.read(os.path.join(self.root, "active", f"seg-{seg}", "coordinator.jsonl"))
        self.assertTrue(any(x["kind"] == "END" and x["tx_id"] == "x" and x["outcome"] == "ABORTED" for x in recs))


if __name__ == "__main__":
    unittest.main()
