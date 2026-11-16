"""ADR-0002 覆蓋航點與預覽驗算的固定案例（演算法說明 v1 §6）。規則版，不需要真模型。
首次執行由 Claude 負責，結果與失敗原樣保留。"""
import copy
import json
import math
import os
import tempfile
import unittest

from .energy import Vehicle, Wind
from .planner import _to_ll, zone_violations
from . import coverage as cv

HOME = {"lat": 24.0, "lon": 121.0}
O = (HOME["lat"], HOME["lon"])


def ll(x, y):
    lat, lon = _to_ll(O, (x, y))
    return {"lat": lat, "lon": lon}


SQUARE = [ll(0, 0), ll(100, 0), ll(100, 100), ll(0, 100)]
NFZ_MID = [{"id": "Z1", **ll(50, 50), "radius_m": 15.0}]


def gen(**kw):
    args = dict(area=SQUARE, home=HOME, spacing_m=20)
    args.update(kw)
    return cv.coverage_generate(**args)


def preview(g, takeoff=90, reserve=25, no_fly=None, **kw):
    return cv.preview_check(g, Vehicle(), Wind(), takeoff, reserve, no_fly or [], created_at="fixed", **kw)


def current(takeoff=90, reserve=25, no_fly=None):
    return dict(vehicle=Vehicle(), wind=Wind(), takeoff_pct=takeoff, reserve_req_pct=reserve, no_fly=no_fly or [])


class Generate(unittest.TestCase):
    def test_square_five_lines_full(self):
        g = gen()
        self.assertEqual(g["status"], "OK")
        self.assertEqual(g["stats"]["n_lines"], 5)
        for l in g["lines"]:
            self.assertAlmostEqual(l["planned_len_m"], 100.0, places=6)
            self.assertAlmostEqual(l["kept_len_m"], 100.0, places=6)
        self.assertEqual(g["points"][0]["kind"], "home")
        self.assertEqual(g["points"][-1]["kind"], "home")
        self.assertTrue(all(p["kind"] == "survey" for p in g["points"][1:-1]))
        r = preview(g)
        self.assertAlmostEqual(r["coverage"]["total"], 1.0, places=9)
        self.assertEqual(r["result"], "pass", r["reasons"])

    def test_nfz_cut_matches_hand_calc(self):
        g = gen(no_fly=NFZ_MID)
        R = 15.0 * 1.35
        h = math.sqrt(R * R - 20.0 ** 2)
        kept = {l["line_no"]: l["kept_len_m"] for l in g["lines"]}
        self.assertAlmostEqual(kept[3], 100 - 2 * R, places=6)          # 59.5
        self.assertAlmostEqual(kept[2], 100 - 2 * h, places=6)          # 93.656
        self.assertAlmostEqual(kept[4], 100 - 2 * h, places=6)
        self.assertAlmostEqual(kept[1], 100.0, places=6)
        self.assertAlmostEqual(kept[5], 100.0, places=6)
        g3 = [l for l in g["lines"] if l["line_no"] == 3][0]
        self.assertEqual(len(g3["gaps"]), 1)
        self.assertAlmostEqual(g3["gaps"][0]["from_m"], 50 - R, places=6)
        self.assertEqual(g3["gaps"][0]["reason"], "NFZ:Z1")
        # 生成的航線本身不穿越原始禁航區（連接段兩點方框）
        self.assertEqual(zone_violations(g["points"], NFZ_MID, O), [])
        self.assertTrue(any(p["kind"] == "connector" for p in g["points"]))
        r = preview(g, no_fly=NFZ_MID)
        self.assertEqual(r["result"], "fail")
        total = (500 - 2 * R - 4 * h) / 500
        self.assertAlmostEqual(r["coverage"]["total"], total, places=9)
        codes = [x["code"] for x in r["reasons"]]
        self.assertIn("LINE_COVERAGE_LOW", codes)
        self.assertIn("HINT", codes)
        self.assertNotIn("NFZ_CROSSING", codes)
        self.assertTrue(any(x["detail"].startswith("L03 預計完成") for x in r["reasons"]))

    def test_missing_spacing(self):
        g = cv.coverage_generate(area=SQUARE, home=HOME)
        self.assertEqual(g["status"], "MISSING")
        self.assertEqual(g["missing"], ["spacing_m"])

    def test_camera_spacing_first(self):
        cam = {"sensor_width_mm": 13.2, "focal_mm": 8.8, "side_overlap": 0.7}
        g = gen(camera=cam, alt_m=20)  # 20*13.2/8.8=30 → 30*0.3=9
        self.assertEqual(g["stats"]["spacing_source"], "camera")
        self.assertAlmostEqual(g["stats"]["spacing_m"], 9.0, places=9)

    def test_concave_unsupported(self):
        L = [ll(0, 0), ll(100, 0), ll(100, 50), ll(50, 50), ll(50, 100), ll(0, 100)]
        self.assertEqual(gen(area=L)["status"], "UNSUPPORTED_CONCAVE")

    def test_invalid(self):
        self.assertEqual(gen(spacing_m=0)["status"], "INVALID")
        bow = [ll(0, 0), ll(100, 100), ll(100, 0), ll(0, 100)]
        self.assertEqual(gen(area=bow)["status"], "INVALID")

    def test_start_corner_nearest_home(self):
        g = gen()
        first, want = g["points"][1], ll(0, 10)  # 左下角那條線的起點
        self.assertAlmostEqual(first["lat"], want["lat"], places=9)
        self.assertAlmostEqual(first["lon"], want["lon"], places=9)

    def test_deterministic(self):
        self.assertEqual(gen(no_fly=NFZ_MID)["route_id"], gen(no_fly=NFZ_MID)["route_id"])


class PreviewAndApply(unittest.TestCase):
    def setUp(self):
        self.g = gen()
        self.rec = preview(self.g, takeoff=90, reserve=25)

    def test_ac7a_small_change_confirm(self):
        self.assertEqual(self.rec["result"], "pass")
        chk = cv.apply_check(self.rec, **current(takeoff=89))
        self.assertEqual(chk["decision"], "CONFIRM", chk)

    def test_ac7b_large_change_confirm_with_diff(self):
        chk = cv.apply_check(self.rec, **current(takeoff=75))
        self.assertEqual(chk["decision"], "CONFIRM_WITH_DIFF", chk)
        self.assertTrue(any(d["field"] == "est_end_pct" for d in chk["diffs"]))

    def test_below_reserve_blocks(self):
        chk = cv.apply_check(self.rec, **current(takeoff=26))
        self.assertEqual(chk["decision"], "BLOCK")
        self.assertIn("BATTERY_BELOW_RESERVE", [r["code"] for r in chk["reasons"]])

    def test_ac10_new_nfz_blocks_original_route(self):
        z = [{"id": "Z9", **ll(50, 30), "radius_m": 5.0}]
        before = copy.deepcopy(self.rec["route"])
        chk = cv.apply_check(self.rec, **current(no_fly=z))
        self.assertEqual(chk["decision"], "BLOCK")
        self.assertEqual(chk["hint"], "NEW_PREVIEW")
        self.assertEqual(self.rec["route"], before)  # 原航線不改

    def test_ac11_limit_change_listed_once(self):
        chk = cv.apply_check(self.rec, **current(reserve=30))
        self.assertEqual(chk["decision"], "CONFIRM_WITH_DIFF")
        self.assertEqual([d["field"] for d in chk["diffs"] if d["kind"] == "limit"], ["reserve_req_pct"])

    def test_ac12_battery_drop_before_write_blocks(self):
        written = []
        ok = cv.confirm_and_write(self.rec, written.append, **current(takeoff=89))
        self.assertTrue(ok["written"])
        written.clear()
        res = cv.confirm_and_write(self.rec, written.append, **current(takeoff=26))
        self.assertFalse(res["written"])
        self.assertEqual(written, [])
        self.assertTrue(res["check"]["reasons"])

    def test_reserve_eff_uses_max_and_vehicle_not_mutated(self):
        v = Vehicle()
        r = cv.preview_check(self.g, v, Wind(), 90, 10, [])
        self.assertEqual(r["reserve_eff_pct"], 20.0)
        self.assertEqual(v.reserve_pct, 20.0)
        r = cv.preview_check(self.g, v, Wind(), 90, 25, [])
        self.assertEqual(r["reserve_eff_pct"], 25.0)
        self.assertEqual(v.reserve_pct, 20.0)

    def test_survey_points_have_no_hover(self):
        e = self.rec["time_s"]
        self.assertGreater(e, 0)
        self.assertFalse(any(p["kind"] == "target" for p in self.rec["route"]))

    def test_ac9_store_roundtrip_and_version(self):
        with tempfile.TemporaryDirectory() as d:
            st = cv.PreviewStore(os.path.join(d, "previews.jsonl"))
            aid = st.append(self.rec)
            got = st.get(aid)
        self.assertEqual(got["route"], json.loads(json.dumps(self.rec["route"])))
        self.assertEqual(cv.recompute_version(got), self.rec["preview_version"])
        self.assertEqual(cv.recompute_version(self.rec), self.rec["preview_version"])

    def test_version_binds_takeoff_and_reserve(self):
        a = preview(self.g, takeoff=90, reserve=25)["preview_version"]
        self.assertNotEqual(a, preview(self.g, takeoff=89, reserve=25)["preview_version"])
        self.assertNotEqual(a, preview(self.g, takeoff=90, reserve=26)["preview_version"])

    def test_ac6_session_untouched(self):
        from . import server
        s = server.SESSION
        keys = ("mission", "plan", "chosen", "run", "replans", "alerts", "current_state", "active_event", "report")
        snap = json.dumps({k: getattr(s, k) for k in keys}, default=str, sort_keys=True, ensure_ascii=False)
        rec = preview(gen(no_fly=NFZ_MID), no_fly=NFZ_MID)
        cv.apply_check(rec, **current(no_fly=NFZ_MID))
        cv.confirm_and_write(self.rec, lambda r: None, **current())
        after = json.dumps({k: getattr(s, k) for k in keys}, default=str, sort_keys=True, ensure_ascii=False)
        self.assertEqual(snap, after)


if __name__ == "__main__":
    unittest.main()
