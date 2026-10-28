"""New synthetic adapter tests for Claude to execute; no model/equipment calls."""
import copy
import csv
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gcs_demo.flightlog import load_csv
from gcs_demo.energy import Vehicle
from gcs_demo.report import make_report


class FlightlogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.csv'
        self.mission = {'cruise_alt_m': 50, 'targets': [
            {'id': 'A', 'lat': 24, 'lon': 121.0001, 'priority': 1}]}
        self.plan = {'id': 'C1', 'speed_mps': 8, 'end_pct': 90, 'calib': 1.2,
                     'vehicle': Vehicle(battery_wh=100, usable_frac=0.8, calib=1.2).to_dict(),
                     'path': [{'id': 'H', 'lat': 24, 'lon': 121, 'alt': 50, 'kind': 'home'},
                              {'id': 'A', 'lat': 24, 'lon': 121.0001, 'alt': 50, 'kind': 'target'},
                              {'id': 'H', 'lat': 24, 'lon': 121, 'alt': 50, 'kind': 'home'}]}
        self.rows = [dict(t_s=t, lat=24, lon=lon, alt=50, battery_pct=pct,
                          voltage=20, current_a=current, wind_mps=2, wind_from=270)
                     for t, lon, pct, current in [(100, 121, 100, 1),
                                                 (110, 121.0001, 99.5, 3),
                                                 (120, 121, 99, 5)]]

    def write(self, rows=None):
        rows = self.rows if rows is None else rows
        with self.path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def load(self):
        self.write()
        return load_csv(self.path, self.mission, self.plan)

    def report(self, run):
        backend = Mock()
        backend.available.return_value = False
        result = make_report(run, self.mission, run.plan, backend=backend)
        backend.complete_json.assert_not_called()
        ids = [f['id'] for f in result['facts']]
        self.assertEqual(len(ids), len(set(ids)))
        for suggestion in result['suggestions']:
            self.assertTrue(suggestion['evidence_ids'])
            self.assertTrue(set(suggestion['evidence_ids']) <= set(ids))
        return result

    def test_trapezoidal_energy_and_complete_report(self):
        run = self.load()
        self.assertAlmostEqual(sum(l['actual_wh'] for l in run.legs), 1/3)
        self.assertAlmostEqual(run.log[-1]['used_wh'], 1/3)
        self.assertEqual(run.t, 20)
        self.assertEqual(run.completed, ['A'])
        self.assertEqual(run.pct, 99)
        self.assertTrue(run.provenance['route_completed'])
        self.assertFalse(run.energy_estimated)
        self.assertTrue(all(math.isfinite(l['pred_wh']) for l in run.legs))
        result = self.report(run)
        self.assertEqual(result['data_provenance']['energy_source'], 'voltage_current_trapezoid')

    def test_planner_envelope(self):
        self.write()
        envelope = {'vehicle': self.plan['vehicle'], 'candidates': [self.plan],
                    'pick': {'choice_id': 'C1'}}
        self.assertEqual(load_csv(self.path, self.mission, envelope).completed, ['A'])

    def test_soc_fallback_is_visible_and_does_not_change_calibration(self):
        for row in self.rows:
            del row['current_a']
        run = self.load()
        self.assertTrue(run.energy_estimated)
        self.assertAlmostEqual(sum(l['actual_wh'] for l in run.legs), 0.8)
        self.assertIsNone(run.log[0]['power_w'])
        result = self.report(run)
        source = next(f for f in result['facts'] if f['key'] == 'telemetry_source')
        self.assertTrue(source['value']['energy_estimated'])
        self.assertIn('估算', result['summary_zh'])
        self.assertEqual(result['next_calib'], 1.2)
        self.assertFalse(result['calibration_eligible'])

    def test_nominal_soc_capacity_is_configurable(self):
        for row in self.rows:
            del row['current_a']
        self.mission['flightlog'] = {'soc_capacity_basis': 'nominal'}
        self.assertAlmostEqual(sum(l['actual_wh'] for l in self.load().legs), 1)

    def test_custom_alias_and_millisecond_timestamp(self):
        for row in self.rows:
            row['TimeMS'] = row.pop('t_s')*1000
        self.mission['flightlog'] = {'columns': {'t_s': 'TimeMS'}, 'time_scale': 0.001}
        self.assertEqual(self.load().t, 20)

    def test_missing_column_is_error(self):
        for row in self.rows:
            del row['voltage']
        with self.assertRaisesRegex(ValueError, 'voltage.*required column'):
            self.load()

    def test_blank_current_is_error_not_fallback(self):
        self.rows[1]['current_a'] = ''
        with self.assertRaisesRegex(ValueError, 'current_a'):
            self.load()

    def test_timestamp_and_gap_errors(self):
        for timestamp in (100, 99, 141):
            with self.subTest(timestamp=timestamp):
                rows = copy.deepcopy(self.rows)
                rows[1]['t_s'] = timestamp
                self.write(rows)
                with self.assertRaisesRegex(ValueError, 'timestamps'):
                    load_csv(self.path, self.mission, self.plan)

    def test_nonfinite_and_out_of_range(self):
        for key, value in [('lat', 'nan'), ('lon', 200), ('current_a', -1),
                           ('battery_pct', 101), ('wind_mps', -1), ('voltage', 0)]:
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows)
                rows[1][key] = value
                self.write(rows)
                with self.assertRaises(ValueError):
                    load_csv(self.path, self.mission, self.plan)

    def test_soc_increase_rejected_only_in_fallback(self):
        for row in self.rows:
            del row['current_a']
        self.rows[2]['battery_pct'] = 99.9
        with self.assertRaisesRegex(ValueError, 'SOC increase'):
            self.load()

    def test_arrival_requires_altitude_and_in_radius_sample(self):
        self.rows[1]['alt'] = 100
        run = self.load()
        self.assertEqual(run.completed, [])
        self.assertFalse(run.provenance['route_completed'])
        self.assertTrue(run.legs[-1]['partial'])
        self.assertAlmostEqual(sum(l['actual_wh'] for l in run.legs), 1/3)

    def test_ambiguous_aliases_rejected(self):
        for row in self.rows:
            row['latitude'] = row['lat']
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.load()

    def test_vehicle_and_hold_require_explicit_input(self):
        self.write()
        bad = dict(self.plan)
        del bad['vehicle']
        with self.assertRaisesRegex(ValueError, 'vehicle required'):
            load_csv(self.path, self.mission, bad)
        with self.assertRaisesRegex(ValueError, 'HOLD'):
            load_csv(self.path, self.mission, {'vehicle': self.plan['vehicle'],
                     'candidates': [self.plan], 'pick': {'choice_id': ''}})

    def test_one_row_and_duplicate_headers_rejected(self):
        self.write(self.rows[:1])
        with self.assertRaisesRegex(ValueError, 'at least two'):
            load_csv(self.path, self.mission, self.plan)
        self.path.write_text('t_s,t_s\n1,2\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate CSV headers'):
            load_csv(self.path, self.mission, self.plan)


from .test_t3_report import T3ReportTests, T3DeidentifiedSmoke

if __name__ == '__main__':
    unittest.main()
