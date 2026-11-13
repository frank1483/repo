"""測試用的選格假後端（範本句＋模型選格，slot_explain）。不連網、不呼叫模型。"""
import re
import threading
import time


def codes(user):
    line = next(l for l in user.splitlines() if l.startswith("只能選："))
    return [part.split(" ", 1)[0] for part in line[len("只能選："):].split("｜")]


class SlotBackend:
    """每格回一個代碼：pick(codes, user) 決定，預設選第一個。可加延遲或閘門測非同步。"""
    name, model = "fake", "fake"

    def __init__(self, pick=None, delay=0.0, gate=None, raw=None):
        self.pick = pick or (lambda cs, user: cs[0])
        self.delay, self.gate, self.raw = delay, gate, raw
        self.calls, self.users = 0, []

    def available(self):
        return True

    def complete_json(self, system, user, schema, timeout_s=None):
        self.calls += 1
        self.users.append(user)
        if self.gate:
            self.gate.wait(5)
        time.sleep(self.delay)
        if self.raw is not None:
            raw = self.raw(user) if callable(self.raw) else self.raw
            return {"ok": True, "data": None, "raw": raw, "latency_s": self.delay, "error": None}
        value = self.pick(codes(user), user)
        return {"ok": True, "data": {"value": value}, "raw": '{"value":"%s"}' % value,
                "latency_s": self.delay, "error": None}
