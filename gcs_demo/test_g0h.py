"""ADR-0002 G0 送簽前覆核（CODEX-APP-0441）的兩個阻斷項。規則版，開發自檢，不是正式 G1。"""
import os
import shutil
import threading
import time
import unittest

from . import commit_layer as cl
from .test_commit_layer import Base as CLBase


def boom():
    raise OSError("disk")


class UiFreezeInLease(CLBase):
    def test_ui_frozen_while_waiting_lease(self):
        self.assertEqual(self.c.ui_apply("x1", {"l": 1})["action"], "WRITE")
        self.assertTrue(self.c.lease.acquire(timeout=1))
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", self.c.ui_apply("x2", {"l": 2})))
        t.start()
        time.sleep(0.1)
        self.c._freeze("ui", "frozen_while_waiting")          # 持租約者在租約內凍結 ui
        self.c.lease.release()
        t.join(10)
        self.assertEqual(out["r"]["code"], "COMMIT_FROZEN")
        self.assertEqual(self.c.word.current().ui_root, {"l": 1})

    def test_ui_undo_frozen_and_begin_unwritable(self):
        self.assertEqual(self.c.ui_apply("x1", {"l": 1})["action"], "WRITE")
        self.c._freeze("ui", "test")
        head = self.c.word.current().undo_head
        self.c.store.budget.disk_budget = self.c.store.budget.used() + 1024        # 一般額度用完：BEGIN 寫不進
        r = self.c.undo("u-ui")
        self.assertEqual(r["code"], "COMMIT_FROZEN")                               # 不被寫入錯誤遮蔽
        d = self.c.word.current()
        self.assertEqual((d.ui_root, d.undo_head), ({"l": 1}, head))

    def test_route_undo_frozen_before_begin(self):
        self.apply("A")
        self.c._freeze("home", "test")
        self.c.store.budget.disk_budget = self.c.store.budget.used() + 1024
        self.assertEqual(self.c.undo("u1")["code"], "COMMIT_FROZEN")


class RolledBackWithoutEnd(CLBase):
    def test_rolled_back_without_end_has_own_reason(self):
        self.apply("A")
        self.apply("B")
        self.hooks.actions["before_write:route.jsonl:COMMITTED"] = boom      # 收尾 COMMITTED 寫不進
        self.hooks.actions["before_write:coordinator.jsonl:END"] = boom      # 兩種 END 都寫不進；ROLLED_BACK 可寫
        r = self.c.undo("u1")
        self.hooks.actions.clear()
        self.assertEqual(r["code"], "COMMIT_FROZEN")
        dst = os.path.join(self.tmp, "rb")
        shutil.copytree(self.root, dst)
        seg = cl.ActiveStore(dst).best_ptr()[1]["segment_id"]
        recs, _ = cl.Journal.read(os.path.join(dst, "active", f"seg-{seg}", "route.jsonl"))
        self.assertTrue([x for x in recs if x["tx_id"] == "u1" and x["kind"] == "ROLLED_BACK"])
        c2, _ = cl.boot(dst)
        self.assertEqual(c2.slot_state["home"]["reason"], "rolled_back_without_end")


if __name__ == "__main__":
    unittest.main()
