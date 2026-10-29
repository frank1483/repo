"""New T3 Part A tests. Claude owns first functional execution and smoke test."""
import copy
import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from .energy import Vehicle
from .flightlog import load_csv, load_plan
from .report import make_report
from .report_t3 import unsupported_numbers, alert_leads


class T3ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'qgc.csv'
        self.v = Vehicle(calib=1.2)
        self.mission = {'home': {'id': 'H', 'lat': 24, 'lon': 121}, 'cruise_alt_m': 5,
                        'targets': [{'id': 'A', 'lat': 24, 'lon': 121, 'alt': 5, 'priority': 1}]}
        self.plan = {'id': 'C1', 'speed_mps': 8, 'end_pct': 90, 'vehicle': self.v.to_dict(),
                     'path': [{'id': 'H', 'lat': 24, 'lon': 121, 'alt': 0, 'kind': 'home'},
                              {'id': 'A', 'lat': 24, 'lon': 121, 'alt': 5, 'kind': 'target'},
                              {'id': 'H', 'lat': 24, 'lon': 121, 'alt': 0, 'kind': 'home'}]}
        self.rows = [{'Timestamp': f'2000-01-01 00:00:0{i}.000', 'gps.lat': 24, 'gps.lon': 121,
                      'altitudeRelative': alt, 'battery0.percentRemaining': soc,
                      'battery0.voltage': 20, 'battery0.current': '-1.00',
                      'wind.speed': '--.--', 'wind.direction': '--.--', 'groundSpeed': speed}
                     for i, alt, soc, speed in [(0, 0, 100, 0), (1, 5, 99, 1), (2, 0, 98, 0),
                                                (3, 0, 98, 0), (4, 0, 100, 0)]]

    def load(self, rows=None):
        rows = rows if rows is not None else self.rows
        with self.path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return load_csv(self.path, self.mission, self.plan)

    def backend(self, data=None):
        b = Mock(model='offline-test-stub')
        b.available.return_value = data is not None
        b.complete_json.return_value = {'ok': True, 'data': data, 'model': 'offline-test-stub'}
        return b

    def test_qgc_timestamp_sentinels_and_landing_reset_trim(self):
        r = self.load()
        self.assertEqual(r.t, 2)
        self.assertEqual(r.pct, 98)
        self.assertEqual(r.data_quality['trimmed_samples'], 2)
        self.assertEqual(r.data_quality['sample_interval_s'], {'min': 1, 'median': 1, 'max': 1})
        self.assertTrue(r.data_quality['missing_wind'])
        self.assertTrue(r.data_quality['missing_current'])
        self.assertIn('disarm_inferred', r.data_quality['trim_reason'])
        self.assertFalse(r.data_quality['disarm_observed'])
        self.assertTrue(all(x['wind_mps'] is None for x in r.log))

    def test_missing_current_sample_uses_whole_run_soc_not_mixed_energy(self):
        self.rows[0]['battery0.current'] = '1'
        r = self.load()
        self.assertTrue(r.energy_estimated)
        self.assertAlmostEqual(sum(l['actual_wh'] for l in r.legs), self.v.battery_wh*self.v.usable_frac*0.02)

    def test_unknown_wind_blocks_wind_facts_and_calibration(self):
        r = self.load()
        rep = make_report(r, self.mission, r.plan, backend=self.backend())
        keys = {f['key'] for f in rep['facts']}
        self.assertFalse({'headwind', 'wind_change', 'best_speed'} & keys)
        self.assertFalse(rep['calibration_eligible'])
        self.assertEqual(rep['next_calib'], 1.2)
        self.assertIn('缺少', rep['summary_zh'])

    def test_current_present_but_wind_missing_still_blocks_calibration(self):
        for row in self.rows:
            row['battery0.current'] = 1
        r = self.load()
        rep = make_report(r, self.mission, r.plan, backend=self.backend())
        self.assertFalse(r.energy_estimated)
        self.assertFalse(rep['calibration_eligible'])
        self.assertEqual(rep['next_calib'], 1.2)

    def test_reset_before_flight_and_midair_soc_increase_are_not_trimmed(self):
        self.rows[1]['battery0.percentRemaining'] = 100
        self.rows[0]['battery0.percentRemaining'] = 90
        with self.assertRaisesRegex(ValueError, 'SOC increase'):
            self.load()

    def test_moving_ground_reset_is_not_a_landing(self):
        for row in self.rows[2:]:
            row['groundSpeed'] = 2
        with self.assertRaisesRegex(ValueError, 'SOC increase'):
            self.load()

    def test_armed_reset_is_not_silently_trimmed(self):
        for row in self.rows:
            row['armed'] = '1'
        with self.assertRaisesRegex(ValueError, 'SOC increase'):
            self.load()

    def test_timestamp_across_day_boundary(self):
        rows = self.rows[:2]
        rows[0]['Timestamp'] = '2000-01-01 23:59:59.000'
        rows[1]['Timestamp'] = '2000-01-02 00:00:00.125'
        self.assertAlmostEqual(self.load(rows).t, 1.125)

    def test_plan_commands_and_global_altitude(self):
        doc = {'fileType': 'Plan', 'mission': {'plannedHomePosition': [24, 121, 100], 'hoverSpeed': 8,
               'items': [{'type': 'SimpleItem', 'command': 22, 'frame': 3, 'params': [0, 0, 0, 0, 24, 121, 5]},
                         {'type': 'SimpleItem', 'command': 16, 'frame': 0, 'params': [0, 0, 0, 0, 24, 121.001, 107]},
                         {'type': 'SimpleItem', 'command': 20}]}}
        p = Path(self.tmp.name) / 'm.plan'
        p.write_text(json.dumps(doc), encoding='utf-8')
        m = load_plan(p)
        self.assertEqual([t['source_command'] for t in m['targets']], [16])
        self.assertEqual([t['alt'] for t in m['targets']], [7])
        self.assertEqual([t['alt'] for t in m['takeoff_items']], [5])
        self.assertTrue(m['rtl'])
        doc['mission']['items'][0]['command'] = 177
        p.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unsupported command'):
            load_plan(p)

    def test_numeric_rounding_percent_and_decimal(self):
        facts = [{'text': '落地 80.0%', 'value': {'margin': 12.345}}]
        self.assertEqual(unsupported_numbers(['落地 80%，餘裕 12.35%'], facts), [])
        self.assertEqual(unsupported_numbers(['落地 80.1%'], facts), ['80.1'])
        self.assertEqual(unsupported_numbers(['餘裕 999.99%'], facts), ['999.99'])

    def test_invented_summary_number_falls_back_without_retry(self):
        r = self.load()
        b = self.backend({'summary_zh': '落地 8765.4321%', 'suggestions': [{'text_zh': '維持', 'evidence_ids': ['F1']}]})
        rep = make_report(r, self.mission, r.plan, backend=b)
        self.assertEqual(rep['source'], 'rule')
        self.assertIn('unsupported_numbers', rep['llm_fallback_reason'])
        b.complete_json.assert_called_once()

    def test_invented_suggestion_number_falls_back_whole_report(self):
        r = self.load()
        b = self.backend({'summary_zh': '任務結束', 'suggestions': [{'text_zh': '提高 8765.4321%', 'evidence_ids': ['F1']}]})
        rep = make_report(r, self.mission, r.plan, backend=b)
        self.assertEqual(rep['source'], 'rule')
        self.assertNotIn('提高 8765.4321%', [s['text_zh'] for s in rep['suggestions']])

    def test_wind_advice_rejected_with_missing_measurements(self):
        r = self.load()
        b = self.backend({'summary_zh': '任務結束', 'suggestions': [{'text_zh': '逆風時改速', 'evidence_ids': ['F1']}]})
        rep = make_report(r, self.mission, r.plan, backend=b)
        self.assertEqual(rep['llm_fallback_reason'], 'wind_advice_without_measurements')

    def test_timeline_margin_no_alert_field_and_versions(self):
        r = self.load()
        rep = make_report(r, self.mission, r.plan, backend=self.backend(), versions={'git_short_hash': 'e65a8bb'})
        self.assertEqual(rep['energy_margin']['margin_pct'], 78)
        self.assertTrue(rep['energy_margin']['landing_inferred'])
        self.assertTrue({'takeoff', 'landing', 'waypoint'} <= {e['kind'] for e in rep['timeline']})
        self.assertNotIn('alert_lead_time', rep)
        self.assertEqual(rep['versions'], {'git_short_hash': 'e65a8bb', 'prompt_hash': None, 'model': None})

    def test_lead_time_uses_pre_alert_samples_and_ignores_generic_lead(self):
        r = self.load()
        leads = alert_leads(r, [{'t_s': 1, 'lead_s': 9999}])
        self.assertEqual(leads[0]['lead_s'], 79)
        r.log[-1]['battery_pct'] = 0  # future data must not change alert-time estimate
        self.assertEqual(alert_leads(r, [{'t_s': 1}])[0]['lead_s'], 79)
        self.assertEqual(alert_leads(r, [{'t_s': 100}]), [])

    def test_model_versions_and_only_one_stub_call(self):
        r = self.load()
        b = self.backend({'summary_zh': '任務結束', 'suggestions': [{'text_zh': '補充量測', 'evidence_ids': ['F1']}]})
        rep = make_report(r, self.mission, r.plan, backend=b, versions={'git_short_hash': 'caller-hash'})
        self.assertEqual(rep['versions']['model'], 'offline-test-stub')
        self.assertEqual(len(rep['versions']['prompt_hash']), 16)
        self.assertEqual(rep['versions']['git_short_hash'], 'caller-hash')
        b.complete_json.assert_called_once()


class T3DeidentifiedSmoke(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('GCS_T3_SMOKE_DIR'), 'Claude sets deidentified input directory for first smoke execution')
    def test_deidentified_csv_plan_report_quality_only(self):
        base = Path(os.environ['GCS_T3_SMOKE_DIR'])
        files = {'sitl_qgc_flight_v1.csv': '3e74e4b7dcc040773797f62fd2b27294a88f327e6a4d7f262ae14dbecd8e8891',
                 'sitl_qgc_mission_v1.plan': '2d66d07ba8f5090dd4161521a3afb0d43e73031c4edbfe19ec483d886f595656'}
        for name, digest in files.items():
            self.assertEqual(hashlib.sha256((base/name).read_bytes()).hexdigest(), digest)
        m = load_plan(base/'sitl_qgc_mission_v1.plan')
        # A route container for offline adapter smoke, not a planner or x500 calibration result.
        h = dict(m['home'], alt=0, kind='home')
        plan = {'id': 'SMOKE', 'speed_mps': m['speed_mps'], 'end_pct': 20,
                'vehicle': Vehicle().to_dict(), 'path': [h]+[dict(t, kind='target') for t in m['targets']]+[h]}
        r = load_csv(base/'sitl_qgc_flight_v1.csv', m, plan)
        b = Mock()
        b.available.return_value = False
        rep = make_report(r, m, r.plan, backend=b)
        self.assertTrue(rep['facts'])
        self.assertTrue(rep['data_quality']['missing_wind'])
        self.assertTrue(rep['data_quality']['missing_current'])
        self.assertTrue(rep['data_quality']['soc_estimated'])
        self.assertGreater(rep['data_quality']['trimmed_samples'], 0)
        self.assertFalse(rep['calibration_eligible'])
        b.complete_json.assert_not_called()
