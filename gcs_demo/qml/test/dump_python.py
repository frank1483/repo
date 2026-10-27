"""輸出 Python 版的規劃／重規劃結果，給 test_core.js 比對 JS 移植。"""
import json
import sys

from gcs_demo import llm, scenario as S
from gcs_demo.energy import Vehicle, Wind
from gcs_demo.planner import plan_mission, replan

none = llm.LLMBackend()
v, w = Vehicle(), Wind(**S.WIND)
p = plan_mission(S.mission(), v, w, none)
state = {"observed_ratio": 1.162, "t_s": 300.0, "lat": 24.7925714, "lon": 120.9942857, "alt": 50.0,
         "battery_pct": 66.8, "completed": ["F", "A", "B"], "remaining": ["C", "D", "E"], "done": False}
ev = {"type": "wind", "speed_mps": 9.0, "from_deg": 240.0, "text_zh": "風"}
r = replan(S.mission(), v, w, state, ev, none)
v2 = Vehicle(calib=1.2)
p2 = plan_mission(S.mission(), v2, Wind(7, 200), none)
json.dump({"mission": S.mission(), "wind": S.WIND, "state": state, "event": ev,
           "plan": p, "replan": r, "plan2": p2}, sys.stdout, ensure_ascii=False, default=str)
