"""New synthetic engineering controls; first execution belongs to Claude."""
import copy
import json
import sys
import unittest
from dataclasses import replace

from .energy import load_airframe
from .alerts.typed_capacity import typed_battery_capacity_snapshot as snap


def vehicle(name="fw_example"):
    return replace(load_airframe(name), battery_wh=100.0)


def options():
    return {"cell_r_ohm": 0.004, "cell_empty_v": 3.55}


def samples(total=80.0, n=100, span=20.0):
    return [{"t_s": float(i), "battery_id": "battery:one", "used_wh": span*i/(n-1),
             "voltage": (4.2-(4.2-3.55)/total*(span*i/(n-1))-5*0.004)*4,
             "current_a": 5.0, "cell_count": 4, "battery_pct": 90.0} for i in range(n)]


def vector_cases():
    cases = []
    for name, total, n, span in (("risk",80,100,20),("healthy",120,100,20),
                                 ("warmup",80,89,20),("span",80,100,7.9),
                                 ("span_equality",80,100,8)):
        cases.append({"name": name, "airframe": "fw_example", "samples": samples(total,n,span), "options": options()})
    for name in ("gap", "flat", "rising", "noisy", "empty", "hybrid", "low_soc", "energy_offset"):
        rows=samples(); cfg=options()
        if name=="gap":
            for r in rows[50:]: r["t_s"]+=31
        if name=="flat":
            for r in rows: r["voltage"]=16.0
        if name=="rising":
            for i,r in enumerate(rows): r["voltage"]=15+i*0.001
        if name=="noisy":
            for i,r in enumerate(rows): r["voltage"]+=(-1 if i%2 else 1)*0.5
        if name=="empty": cfg["cell_empty_v"]=4.5
        if name=="low_soc":
            for r in rows: r["battery_pct"]=10
        if name=="energy_offset":
            for r in rows: r["used_wh"]+=10
        cases.append({"name":name,"airframe":"vtol_example" if name=="hybrid" else "fw_example","samples":rows,"options":cfg})
    return cases


def vectors():
    return {"contract":"typed_capacity_snapshot_v1", "cases":[{**c,"output":snap(vehicle(c["airframe"]),c["samples"],c["options"])} for c in vector_cases()]}


class TestTypedCapacity(unittest.TestCase):
    def test_capacity_and_compensation(self):
        o=snap(vehicle(),samples(),options())
        self.assertEqual(o["status"],"ok"); self.assertIs(o["risk"],True)
        self.assertAlmostEqual(o["estimated_total_wh"],80); self.assertAlmostEqual(o["estimated_remaining_wh"],60)
        self.assertAlmostEqual(o["soc_overestimate_pct"],30)

    def test_healthy_and_low_soc(self):
        self.assertIs(snap(vehicle(),samples(120),options())["risk"],False)
        r=samples()
        for x in r: x["battery_pct"]=10
        o=snap(vehicle(),r,options()); self.assertIs(o["risk"],False); self.assertEqual(o["conservative_remaining_wh"],10)

    def test_warmup_and_span_boundary(self):
        self.assertEqual(snap(vehicle(),samples(n=89),options())["reason"],"insufficient_samples")
        self.assertEqual(snap(vehicle(),samples(span=7.9),options())["reason"],"insufficient_energy_span")
        self.assertEqual(snap(vehicle(),samples(span=8),options())["status"],"ok")

    def test_unknown_fit_and_gap(self):
        d={c["name"]:c["output"] for c in vectors()["cases"]}
        for name,reason in (("gap","telemetry_gap"),("flat","degenerate_fit"),("rising","capacity_fit_unreliable"),("noisy","capacity_fit_unreliable"),("empty","extrapolated_empty_reached")):
            self.assertEqual(d[name]["reason"],reason); self.assertIsNone(d[name]["risk"]); self.assertIsNone(d[name]["conservative_remaining_wh"])

    def test_risk_thresholds_are_strict(self):
        r=samples(); o=snap(vehicle(),r,options())
        for k,v in (("capacity_ratio_limit",o["capacity_ratio"]),("soc_gap_limit_pct",o["soc_overestimate_pct"])):
            self.assertIs(snap(vehicle(),r,{**options(),k:v})["risk"],False)

    def test_energy_counter_origin_is_preserved(self):
        r=samples()
        for x in r: x["used_wh"]+=10
        o=snap(vehicle(),r,options()); self.assertAlmostEqual(o["estimated_total_wh"],90); self.assertAlmostEqual(o["estimated_remaining_wh"],60)

    def test_mixed_session_and_charging_rejected(self):
        for k,v in (("battery_id","battery:two"),("cell_count",5),("current_a",-1),("used_wh",-1),("t_s",0)):
            r=samples(); r[-1][k]=v
            with self.assertRaises(ValueError): snap(vehicle(),r,options())

    def test_schema_and_finite_values(self):
        for k,v in (("cell_count",True),("battery_pct",True),("used_wh",float("nan")),("voltage",float("inf")),("battery_id","bad id"),("battery_id","battery:one\n")):
            r=samples(); r[0][k]=v
            with self.assertRaises(ValueError): snap(vehicle(),r,options())
        for r in ([],samples(n=602),[{}]):
            with self.assertRaises(ValueError): snap(vehicle(),r,options())
        r=samples(); r[0]["extra"]=1
        with self.assertRaises(ValueError): snap(vehicle(),r,options())

    def test_explicit_options_and_profile(self):
        for cfg in (None,{}, {**options(),"extra":1},{**options(),"min_samples":True},{**options(),"cell_empty_v":None},{**options(),"min_r2":2}):
            with self.assertRaises(ValueError): snap(vehicle(),samples(),cfg)
        with self.assertRaises(ValueError): snap(load_airframe("x500"),samples(),options())
        self.assertEqual(snap(vehicle("vtol_example"),samples(),options())["status"],"ok")

    def test_no_input_mutation_and_detached_output(self):
        rows=samples(); cfg=options(); before=copy.deepcopy([rows,cfg]); out=snap(vehicle(),rows,cfg)
        self.assertEqual([rows,cfg],before); out["assumptions"]["cell_r_ohm"]=1
        self.assertEqual(cfg,options())

    def test_no_capacity_or_action_claim(self):
        for c in vectors()["cases"]:
            o=c["output"]
            for key in ("measured_capacity","sensor_validated","probability_interval","energy_correction_applied","feasible","executable"): self.assertIs(o[key],False)
            self.assertEqual(o["candidates"],[]); self.assertIsNone(o["rule_choice"])

    def test_gap_equality_and_energy_plateau(self):
        r=samples()
        for x in r[50:]: x["t_s"]+=29
        self.assertEqual(snap(vehicle(),r,options())["status"],"ok")
        r=samples(); r[1]["used_wh"]=r[0]["used_wh"]; r[1]["voltage"]=r[0]["voltage"]
        self.assertEqual(snap(vehicle(),r,options())["status"],"ok")


if __name__=="__main__":
    if sys.argv[1:]==["--vectors"]: print(json.dumps(vectors(),allow_nan=False,sort_keys=True))
    else: unittest.main()
