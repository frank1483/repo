"""ADR-0002 M1 套用提交層（route_apply／route_undo）與啟動恢復，桌面 Python 參考實作。

依「演算法說明 v1：套用提交層與恢復」（adr0002_algo/提交層_演算法說明_v1.md，
使用者 2026-11-17 08:57 回「是」）。只用標準庫。不碰 server.SESSION、/api/plan、planner.py。

重點：
- 安全入站：先宣告（safety_seq += 1、ready=False）、再寫值、再 ready=True；連續來源只在超出 ε 時算事件。
- 發布字 W＝(root_gen, safety_seq)。Python 沒有硬體 CAS，用一把只保護 O(1) 動作的小鎖代替；
  鎖內不做 I/O 或計算。移植時改用真正原子操作。
- 描述元 Descriptor 與 undo 串列節點都是不可變物件；route 根與 undo 頭由同一次 CAS 一起發布。
- route 交易：BEGIN → INTENT/SNAPSHOT/PREPARED（fsync）→ 一致快照 → 鎖外重驗 → CAS(P) → COMMITTED/END。
- GenUI／參數式 UI 交易：此處只有替身 ui_apply（repo 尚無 ADR-0001 §5 的 GenUI 交易），
  發布只比對 root_gen、不比對 safety_seq。
- 活動區分段＋檢查點（分塊）＋雙啟用指標 ptr-A／ptr-B；不刪、不截斷任何紀錄。
數值都是「測試用值」，不是凍結值。
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import threading
import time
from typing import Any, Callable

from .planner_t3 import _canonical

TEST_VALUES = {
    "eps": {"battery": 0.5, "wind_speed": 0.5, "wind_dir": 10.0, "position_m": 5.0},
    "joint_margin_battery_pct": 1.0,
    "max_finalize_attempts": 5,
    "max_not_ready_ms": 500,
    "line_cap_bytes": 256 * 1024,
    "segment_cap_bytes": 32 * 1024 * 1024,
    "segment_cap_lines": 4096,
    "disk_budget_bytes": 2 * 1024 ** 3,
    "terminal_reserve_bytes": 16 * 1024 ** 2,
    "lease_timeout_s": 5.0,
}

DISCRETE_SOURCES = ("no_fly", "policy", "limits", "area", "vehicle")
CONTINUOUS_SOURCES = ("battery", "wind", "position")


class CommitError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SimulatedCrash(Exception):
    """測試用：在指定邊界停下，模擬斷電。"""


class Hooks:
    """在每個邊界呼叫 point(name)。測試可在此丟例外、暫停或記錄順序。"""

    def __init__(self):
        self.actions: dict[str, Callable[[], None]] = {}
        self.trace: list[str] = []

    def point(self, name):
        self.trace.append(name)
        act = self.actions.get(name)
        if act:
            act()


def _sha(obj) -> str:
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()


def _plain(obj):
    """把 tuple 等轉成可 JSON／canonical 的形式。"""
    return json.loads(json.dumps(obj, ensure_ascii=False))


# ---------------- 發布字、描述元、undo 串列 ----------------

@dataclasses.dataclass(frozen=True)
class UndoNode:
    entry: dict
    next: "UndoNode | None"


@dataclasses.dataclass(frozen=True)
class Descriptor:
    root_gen: int
    global_seq: int
    ui_root: Any
    route_roots: tuple          # ((slot_id, root_dict), ...)，root_dict 視為不可變
    undo_head: UndoNode | None

    def route(self, slot_id):
        for s, r in self.route_roots:
            if s == slot_id:
                return r
        return None

    def with_route(self, slot_id, root):
        rr = tuple((s, r) for s, r in self.route_roots if s != slot_id)
        return rr + ((slot_id, root),)


class PublishWord:
    def __init__(self, initial: Descriptor):
        self._lock = threading.Lock()   # 只保護 O(1) 的讀、遞增、比較並替換
        self.root_gen = initial.root_gen
        self.safety_seq = 0
        self.desc = {initial.root_gen: initial}

    def read(self):
        with self._lock:
            return self.root_gen, self.safety_seq

    def current(self) -> Descriptor:
        with self._lock:
            return self.desc[self.root_gen]

    def announce(self):
        with self._lock:
            self.safety_seq += 1
            return self.safety_seq

    def cas_route(self, expect_gen, expect_seq, new: Descriptor) -> bool:
        with self._lock:
            if self.root_gen != expect_gen or self.safety_seq != expect_seq:
                return False
            self.desc[new.root_gen] = new
            self.root_gen = new.root_gen
            return True

    def cas_gen(self, expect_gen, new: Descriptor) -> bool:
        """UI 替身、undo、回滾用：只比對 root_gen（結構寫入租約保證沒有第二個結構發布者）。"""
        with self._lock:
            if self.root_gen != expect_gen:
                return False
            self.desc[new.root_gen] = new
            self.root_gen = new.root_gen
            return True


# ---------------- 安全入站 ----------------

class SafetyIngest:
    def __init__(self, word: PublishWord, eps=None):
        self.word = word
        self.eps = dict(TEST_VALUES["eps"], **(eps or {}))
        self._lk = threading.Lock()     # G0-2：只保護 O(1) 的計數與序號（G0-1）
        self._state = {s: {"value": None, "ready": True, "ref": None, "pending": 0, "next_seq": 0,
                           "applied_seq": 0, "stale": False, "stale_seq": 0}
                       for s in DISCRETE_SOURCES + CONTINUOUS_SOURCES}
        self.events = 0

    @staticmethod
    def _refresh(st):
        st["ready"] = st["pending"] == 0 and not st["stale"]

    def _beyond_eps(self, src, new, ref):
        if ref is None or new is None:
            return True
        e = self.eps
        if src == "battery":
            return abs(new - ref) > e["battery"]
        if src == "wind":
            dd = abs((new["from_deg"] - ref["from_deg"] + 180) % 360 - 180)
            return abs(new["speed_mps"] - ref["speed_mps"]) > e["wind_speed"] or dd > e["wind_dir"]
        if src == "position":
            return (abs(new[0] - ref[0]) ** 2 + abs(new[1] - ref[1]) ** 2) ** 0.5 > e["position_m"]
        return True

    def event(self, src, value, hooks: Hooks | None = None):
        """安全事件（G0-2）：宣告（pending+1、取來源序號、遞增 safety_seq）→ 寫值（舊序號不覆蓋新值）
        → 結束（pending−1；異常結束標 stale，直到之後更新的寫入成功）。pending＝0 且非 stale 才就緒。"""
        st = self._state[src]
        with self._lk:
            st["pending"] += 1
            st["next_seq"] += 1
            seq = st["next_seq"]
            st["ready"] = False
            self.word.announce()
            self.events += 1
        ok = False
        try:
            if hooks:
                hooks.point(f"ingest:{src}:announced")
            v, vref = copy.deepcopy(value), copy.deepcopy(value)     # 複製在臨界區外（G0-1：鎖內只做 O(1)）
            if hooks:
                hooks.point(f"ingest:{src}:before_write")
            with self._lk:
                if seq > st["applied_seq"]:
                    st["value"], st["ref"], st["applied_seq"] = v, vref, seq
                    if st["stale"] and seq > st["stale_seq"]:
                        st["stale"] = False
            ok = True
        finally:
            with self._lk:
                st["pending"] -= 1
                if not ok and seq > st["applied_seq"]:
                    st["stale"], st["stale_seq"] = True, max(st["stale_seq"], seq)
                self._refresh(st)

    def sample(self, src, value, hooks: Hooks | None = None):
        """連續來源的一般樣本：超出 ε 才算事件；ε 內只更新數值。"""
        st = self._state[src]
        if src in DISCRETE_SOURCES or self._beyond_eps(src, value, st["ref"]):
            self.event(src, value, hooks)
        else:
            with self._lk:                       # ε 內：不宣告事件；收到時就取序號，同樣遵守「舊值不覆蓋新值」
                st["next_seq"] += 1
                seq = st["next_seq"]
            v = copy.deepcopy(value)
            if hooks:
                hooks.point(f"ingest:{src}:sample_before_write")
            with self._lk:
                if seq > st["applied_seq"]:
                    st["value"], st["applied_seq"] = v, seq

    def snapshot(self, timeout_ms=None):
        """seqlock 讀法：前後讀 safety_seq 相同且全部 ready 才成立。"""
        timeout = (timeout_ms or TEST_VALUES["max_not_ready_ms"]) / 1000.0
        t0 = time.monotonic()
        while True:
            _, s0 = self.word.read()
            if all(v["ready"] for v in self._state.values()):
                with self._lk:
                    refs = {k: v["value"] for k, v in self._state.items()}
                vals = copy.deepcopy(refs)
                _, s1 = self.word.read()
                if s0 == s1 and all(v["ready"] for v in self._state.values()):
                    return s0, vals
            if time.monotonic() - t0 > timeout:
                raise CommitError("INPUT_NOT_CURRENT", "安全來源未就緒或持續變動")
            time.sleep(0.001)


# ---------------- 日誌 ----------------

class Journal:
    """只追加 JSON Lines；每行含 sha256；寫入後 fsync。讀取時壞行原樣保留在 bad 清單。"""

    def __init__(self, path, hooks: Hooks | None = None, budget: "StorageBudget | None" = None):
        self.path = path
        self.hooks = hooks or Hooks()
        self.budget = budget

    def append(self, rec: dict):
        body = _plain(rec)
        body["sha256"] = _sha({k: v for k, v in body.items() if k != "sha256"})
        line = json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n"
        data = line.encode("utf-8")
        if len(data) > TEST_VALUES["line_cap_bytes"]:
            raise CommitError("LIMIT_EXCEEDED", "單行超過上限")
        if self.budget:
            self.budget.admit(len(data))
        name = os.path.basename(self.path)
        self.hooks.point(f"before_write:{name}:{rec.get('kind')}")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "ab") as f:
            f.write(data)
            f.flush()
            self.hooks.point(f"fsync:{name}:{rec.get('kind')}")
            os.fsync(f.fileno())
        self.hooks.point(f"after_fsync:{name}:{rec.get('kind')}")
        return body

    @staticmethod
    def read(path, max_bytes=None, max_lines=None):
        good, bad = [], []
        if not os.path.exists(path):
            return good, bad
        max_bytes = max_bytes or TEST_VALUES["segment_cap_bytes"]
        max_lines = max_lines or TEST_VALUES["segment_cap_lines"]
        cap = TEST_VALUES["line_cap_bytes"]
        total = 0
        with open(path, "rb") as f:
            for n, raw in enumerate(iter(lambda: f.readline(cap + 1), b"")):
                total += len(raw)
                if n >= max_lines or total > max_bytes:
                    raise CommitError("STORE_READ_ONLY", "恢復掃描超過上限")
                if len(raw) > cap or not raw.endswith(b"\n"):
                    bad.append({"line": n, "reason": "too_long_or_partial", "bytes": len(raw)})
                    continue
                try:
                    rec = json.loads(raw.decode("utf-8"))
                    sha = rec.get("sha256")
                    if sha != _sha({k: v for k, v in rec.items() if k != "sha256"}):
                        raise ValueError("sha")
                    good.append(rec)
                except ValueError:
                    bad.append({"line": n, "reason": "sha_or_json", "bytes": len(raw)})
        return good, bad


class StorageBudget:
    def __init__(self, root, disk_budget=None, reserve=None):
        self.root = root
        self.disk_budget = disk_budget or TEST_VALUES["disk_budget_bytes"]
        self.reserve = reserve or TEST_VALUES["terminal_reserve_bytes"]
        self.terminal_mode = False   # 寫終態時可動用預留

    def used(self):
        tot = 0
        for d, _, files in os.walk(self.root):
            for fn in files:
                try:
                    tot += os.path.getsize(os.path.join(d, fn))
                except OSError:
                    pass
        return tot

    def admit(self, nbytes):
        limit = self.disk_budget - (0 if self.terminal_mode else self.reserve)
        if self.used() + nbytes > limit:
            raise CommitError("STORE_READ_ONLY", "儲存總量不足")


# ---------------- 活動區 ----------------

class ActiveStore:
    def __init__(self, root, hooks: Hooks | None = None, budget: StorageBudget | None = None):
        self.root = root
        self.hooks = hooks or Hooks()
        self.budget = budget or StorageBudget(root)
        os.makedirs(os.path.join(root, "active"), exist_ok=True)

    def seg_dir(self, n):
        return os.path.join(self.root, "active", f"seg-{n}")

    def journal(self, n, name):
        return Journal(os.path.join(self.seg_dir(n), name), self.hooks, self.budget)

    # --- 啟用指標
    def _ptr_path(self, ab):
        return os.path.join(self.root, "active", f"ptr-{ab}.json")

    def read_ptrs(self):
        out = []
        for ab in "AB":
            p = self._ptr_path(ab)
            try:
                with open(p, "rb") as f:
                    rec = json.loads(f.read().decode("utf-8"))
                if _ptr_shape_ok(rec) and rec["sha256"] == _sha({k: v for k, v in rec.items() if k != "sha256"}):
                    out.append((ab, rec))
            except (OSError, ValueError):
                pass
        return out

    def best_ptr(self):
        ptrs = self.read_ptrs()
        if not ptrs:
            return None
        return max(ptrs, key=lambda x: x[1]["seq"])

    def best_valid(self):
        """補件 G0-6：依 seq 由大到小，取第一份「結構與自身 hash 正確、且引用的檢查點可核證」的指標。
        回傳 (ab, rec, checkpoint_state, rejected)；都不行時 (None, None, None, rejected)。"""
        rejected = []
        for ab, rec in sorted(self.read_ptrs(), key=lambda x: -x[1]["seq"]):
            try:
                state = self.read_checkpoint(rec["segment_id"], rec["checkpoint_hash"])
                return ab, rec, state, rejected
            except (CommitError, OSError, ValueError, KeyError, TypeError) as e:
                rejected.append({"pointer": ab, "segment_id": rec["segment_id"],
                                 "reason": getattr(e, "code", type(e).__name__)})
        return None, None, None, rejected

    def write_ptr(self, segment_id, checkpoint_hash):
        cur = self.read_ptrs()
        seq = max([r["seq"] for _, r in cur], default=0) + 1
        best = self.best_ptr()
        ab = "A" if best is None or best[0] == "B" else "B"   # 輪流寫另一份
        rec = {"segment_id": segment_id, "checkpoint_hash": checkpoint_hash, "seq": seq}
        rec["sha256"] = _sha(rec)
        p = self._ptr_path(ab)
        tmp = p + ".tmp"
        self.hooks.point("ptr:before_write")
        with open(tmp, "wb") as f:
            f.write(json.dumps(rec, sort_keys=True).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        self.hooks.point("ptr:before_replace")
        os.replace(tmp, p)
        self.hooks.point("ptr:after_replace")
        return rec

    # --- 檢查點（分塊）
    def next_segment_id(self):
        """新分段一律用沒出現過的編號；中斷留下的不完整分段保留不動。"""
        base = os.path.join(self.root, "active")
        ids = [int(d[4:]) for d in os.listdir(base) if d.startswith("seg-") and d[4:].isdigit()]
        return max(ids, default=-1) + 1

    def write_checkpoint(self, n, state: dict, prev_tail_hash, prev_segment_id=None):
        """state={'global_seq','route_roots':{slot:root},'slot_state':{slot:{state,reason,terminal_ref}},'ui_root'}"""
        j = self.journal(n, "checkpoint.jsonl")
        hashes = []
        chunks = [{"kind": "CHUNK", "part": "ui_root", "data": state.get("ui_root")}]
        for slot, root in sorted(state.get("route_roots", {}).items()):
            chunks.append({"kind": "CHUNK", "part": f"route:{slot}", "data": root})
        chunks.append({"kind": "CHUNK", "part": "slot_state", "data": state.get("slot_state", {})})
        for c in chunks:
            hashes.append(j.append(c)["sha256"])
        man = j.append({"kind": "CHECKPOINT_MANIFEST", "global_seq": state.get("global_seq", 0),
                        "chunk_hashes": hashes, "prev_segment_tail_hash": prev_tail_hash,
                        "prev_segment_id": prev_segment_id})
        return man["sha256"]

    def read_checkpoint(self, n, expect_hash):
        recs, bad = Journal.read(os.path.join(self.seg_dir(n), "checkpoint.jsonl"))
        if bad or not recs or recs[-1].get("kind") != "CHECKPOINT_MANIFEST":
            raise CommitError("CHECKPOINT_INVALID", "檢查點不完整")
        man = recs[-1]
        if man["sha256"] != expect_hash or [r["sha256"] for r in recs[:-1]] != man["chunk_hashes"]:
            raise CommitError("CHECKPOINT_INVALID", "檢查點雜湊不符")
        state = {"global_seq": man["global_seq"], "route_roots": {}, "slot_state": {}, "ui_root": None,
                 "prev_segment_tail_hash": man["prev_segment_tail_hash"],
                 "prev_segment_id": man.get("prev_segment_id")}
        for r in recs[:-1]:
            if r["part"] == "ui_root":
                state["ui_root"] = r["data"]
            elif r["part"] == "slot_state":
                state["slot_state"] = r["data"]
            else:
                state["route_roots"][r["part"].split(":", 1)[1]] = r["data"]
        return state

    def tail_hash(self, n):
        """上一段最後一筆的 sha（只讀各檔最後一行，有界）。"""
        out = {}
        for name in ("checkpoint.jsonl", "coordinator.jsonl", "route.jsonl"):
            p = os.path.join(self.seg_dir(n), name)
            if not os.path.exists(p):
                continue
            with open(p, "rb") as f:
                size = os.path.getsize(p)
                f.seek(max(0, size - TEST_VALUES["line_cap_bytes"]))
                lines = f.read().splitlines()
            if lines:
                try:
                    out[name] = json.loads(lines[-1].decode("utf-8")).get("sha256")
                except ValueError:
                    out[name] = None
        return _sha(out)


def _ptr_shape_ok(rec):
    """指標必須是 {segment_id:int≥0, checkpoint_hash:64 位小寫十六進位, seq:int≥1, sha256:64 位}，不多不少。"""
    if not isinstance(rec, dict) or set(rec) != {"segment_id", "checkpoint_hash", "seq", "sha256"}:
        return False
    hx = set("0123456789abcdef")
    return (type(rec["segment_id"]) is int and rec["segment_id"] >= 0 and type(rec["seq"]) is int and rec["seq"] >= 1
            and all(isinstance(rec[k], str) and len(rec[k]) == 64 and set(rec[k]) <= hx
                    for k in ("checkpoint_hash", "sha256")))


# ---------------- 協調器 ----------------

def _route_root(route_id, points, draft_id, draft_rev, needs_reverify=False, source_tx=None):
    return {"route_id": route_id, "points_hash": _sha({"points": points}), "points": points,
            "draft_id": draft_id, "draft_rev": draft_rev, "needs_reverify": needs_reverify,
            "source_tx": source_tx}


def _same_route(a, b):
    """同一條已提交航線（忽略 needs_reverify 等標記）。"""
    if a is None or b is None:
        return a is b
    keys = ("route_id", "points_hash", "draft_id", "draft_rev", "source_tx")
    return all(a.get(k) == b.get(k) for k in keys)


class Coordinator:
    def __init__(self, store: ActiveStore, ingest_eps=None, hooks: Hooks | None = None, boot_state=None,
                 read_only=False):
        self.read_only = read_only      # G0-6：受限唯讀模式，所有交易回 STORE_READ_ONLY、不寫任何檔
        self.store = store
        self.hooks = hooks or store.hooks
        self.lease = threading.Lock()
        bs = boot_state or {"global_seq": 0, "route_roots": {}, "slot_state": {}, "ui_root": None, "segment": 0,
                            "root_gen": 0}
        self.segment = bs["segment"]
        self.global_seq = bs["global_seq"]
        self.slot_state = dict(bs.get("slot_state", {}))
        init = Descriptor(root_gen=bs.get("root_gen", 0), global_seq=self.global_seq, ui_root=bs.get("ui_root"),
                          route_roots=tuple(sorted(bs.get("route_roots", {}).items())), undo_head=None)
        self.word = PublishWord(init)
        self.ingest = SafetyIngest(self.word, ingest_eps)
        self.cj = store.journal(self.segment, "coordinator.jsonl")
        self.rj = store.journal(self.segment, "route.jsonl")
        self.results: dict[str, dict] = {}   # 冪等：tx_id → 結果

    # --- 共用
    def _acquire(self):
        if not self.lease.acquire(timeout=TEST_VALUES["lease_timeout_s"]):
            raise CommitError("lease_timeout")

    def _begin(self, kind, tx_id, d: Descriptor):
        self.global_seq += 1
        gs = self.global_seq
        self.cj.append({"kind": "BEGIN", "global_seq": gs, "tx_kind": kind, "tx_id": tx_id,
                        "base_roots": {"ui": _sha({"r": d.ui_root}), "route": _sha({"r": _plain(d.route_roots)})}})
        return gs

    def _end(self, gs, tx_id, outcome, d: Descriptor, terminal):
        self.cj.append({"kind": "END", "global_seq": gs, "tx_id": tx_id, "outcome": outcome,
                        "after_roots": {"ui": _sha({"r": d.ui_root}), "route": _sha({"r": _plain(d.route_roots)})},
                        "kind_terminal_sha": terminal.get("sha256") if terminal else None})

    def _freeze(self, slot_id, reason, ref=None):
        self.slot_state[slot_id] = {"state": "FROZEN", "reason": reason, "terminal_ref": ref}

    # --- route_apply
    def route_apply(self, tx_id, slot_id, route_id, points, draft_id, draft_rev,
                    recheck: Callable[[dict], dict], guard=None):
        """recheck(S) → {'action': 'WRITE'|'REDISPLAY'|'BLOCK', 'reasons': [...]}（純函式，鎖外執行）。
        guard(publish) → (code, ok)（G0-9／G0-11）：呼叫端在自己的鎖內核對授權仍有效，有效才呼叫 publish()（＝P 的 CAS）；
        code 非 None 表示授權已失效，交易 ABORTED、零切換。"""
        if tx_id in self.results:
            return self.results[tx_id]
        if self.read_only:
            return {"action": "BLOCK", "code": "STORE_READ_ONLY", "reasons": ["restricted_read_only"]}
        if self.slot_state.get(slot_id, {}).get("state") == "FROZEN":
            return {"action": "BLOCK", "code": "COMMIT_FROZEN", "reasons": [self.slot_state[slot_id]["reason"]]}
        self._acquire()
        try:
            return self._route_apply_locked(tx_id, slot_id, route_id, points, draft_id, draft_rev, recheck, guard)
        finally:
            self.lease.release()

    def _route_apply_locked(self, tx_id, slot_id, route_id, points, draft_id, draft_rev, recheck, guard=None):
        h = self.hooks
        d0 = self.word.current()
        before = d0.route(slot_id)
        after = _route_root(route_id, points, draft_id, draft_rev, False, tx_id)
        try:
            gs = self._begin("route_apply", tx_id, d0)
        except (CommitError, OSError) as e:
            res = {"action": "BLOCK", "tx_id": tx_id, "code": getattr(e, "code", "journal_unwritable"),
                   "reasons": [str(e)]}
            self.results[tx_id] = res
            return res
        h.point("tx:after_begin")
        try:
            self.rj.append({"kind": "INTENT", "tx_id": tx_id, "global_seq": gs, "slot_id": slot_id})
            self.rj.append({"kind": "SNAPSHOT", "tx_id": tx_id, "role": "BEFORE", "slot_id": slot_id, "root": before})
            self.rj.append({"kind": "SNAPSHOT", "tx_id": tx_id, "role": "AFTER", "slot_id": slot_id, "root": after})
            self.rj.append({"kind": "PREPARED", "tx_id": tx_id, "slot_id": slot_id,
                            "before_sha": _sha({"r": before}), "after_sha": _sha({"r": after})})
        except CommitError as e:
            return self._abort(gs, tx_id, slot_id, d0, e.code, [e.detail])
        except OSError as e:
            return self._abort(gs, tx_id, slot_id, d0, "journal_unwritable", [str(e)])
        h.point("tx:after_prepared")

        for attempt in range(TEST_VALUES["max_finalize_attempts"]):
            try:
                seq0, S = self.ingest.snapshot()
            except CommitError as e:
                return self._abort(gs, tx_id, slot_id, d0, e.code, [e.detail])
            h.point("tx:after_snapshot")
            verdict = recheck(S)                       # 鎖外重驗
            h.point("tx:after_recheck")
            if verdict["action"] != "WRITE":
                return self._abort(gs, tx_id, slot_id, d0, verdict["action"], verdict.get("reasons", []),
                                   extra=verdict)
            entry = {"global_seq": gs, "tx_kind": "route_apply", "tx_id": tx_id, "slot_id": slot_id,
                     "before": before, "after": after}
            d1 = Descriptor(root_gen=d0.root_gen + 1, global_seq=gs, ui_root=d0.ui_root,
                            route_roots=d0.with_route(slot_id, after), undo_head=UndoNode(entry, d0.undo_head))
            h.point("tx:before_cas")
            if guard is None:
                ok = self.word.cas_route(d0.root_gen, seq0, d1)
            else:
                code, ok = guard(lambda: self.word.cas_route(d0.root_gen, seq0, d1))
                if code:
                    h.point("tx:guard_rejected")
                    return self._abort(gs, tx_id, slot_id, d0, "BLOCK", [code], code=code)
            if ok:
                h.point("tx:after_cas")
                return self._finish(gs, tx_id, slot_id, d0, d1, before, seq0, recheck)
            h.point("tx:cas_failed")
        return self._abort(gs, tx_id, slot_id, d0, "BLOCK", ["INPUT_NOT_CURRENT"], code="INPUT_NOT_CURRENT")

    def _abort(self, gs, tx_id, slot_id, d0, action, reasons, extra=None, code=None):
        try:
            term = self.rj.append({"kind": "ABORTED", "tx_id": tx_id, "slot_id": slot_id, "action": action,
                                   "reasons": reasons})
            self._end(gs, tx_id, "ABORTED", d0, term)
        except (CommitError, OSError):
            pass   # 沒有 END：BOOT 走「有 BEGIN 無 END」→ 採用 before，結果相同
        res = {"action": action if action in ("REDISPLAY", "BLOCK") else "BLOCK", "tx_id": tx_id,
               "code": code or (action if action not in ("REDISPLAY", "BLOCK") else None), "reasons": reasons}
        if extra:
            res["diffs"] = extra.get("diffs")
        self.results[tx_id] = res
        return res

    def _finish(self, gs, tx_id, slot_id, d0, d1, before, seq0, recheck):
        h = self.hooks
        try:
            term = self.rj.append({"kind": "COMMITTED", "tx_id": tx_id, "slot_id": slot_id,
                                   "after_sha": _sha({"r": d1.route(slot_id)})})
            h.point("tx:after_committed")
            self._end(gs, tx_id, "COMMITTED", d1, term)
        except (CommitError, OSError) as e:
            return self._rollback(gs, tx_id, slot_id, d0, d1, str(e))
        h.point("tx:after_end")
        res = {"action": "WRITE", "tx_id": tx_id, "global_seq": gs, "needs_reverify": False, "reasons": []}
        _, seq_now = self.word.read()
        if seq_now != seq0:                     # P 之後有安全事件 → 重驗，必要時標不可用
            try:
                _, S = self.ingest.snapshot()
                v = recheck(S)
            except CommitError as e:
                v = {"action": "BLOCK", "reasons": [e.code]}
            if v["action"] != "WRITE":
                res["needs_reverify"] = True
                res["reasons"] = v.get("reasons", [])
        self.results[tx_id] = res
        return res

    def _rollback(self, gs, tx_id, slot_id, d0, d1, why):
        # 一次發布：before 航線（標 needs_reverify）＋交易前的 undo 頭，不會出現「新 undo 頭配舊航線」
        before = d0.route(slot_id)
        rr = tuple((s, r) for s, r in d1.route_roots if s != slot_id)
        if before is not None:
            rr = rr + ((slot_id, dict(before, needs_reverify=True)),)
        d2 = Descriptor(d1.root_gen + 1, gs, d0.ui_root, rr, d0.undo_head)
        self.hooks.point("tx:rollback_publish")
        self.word.cas_gen(d1.root_gen, d2)
        self.store.budget.terminal_mode = True
        try:
            term = self.rj.append({"kind": "ROLLED_BACK", "tx_id": tx_id, "slot_id": slot_id, "why": why})
            self._end(gs, tx_id, "ROLLED_BACK", self.word.current(), term)
            res = {"action": "BLOCK", "tx_id": tx_id, "code": "ROLLED_BACK", "reasons": [why]}
        except (CommitError, OSError) as e:
            self._freeze(slot_id, "rollback_unwritable:" + str(e))
            try:
                self._end(gs, tx_id, "COMMIT_FROZEN", self.word.current(), None)
            except (CommitError, OSError):
                pass
            res = {"action": "BLOCK", "tx_id": tx_id, "code": "COMMIT_FROZEN", "reasons": [why, str(e)]}
        finally:
            self.store.budget.terminal_mode = False
        self.results[tx_id] = res
        return res

    # --- UI 替身（ADR-0001 §5 的 GenUI 交易尚未實作；只模擬 ② 生效後的發布）
    def ui_apply(self, tx_id, new_ui_root):
        if self.read_only:
            return {"action": "BLOCK", "code": "STORE_READ_ONLY"}
        self._acquire()
        try:
            d0 = self.word.current()
            gs = self._begin("genui", tx_id, d0)
            self.hooks.point("ui:after_begin")
            entry = {"global_seq": gs, "tx_kind": "genui", "tx_id": tx_id, "before": d0.ui_root, "after": new_ui_root}
            d1 = Descriptor(d0.root_gen + 1, gs, new_ui_root, d0.route_roots, UndoNode(entry, d0.undo_head))
            self.hooks.point("ui:active_durable")          # 替身：ADR-0001 §5 ② 在此生效
            ok = self.word.cas_gen(d0.root_gen, d1)         # 不比對 safety_seq，一定成功
            assert ok, "lease guarantees single structure publisher"
            self._end(gs, tx_id, "COMMITTED", d1, None)
            return {"action": "WRITE", "tx_id": tx_id, "global_seq": gs}
        finally:
            self.lease.release()

    # --- undo（共用 LIFO）
    def undo(self, tx_id):
        if self.read_only:
            return {"action": "BLOCK", "code": "STORE_READ_ONLY"}
        self._acquire()
        try:
            d0 = self.word.current()
            node = d0.undo_head
            if node is None:
                return {"action": "BLOCK", "code": "UNDO_EMPTY"}
            e = node.entry
            gs = self._begin("route_undo" if e["tx_kind"] == "route_apply" else "genui_undo", tx_id, d0)
            if e["tx_kind"] == "route_apply":
                slot = e["slot_id"]
                if not _same_route(d0.route(slot), e["after"]):
                    self._end(gs, tx_id, "ABORTED", d0, None)
                    return {"action": "BLOCK", "code": "UNDO_CONFLICT"}
                if self.slot_state.get(slot, {}).get("state") == "FROZEN":
                    self._end(gs, tx_id, "ABORTED", d0, None)
                    return {"action": "BLOCK", "code": "COMMIT_FROZEN"}
                restored = None if e["before"] is None else dict(e["before"], needs_reverify=True)
                rr = tuple((s, r) for s, r in d0.route_roots if s != slot)
                if restored is not None:
                    rr = rr + ((slot, restored),)
                self.rj.append({"kind": "SNAPSHOT", "tx_id": tx_id, "role": "AFTER", "slot_id": slot, "root": restored})
                d1 = Descriptor(d0.root_gen + 1, gs, d0.ui_root, rr, node.next)
                term = self.rj.append({"kind": "COMMITTED", "tx_id": tx_id, "slot_id": slot,
                                       "after_sha": _sha({"r": restored})})
            else:
                d1 = Descriptor(d0.root_gen + 1, gs, e["before"], d0.route_roots, node.next)
                term = None
            self.hooks.point("undo:before_publish")
            self.word.cas_gen(d0.root_gen, d1)
            self._end(gs, tx_id, "COMMITTED", d1, term)
            return {"action": "WRITE", "tx_id": tx_id, "undid": e["tx_id"], "needs_reverify": True}
        finally:
            self.lease.release()

    # --- 檢查點輸出（BOOT 與分段交接用）
    def state_for_checkpoint(self):
        d = self.word.current()
        return {"global_seq": self.global_seq, "route_roots": {s: r for s, r in d.route_roots},
                "slot_state": copy.deepcopy(self.slot_state), "ui_root": d.ui_root}


# ---------------- 啟動恢復 ----------------

def init_store(root, hooks=None):
    st = ActiveStore(root, hooks)
    if st.best_ptr() is None:
        h = st.write_checkpoint(0, {"global_seq": 0, "route_roots": {}, "slot_state": {}, "ui_root": None}, None)
        st.write_ptr(0, h)
    return st


def boot(root, hooks=None, eps=None):
    """依 ptr-A／ptr-B 與最新分段恢復，寫新分段並切換指標，回傳 (Coordinator, report)。"""
    st = ActiveStore(root, hooks)
    report = {"recovery": [], "frozen": []}
    ab, best_rec, state, rejected = st.best_valid()
    if rejected:
        report["pointer_rejected"] = rejected
    if best_rec is None:
        return _restricted_boot(st, eps, hooks, report)
    seg = best_rec["segment_id"]
    if state.get("prev_segment_id") is not None:
        prev_tail = st.tail_hash(state["prev_segment_id"])
        if state["prev_segment_tail_hash"] != prev_tail:
            for s in state["route_roots"]:
                state["slot_state"][s] = {"state": "FROZEN", "reason": "checkpoint_tail_hash_mismatch"}
            report["frozen"].append("checkpoint_tail_hash_mismatch")
    roots = dict(state["route_roots"])
    slot_state = dict(state["slot_state"])
    ui_root = state["ui_root"]
    coord, cbad = Journal.read(os.path.join(st.seg_dir(seg), "coordinator.jsonl"))
    route, rbad = Journal.read(os.path.join(st.seg_dir(seg), "route.jsonl"))
    if cbad or rbad:
        report["recovery"].append({"bad_lines": {"coordinator": cbad, "route": rbad}})
    by_tx: dict[str, list] = {}
    for r in route:
        by_tx.setdefault(r["tx_id"], []).append(r)
    begins = {r["global_seq"]: r for r in coord if r["kind"] == "BEGIN"}
    ends = {r["global_seq"]: r for r in coord if r["kind"] == "END"}
    gmax = state["global_seq"]
    for gs in sorted(begins):
        b = begins[gs]
        gmax = max(gmax, gs)
        tx = b["tx_id"]
        recs = by_tx.get(tx, [])
        kinds = [r["kind"] for r in recs]
        slot = next((r["slot_id"] for r in recs if "slot_id" in r), None)
        end = ends.get(gs)
        after = next((r["root"] for r in recs if r["kind"] == "SNAPSHOT" and r["role"] == "AFTER"), None)
        if b["tx_kind"] in ("genui", "genui_undo"):
            continue   # 替身不持久化 UI 根；真的 GenUI 交易依 ADR-0001 E-3／E-4 恢復
        if end is None:
            if "COMMITTED" in kinds:
                slot_state[slot] = {"state": "FROZEN", "reason": "committed_without_end", "terminal_ref": tx}
                report["frozen"].append(tx)
            else:
                report["recovery"].append({"tx": tx, "action": "use_before", "why": "begin_without_end"})
            continue
        if end.get("tx_id") != tx:                      # G0-4：交易身分矛盾 → 凍結
            if slot is not None:
                slot_state[slot] = {"state": "FROZEN", "reason": "tx_identity_mismatch", "terminal_ref": tx}
            report["frozen"].append(tx)
            continue
        oc = end["outcome"]
        term = next((r for r in reversed(recs) if r["kind"] in ("COMMITTED", "ABORTED", "ROLLED_BACK")), None)
        if oc == "COMMITTED":
            if term is None or term["kind"] != "COMMITTED" or term["sha256"] != end["kind_terminal_sha"]:
                slot_state[slot] = {"state": "FROZEN", "reason": "terminal_mismatch", "terminal_ref": tx}
                report["frozen"].append(tx)
                continue
            if after is None:
                roots.pop(slot, None)
            else:
                roots[slot] = after
        elif oc == "ABORTED":                            # G0-4
            claimed = end.get("kind_terminal_sha")
            why = None
            if term is not None:
                if term["kind"] != "ABORTED" or term["sha256"] != claimed:
                    why = "aborted_mismatch"
            elif claimed is not None:
                why = "aborted_terminal_missing"
            elif "COMMITTED" in kinds:
                why = "aborted_but_committed"
            else:
                bsnap = next((r for r in recs if r["kind"] == "SNAPSHOT" and r["role"] == "BEFORE"), None)
                prep = next((r for r in recs if r["kind"] == "PREPARED"), None)
                if bsnap is not None and prep is not None and _sha({"r": bsnap["root"]}) != prep["before_sha"]:
                    why = "before_snapshot_mismatch"
                else:
                    report["recovery"].append({"tx": tx, "action": "use_before",
                                               "why": "aborted_without_kind_terminal"})
            if why:
                if slot is not None:
                    slot_state[slot] = {"state": "FROZEN", "reason": why, "terminal_ref": tx}
                report["frozen"].append(tx)
        elif oc == "ROLLED_BACK":
            if term is None or term["kind"] != "ROLLED_BACK":
                slot_state[slot] = {"state": "FROZEN", "reason": "rollback_evidence_missing", "terminal_ref": tx}
                report["frozen"].append(tx)
        elif oc == "COMMIT_FROZEN":
            slot_state[slot] = {"state": "FROZEN", "reason": "commit_frozen", "terminal_ref": tx}
            report["frozen"].append(tx)
    for s in list(roots):
        if roots[s] is not None:
            roots[s] = dict(roots[s], needs_reverify=True)
    new_seg = st.next_segment_id()
    tail = st.tail_hash(seg)
    h = st.write_checkpoint(new_seg, {"global_seq": gmax, "route_roots": roots, "slot_state": slot_state,
                                      "ui_root": ui_root}, tail, seg)
    rj = st.journal(new_seg, "coordinator.jsonl")      # 補件 G0-4：RECOVERY 先持久化，再啟用新指標
    for x in report["recovery"]:
        if x.get("action") == "use_before":
            rj.append({"kind": "RECOVERY", "tx_id": x["tx"], "action": "use_before", "why": x.get("why"),
                       "from_segment": seg})
    st.write_ptr(new_seg, h)
    c = Coordinator(st, eps, hooks, boot_state={"global_seq": gmax, "route_roots": roots, "slot_state": slot_state,
                                                "ui_root": ui_root, "segment": new_seg, "root_gen": 0})
    report["segment"] = new_seg
    return c, report


def _restricted_boot(st: ActiveStore, eps, hooks, report):
    """G0-6：兩份啟用指標都無法驗證。活動區有任何指標檔或分段 → 受限唯讀（不寫檔、停用全部槽、回報診斷）；
    完全空白 → STORE_UNINITIALIZED（要先 init_store）。"""
    base = os.path.join(st.root, "active")
    names = sorted(os.listdir(base)) if os.path.isdir(base) else []
    ptr_files = [n for n in names if n.startswith("ptr-")]
    segs = [n for n in names if n.startswith("seg-")]
    if not ptr_files and not segs:
        raise CommitError("STORE_UNINITIALIZED", "活動區是空白的，請先初始化")
    diag = []
    for ab in "AB":
        p = st._ptr_path(ab)
        if not os.path.exists(p):
            diag.append({"pointer": ab, "result": "missing"})
            continue
        try:
            with open(p, "rb") as f:
                raw = f.read()
            rec = json.loads(raw.decode("utf-8"))
            if not _ptr_shape_ok(rec):
                res = "bad_shape"
            elif rec["sha256"] != _sha({k: v for k, v in rec.items() if k != "sha256"}):
                res = "hash_mismatch"
            else:
                res = "checkpoint_unverifiable"
            diag.append({"pointer": ab, "result": res, "bytes": len(raw)})
        except (OSError, ValueError) as e:
            diag.append({"pointer": ab, "result": "unreadable", "error": repr(e)[:120]})
    report.update(mode="RESTRICTED_READ_ONLY", diagnostics={"pointers": diag, "segments": segs, "files": names,
                                                            "rejected": report.get("pointer_rejected", [])})
    report["frozen"].append("all_slots_restricted_read_only")
    c = Coordinator(st, eps, hooks, boot_state={"global_seq": 0, "route_roots": {}, "slot_state": {},
                                                "ui_root": None, "segment": -1, "root_gen": 0}, read_only=True)
    return c, report
