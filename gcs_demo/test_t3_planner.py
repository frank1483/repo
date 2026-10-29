"""New offline Part B tests; Claude owns first execution, retain first failure."""
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from .energy import Vehicle, Wind
from .llm import LLMBackend
from .planner import plan_mission, replan, check_apply, _evaluate, _to_xy, rule_choice
from .planner_t3 import mission_version, replan_context, constraint_deltas
from . import server
from .flightlog import load_plan
from .report import build_facts
from .report_t3 import timeline_text


def fixture():
    # Synthetic battery/flat tiny route to isolate hover budget; not x500 data.
    m = {"name": "合成測試", "home": {"id": "H", "lat": 24, "lon": 121},
         "cruise_alt_m": 0, "speed_mps": 8, "no_fly": [], "limits": {"max_altitude_m": 120},
         "targets": [{"id": str(i), "lat": 24 + i * 0.000001, "lon": 121,
                      "alt": 0, "priority": 1} for i in range(1, 7)]}
    return m, Vehicle(battery_wh=1.8, usable_frac=1), Wind()


def state_for(m):
    return {"lat": 24, "lon": 121, "alt": 0, "battery_pct": 80,
            "observed_ratio": 1.2345, "remaining": [t["id"] for t in m["targets"]], "completed": []}


class T3PlannerTests(unittest.TestCase):
    def plan(self, m, v, w):
        return plan_mission(m, v, w, backend=LLMBackend())

    def test_cross_runtime_vectors(self):
        data = json.loads(Path(__file__).with_name("t3_version_vectors.json").read_text(encoding="utf-8"))
        for vector in data:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(mission_version(**vector["inputs"]), vector["mission_version"])

    def test_dictionary_order_and_numeric_equivalence(self):
        m, v, w = fixture()
        self.assertEqual(mission_version(m, v, w), mission_version(dict(reversed(list(m.items()))), v.to_dict(), {"from_deg": 0.0, "speed_mps": 0.0}))

    def test_all_four_inputs_invalidate(self):
        m, v, w = fixture()
        s = state_for(m)
        result = {"mission_version": mission_version(m, v, w, s)}
        self.assertTrue(check_apply(result, m, v, w, s)["ok"])
        for index in range(4):
            args = [copy.deepcopy(m), copy.copy(v), copy.copy(w), copy.deepcopy(s)]
            if index == 0:
                args[0]["targets"][0]["lat"] += 0.01
            elif index == 1:
                args[1].calib += 0.1
            elif index == 2:
                args[2].speed_mps += 1
            else:
                args[3]["battery_pct"] -= 1
            self.assertEqual(check_apply(result, *args), {"ok": False, "reason_zh": "任務已變更，請重新規劃"})

    def test_array_order_matters_and_snapshots_not_mutated(self):
        m, v, w = fixture()
        out = self.plan(m, v, w)
        before = copy.deepcopy(out)
        m["targets"].reverse()
        self.assertFalse(check_apply(out, m, v, w)["ok"])
        self.assertEqual(out, before)

    def test_absent_and_nonfinite_version_fail_closed(self):
        m, v, w = fixture()
        self.assertFalse(check_apply({}, m, v, w)["ok"])
        out = self.plan(m, v, w)
        m["speed_mps"] = float("nan")
        self.assertFalse(check_apply(out, m, v, w)["ok"])

    def test_replan_effective_context_for_each_event(self):
        m, v, w = fixture()
        s = state_for(m)
        events = [{"type": "wind", "speed_mps": 4, "from_deg": 90},
                  {"type": "battery", "battery_pct": 70},
                  {"type": "no_fly", "zone": {"id": "Z", "lat": 25, "lon": 122, "radius_m": 10}},
                  {"type": "add_target", "target": {"id": "NEW", "lat": 24.001, "lon": 121, "alt": 0}}]
        saved = copy.deepcopy((m, v, w, s))
        for event in events:
            out = replan(m, v, w, s, event, backend=LLMBackend())
            context = replan_context(m, v, w, s, event)
            self.assertTrue(check_apply(out, *context)["ok"])
            self.assertEqual(context[1].calib, 1.235)
            self.assertFalse(any(c["id"] == "S1" for c in out["candidates"]))
            context[3]["remaining"].reverse()
            self.assertFalse(check_apply(out, *context)["ok"])
        self.assertEqual((m, v, w, s), saved)

    def test_s1_two_independent_feasible_sorties(self):
        m, v, w = fixture()
        out = self.plan(m, v, w)
        split = next(c for c in out["candidates"] if c["id"] == "S1")
        self.assertEqual(out["rule_choice"], "")  # 使用者 10/28：分兩趟只列建議，不當預設
        self.assertFalse(any(c["feasible"] for c in out["candidates"] if c["id"] != "S1"))
        self.assertEqual(sorted(split["order"]), sorted(t["id"] for t in m["targets"]))
        self.assertEqual(len(split["order"]), len(set(split["order"])))
        self.assertEqual(split["path"], [])
        self.assertTrue(split["requires_battery_swap"])
        for sub in split["sorties"]:
            self.assertTrue(sub["feasible"])
            self.assertGreaterEqual(sub["end_pct"], v.reserve_pct)
            self.assertEqual(sub["path"][0]["kind"], "home")
            self.assertEqual(sub["path"][-1]["kind"], "home")
            self.assertEqual(sub["missing_must"], [])
            self.assertEqual(sub["constraint_deltas"], [])
            used = sum(l["energy_wh"] for l in sub["legs"])
            self.assertAlmostEqual(sub["end_pct"], 100 - used / 1.8 * 100, delta=1)
        self.assertEqual(split["end_pct"], min(s["end_pct"] for s in split["sorties"]))
        self.assertAlmostEqual(split["energy_wh"], sum(s["energy_wh"] for s in split["sorties"]), places=1)

    def test_s1_absent_when_single_sortie_covers_all(self):
        m, v, w = fixture()
        v.battery_wh = 90
        out = self.plan(m, v, w)
        self.assertFalse(any(c["id"] == "S1" for c in out["candidates"]))
        self.assertNotEqual(out["pick"]["decision"], "HOLD")

    def test_insufficient_two_sortie_budget_stays_hold(self):
        m, v, w = fixture()
        v.battery_wh = 0.2
        out = self.plan(m, v, w)
        self.assertFalse(any(c["id"] == "S1" for c in out["candidates"]))
        self.assertEqual(out["pick"]["decision"], "HOLD")
        bad = next(e for e in out["evidence"] if e.get("value", {}).get("violations"))
        self.assertTrue(any(x["violated"] == "reserve" and x["short_pct"] > 0 for x in bad["value"]["violations"]))

    def test_s1_does_not_hide_altitude_failure(self):
        m, v, w = fixture()
        m["targets"][0]["alt"] = 121
        out = self.plan(m, v, w)
        self.assertFalse(any(c["id"] == "S1" for c in out["candidates"]))

    def test_exact_quantified_constraints(self):
        m, v, w = fixture()
        m["no_fly"] = [{"id": "Z", "lat": 24, "lon": 121, "radius_m": 10}]
        path = [{"id": "a", "lat": 24, "lon": 121, "alt": 125},
                {"id": "b", "lat": 24, "lon": 121.001, "alt": 0}]
        deltas = constraint_deltas(m, v, path, {"margin_pct": -4.2}, ["missing"], _to_xy)
        self.assertIn({"violated": "reserve", "short_pct": 4.2}, deltas)
        self.assertIn({"violated": "altitude", "point_id": "a", "over_m": 5}, deltas)
        self.assertIn({"violated": "required_targets", "missing_count": 1, "target_ids": ["missing"]}, deltas)
        zone = next(d for d in deltas if d["violated"] == "no_fly")
        self.assertEqual(zone["short_m"], 10)

    def test_rule_choice_prefers_coverage_without_changing_tie_rule(self):
        a = {"id": "C", "order": [1], "feasible": True, "energy_wh": 1, "must_rank": 0}
        b = {"id": "S1", "order": [1, 2], "feasible": True, "energy_wh": 2, "must_rank": 1}
        self.assertEqual(rule_choice([a, b]), "S1")
        b["order"] = [1]
        self.assertEqual(rule_choice([a, b]), "C")

    def test_server_gates_stale_plan_before_mutation(self):
        m, v, w = fixture()
        session = server.Session()
        session.mission, session.wind = m, w
        session.vehicle = lambda: v
        session.plan = self.plan(m, v, w)
        token = session.plan["mission_version"]
        m["targets"][0]["lon"] += 0.001
        with patch.object(server, "SESSION", session), patch.object(server, "MissionRun") as run:
            out = server.handle("/api/start", {"choice_id": "C1", "mission_version": token})
            self.assertFalse(out["ok"])
            run.assert_not_called()
            self.assertIsNone(session.chosen)

    def test_server_rejects_missing_preview_token(self):
        m, v, w = fixture()
        session = server.Session()
        session.mission, session.wind, session.vehicle = m, w, lambda: v
        session.plan = self.plan(m, v, w)
        with patch.object(server, "SESSION", session), patch.object(server, "MissionRun") as run:
            self.assertFalse(server.handle("/api/start", {"choice_id": "S1"})["ok"])
            run.assert_not_called()

    def test_server_does_not_flatten_s1(self):
        m, v, w = fixture()
        session = server.Session()
        session.mission, session.wind, session.vehicle = m, w, lambda: v
        session.plan = self.plan(m, v, w)
        with patch.object(server, "SESSION", session), patch.object(server, "MissionRun") as run:
            out = server.handle("/api/start", {"choice_id": "S1", "mission_version": session.plan["mission_version"]})
            self.assertIn("兩個獨立架次", out["reason_zh"])
            run.assert_not_called()
            self.assertIsNone(session.chosen)

    def test_server_stale_replan_never_flies_or_sets_choice(self):
        m, v, w = fixture()
        s, event = state_for(m), {"type": "wind", "speed_mps": 1, "from_deg": 90}
        session = server.Session()
        session.mission, session.wind, session.vehicle = m, w, lambda: v
        result = replan(m, v, w, s, event, backend=LLMBackend())
        session.replans, session.current_state, session.active_event = [result], copy.deepcopy(s), event
        session.current_state["battery_pct"] -= 1
        session.run = Mock()
        with patch.object(server, "SESSION", session):
            out = server.handle("/api/continue", {"choice_id": "R1", "mission_version": result["mission_version"]})
        self.assertFalse(out["ok"])
        session.run.fly.assert_not_called()
        self.assertNotIn("final_choice", result)


class T3Corrections0316Tests(unittest.TestCase):
    def test_takeoff_separate_target_ids_preserve_source_item(self):
        doc = {"fileType": "Plan", "mission": {"plannedHomePosition": [24, 121, 100], "hoverSpeed": 8,
               "items": [{"type": "SimpleItem", "command": 22, "frame": 3, "params": [0, 0, 0, 0, 24, 121, 5]},
                         {"type": "SimpleItem", "command": 16, "frame": 0, "params": [0, 0, 0, 0, 24.001, 121, 107]},
                         {"type": "SimpleItem", "command": 20}]}}
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'synthetic.plan'
            file.write_text(json.dumps(doc), encoding='utf-8')
            m = load_plan(file)
            self.assertEqual([t['id'] for t in m['targets']], ['WP2'])
            self.assertEqual(m['targets'][0]['alt'], 7)
            self.assertEqual(m['takeoff_items'][0]['source_command'], 22)
            self.assertEqual(m['takeoff_items'][0]['source_item_index'], 0)
            self.assertEqual(m['takeoff_items'][0]['kind'], 'takeoff')
            doc['mission']['items'] = doc['mission']['items'][:1]
            file.write_text(json.dumps(doc), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'no waypoint targets'):
                load_plan(file)

    def test_worst_display_provenance_and_timeline_text_keep_raw_values(self):
        raw = 1.6120229858953736
        run = SimpleNamespace(v=Vehicle(), t=2, pct=98, energy_estimated=True, completed=['WP2'],
            provenance={'energy_source': 'SOC delta'},
            data_quality={'missing_wind': True, 'missing_current': True, 'soc_estimated': True,
                          'calibration_eligible': False, 'sample_interval_s': {'min': 1, 'median': 1, 'max': 1}},
            log=[{'t_s': i, 'lat': 24, 'lon': 121, 'alt': alt, 'battery_pct': 100-i,
                  'ground_speed_mps': 0, 'wind_mps': None, 'wind_from': None} for i, alt in [(0, 0), (1, 5), (2, 0)]],
            legs=[{'from': 'H', 'to': 'WP2', 'actual_wh': 0.9, 'pred_wh': raw, 'headwind_mps': None, 'end_t_s': 1}])
        facts = build_facts(run, {'targets': [{'id': 'WP2', 'priority': 1}]}, {'end_pct': 99, 'speed_mps': 8}, [], [])
        f = {x['key']: x for x in facts}
        self.assertIn('預估 1.61 Wh', f['worst_leg']['text'])
        self.assertNotIn(str(raw), f['worst_leg']['text'])
        self.assertEqual(f['worst_leg']['value']['pred_wh'], raw)
        self.assertIn('已用 PX4 SITL 匯出核對欄位，尚未用實機核對', f['telemetry_source']['text'])
        self.assertIn('1.0 秒 起飛', f['timeline']['text'])
        self.assertIn('到達航點 WP2', f['timeline']['text'])
        self.assertEqual(len(f['timeline']['value']), 3)
        self.assertIn('完成目標 1/1', f['completion']['text'])

    def test_timeline_preview_is_bounded_and_no_events_is_explicit(self):
        events = [{'kind': 'waypoint', 't_s': i, 'target_id': 'P'+str(i)} for i in range(8)]
        text = timeline_text(events)
        self.assertIn('另 3 件', text)
        self.assertIn('P4', text)
        self.assertNotIn('P5', text)
        self.assertEqual(len(events), 8)
        self.assertIn('無可推定事件', timeline_text([]))


if __name__ == "__main__":
    unittest.main()
