"""ADR-0002 G1（範圍 B）首跑前修正（CODEX-APP-0445）：RF-08 逐條件、首敗停止、F-1 真實重驗、D-3 受控重啟。規則版。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from . import commit_layer as cl
from . import coverage as cv
from . import g1_runner as G
from .energy import Vehicle, Wind
from .route_recheck import make_route_recheck
from .test_commit_layer import HOME, PTS, SQUARE, seed
from .test_commit_layer import Base as CLBase


def rel(p):
    return os.path.relpath(p, G.BASE).replace(os.sep, "/")


class Fixture:
    """在 repo 內建一個「原本可放行」的最小 manifest；_git／_blob／effective_config 以替身固定。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="g1c_", dir=G.HERE)
        self.code_rel = rel(os.path.join(self.tmp, "fake.py"))
        self.code_repo_path = os.path.relpath(os.path.join(self.tmp, "fake.py"), G.REPO).replace(os.sep, "/")
        with open(os.path.join(self.tmp, "fake.py"), "wb") as f:
            f.write(b"x = 1\r\n")                          # checkout 是 CRLF，blob 是 LF
        self.blob = b"x = 1\n"
        self.commit = "c" * 40
        self.files = {}

        def put(name, obj_or_bytes):
            b = obj_or_bytes if isinstance(obj_or_bytes, bytes) else G.canonical(obj_or_bytes)
            p = os.path.join(self.tmp, name)
            with open(p, "wb") as f:
                f.write(b)
            self.files[name] = b
            return {"relative_path": rel(p), "sha256": G.sha(b), "bytes": len(b)}
        inv = put("inv.json", {"schema_version": "CodeInventory/1", "repo": "r", "commit": self.commit,
                               "entries": [{"kind": "code", "path": self.code_repo_path,
                                            "sha256": G.sha(self.blob), "bytes": len(self.blob)}]})
        pol = put("pol.json", {"schema_version": "PolicyProfile/1", "id": "p", "version": "v1", "keys": [],
                               "bound_effective_config": [{"module": "m", "key": "k", "value": 1}]})
        sig = put("sig.md", b"signoff")
        g0m = put("g0m.json", b"{}")
        mat = put("mat.md", b"matrix")
        res = put("res.json", {"gate_id": "ADR-0002:G0", "outcome": "SIGNED_OFF",
                               "signoff_ref": {"id": "s", "version": "v", "sha256": sig["sha256"]},
                               "g0_manifest_sha256": g0m["sha256"]})
        self.srcs = [dict(inv, role="code_inventory"), dict(pol, role="policy_profile"), dict(sig, role="g0_signoff"),
                     dict(g0m, role="g0_manifest"), dict(mat, role="matrix"), dict(res, role="dependency_result")]
        self.res_sha, self.pol_sha = res["sha256"], pol["sha256"]

    def manifest(self, **over):
        m = {"schema_version": "GateManifest/1", "gate_id": "ADR-0002:G1",
             "scope": {"platform": "desktop-windows-pc", "backend": "python-reference", "feature_ids": [],
                       "trial_ids": ["gcs_demo.test_a", "gcs_demo.test_b"]},
             "sources": sorted(self.srcs, key=lambda s: (s["role"], s["relative_path"])),
             "dependencies": [{"gate_id": "ADR-0002:G0", "result_sha256": self.res_sha}],
             "stop_profile_ref": {"id": "p", "version": "v1", "sha256": self.pol_sha},
             "evidence_requirements": [], "permitted_actions": [], "authoritative_decision_refs": []}
        for k, v in over.items():
            if v is None:
                m.pop(k)
            else:
                m[k] = v
        b = G.canonical(m)
        p = os.path.join(self.tmp, "man.json")
        with open(p, "wb") as f:
            f.write(b)
        return p, G.sha(b)

    def patches(self, head=None, dirty="", eff=None):
        return [mock.patch.object(G, "_git", side_effect=lambda *a: (head or self.commit) if a[0] == "rev-parse"
                                  else dirty),
                mock.patch.object(G, "_blob", return_value=self.blob),
                mock.patch.object(G, "effective_config", return_value=eff or {"m": {"k": 1}})]

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RF08EachCondition(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()

    def tearDown(self):
        self.fx.close()

    def check(self, path_sha, reason_prefix, **patch_kw):
        p, h = path_sha
        ps = self.fx.patches(**patch_kw)
        [x.start() for x in ps]
        try:
            ok, reasons, _ = G.verify(p, h)
        finally:
            [x.stop() for x in ps]
        self.assertFalse(ok, reason_prefix)
        self.assertTrue(any(r.startswith(reason_prefix) for r in reasons), (reason_prefix, reasons))

    def test_valid_fixture_passes(self):
        p, h = self.fx.manifest()
        ps = self.fx.patches()
        [x.start() for x in ps]
        try:
            ok, reasons, _ = G.verify(p, h)
        finally:
            [x.stop() for x in ps]
        self.assertEqual((ok, reasons), (True, []))

    def test_each_condition_rejects(self):
        fx = self.fx
        good_scope = {"platform": "desktop-windows-pc", "backend": "python-reference", "feature_ids": [],
                      "trial_ids": ["gcs_demo.test_a"]}
        self.check(fx.manifest(extra=1), "manifest_keys_not_closed")
        self.check(fx.manifest(scope=dict(good_scope, backend="cpp")), "scope_backend_not_python_reference")
        self.check(fx.manifest(scope=dict(good_scope, extra=1)), "scope_keys_not_closed")
        self.check(fx.manifest(scope=dict(good_scope, trial_ids=[])), "trial_ids_empty_or_duplicate")
        self.check(fx.manifest(scope=dict(good_scope, trial_ids=["gcs_demo.test_a", "gcs_demo.test_a"])),
                   "trial_ids_empty_or_duplicate")
        self.check(fx.manifest(sources=[s for s in fx.srcs if s["role"] != "matrix"]), "required_sources_missing")
        self.check(fx.manifest(sources=[dict(fx.srcs[0], extra=1)] + fx.srcs[1:]), "source_keys_not_closed")
        self.check(fx.manifest(stop_profile_ref={"id": "p", "version": "v1", "sha256": "0" * 64}),
                   "stop_profile_ref_unresolved")
        self.check(fx.manifest(dependencies=[]), "dependencies_not_exactly_G0")
        self.check(fx.manifest(dependencies=[{"gate_id": "ADR-0002:G0", "result_sha256": "1" * 64}]),
                   "dependency_unverified")
        self.check(fx.manifest(), "commit_mismatch", head="d" * 40)
        self.check(fx.manifest(), "worktree_dirty", dirty=" M x")
        self.check(fx.manifest(), "config_mismatch", eff={"m": {"k": 2}})

    def test_released_chain_required(self):
        fx = self.fx
        fx.files  # noqa: B018
        res = json.loads(fx.files["res.json"])
        res["outcome"] = "PENDING"
        b = G.canonical(res)
        with open(os.path.join(fx.tmp, "res.json"), "wb") as f:
            f.write(b)
        srcs = [dict(s, sha256=G.sha(b), bytes=len(b)) if s["role"] == "dependency_result" else s for s in fx.srcs]
        self.check(fx.manifest(sources=srcs, dependencies=[{"gate_id": "ADR-0002:G0", "result_sha256": G.sha(b)}]),
                   "dependency_not_released")

    def test_git_failure_is_a_reason_not_a_crash(self):
        p, h = self.fx.manifest()
        with mock.patch.object(G, "_git", side_effect=G.GitError("boom")), \
                mock.patch.object(G, "effective_config", return_value={"m": {"k": 1}}):
            ok, reasons, _ = G.verify(p, h)
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("code_inventory_unverifiable") for r in reasons))

    def test_checkout_must_equal_blob_after_eol_normalization(self):
        with open(os.path.join(self.fx.tmp, "fake.py"), "wb") as f:
            f.write(b"x = 2\r\n")
        self.check(self.fx.manifest(), "checkout_differs")

    def test_not_released_starts_no_test_process(self):
        p, h = self.fx.manifest(extra=1)
        out = os.path.join(self.fx.tmp, "run")
        ps = self.fx.patches()
        [x.start() for x in ps]
        try:
            with mock.patch.object(G.subprocess, "run") as run:
                self.assertEqual(G.main(["--manifest", p, "--sha256", h, "--out", out]), 2)
                self.assertFalse([c for c in run.call_args_list if "unittest" in c.args[0]])
        finally:
            [x.stop() for x in ps]
        self.assertEqual(json.load(open(os.path.join(out, "RUN_INFO.json"), encoding="utf-8"))["result"], "NOT_RELEASED")

    def test_first_failure_stops_later_trials(self):
        p, h = self.fx.manifest()
        out = os.path.join(self.fx.tmp, "run2")
        ps = self.fx.patches()
        [x.start() for x in ps]
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return type("P", (), {"returncode": 1, "stdout": "FAILED", "stderr": ""})()
        try:
            with mock.patch.object(G.subprocess, "run", side_effect=fake_run):
                self.assertEqual(G.main(["--manifest", p, "--sha256", h, "--out", out]), 1)
        finally:
            [x.stop() for x in ps]
        info = json.load(open(os.path.join(out, "RUN_INFO.json"), encoding="utf-8"))
        self.assertEqual(len([c for c in calls if "unittest" in c]), 1)       # 第二套沒有啟動
        self.assertEqual(info["stop_reason"], "first_failure_stops_later_trials:gcs_demo.test_a")
        self.assertEqual(info["result"], "FAIL")


class F1RealRecheck(CLBase):
    def test_hard_margin_from_real_recheck_no_event_zero_publish(self):
        """真實的 route_recheck（不是直接指定 BLOCK）在沒有新安全事件時，因硬性餘裕不足擋下，零發布。"""
        g = cv.coverage_generate(area=SQUARE, home=HOME, spacing_m=20)
        rec = cv.preview_check(g, Vehicle(), Wind(), 90, 25, [])
        rc = make_route_recheck(rec, Vehicle(), {"reserve_req_pct": 25, "max_alt_m": 120})
        S = {"wind": {"speed_mps": 0.0, "from_deg": 0.0}, "no_fly": [], "limits": {"reserve_req_pct": 25, "max_alt_m": 120},
             "position": (0.0, 0.0), "vehicle": {"id": "UAV-01"}}
        b = 100.0
        while b > 26 and rc(dict(S, battery=b))["reasons"] != ["JOINT_MARGIN_BATTERY"]:
            b = round(b - 0.05, 2)
        self.assertEqual(rc(dict(S, battery=b))["reasons"], ["JOINT_MARGIN_BATTERY"])
        self.assertEqual(cv.apply_check(rec, vehicle=Vehicle(), wind=Wind(), takeoff_pct=b, reserve_req_pct=25,
                                        no_fly=[])["decision"] != "BLOCK", True)   # 名目上通過，只有保守上界不過
        self.c.ingest.event("battery", b)
        _, seq0 = self.c.word.read()
        g0 = self.c.word.root_gen
        r = self.c.route_apply("t-hm", "home", rec["route_id"], rec["route"], "d1", 1, rc)
        _, seq1 = self.c.word.read()
        self.assertEqual((r["action"], r["reasons"]), ("BLOCK", ["JOINT_MARGIN_BATTERY"]))
        self.assertEqual(seq1, seq0)                                  # 沒有新的安全事件
        self.assertEqual(self.c.word.root_gen, g0)
        self.assertIsNone(self.c.word.current().route("home"))


class D3ControlledRestart(CLBase):
    def test_exhausted_store_controlled_boot_restores_eligibility(self):
        """D-3（G1 範圍）：耗盡後拒絕新交易；同一儲存受控 BOOT 開新世代，序號歸零、已提交根恢復，新交易可再進行。"""
        self.apply("A")
        self.c.word.safety_seq = 2 ** cl.TEST_VALUES["safety_seq_bits"] - 1
        with self.assertRaises(cl.CommitError):
            self.c.ingest.event("policy", {"v": "x"})
        self.assertEqual(self.apply("B")["code"], "W_EPOCH_EXHAUSTED")
        c2, rep = cl.boot(self.root)                                 # 受控重啟
        self.assertEqual(c2.word.read()[1], 0)
        self.assertFalse(c2.word.exhausted)
        self.assertEqual(c2.word.current().route("home")["route_id"], "r-A")
        self.assertTrue(c2.word.current().route("home")["needs_reverify"])
        seed(c2)
        self.assertEqual(c2.route_apply("C", "home", "r-C", PTS, "d1", 2, lambda S: {"action": "WRITE", "reasons": []})["action"],
                         "WRITE")


class D3OldTokensInvalidAfterRestart(unittest.TestCase):
    def test_old_boot_epoch_request_rejected(self):
        from .test_preview_api import Base as PVBase

        class T(PVBase):
            def runTest(inner):
                pass
        t = T()
        t.setUp()
        try:
            p = t.preview()
            ch, tok = __import__("gcs_demo.test_g0", fromlist=["TokenRevocation"]).TokenRevocation._confirm(t, p)
            t.svc.boot_epoch = 8                                     # 受控重啟後的新 boot epoch
            st, js, _ = t.raw("POST", "/api/preview/commit",
                              {"boot_epoch": 7, "request_epoch": 999, "session_id": t.sid, "target_slot_id": "home",
                               "nonce": "n1", "apply_intent_id": ch["apply_intent_id"], "shown_hash": ch["shown_hash"],
                               "confirm_token": tok})
            self.assertEqual((st, js["error"]["code"]), (409, "EPOCH_STALE"))
            self.assertIsNone(t.coord.word.current().route("home"))
        finally:
            t.tearDown()


if __name__ == "__main__":
    unittest.main()
