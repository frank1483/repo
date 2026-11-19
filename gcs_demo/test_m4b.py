"""M4b 控制器單元測試（假模型、one-hot 假向量、字數當 token；不呼叫 Ollama）。"""
import json
import unittest

from .agent_m4b import FLIGHT_NOTICE, M4bController
from .id_graph import Graph, build

G = build()
IDS = [n["id"] for n in G["nodes"]]


def onehot(i):
    v = [0.0] * len(IDS)
    v[IDS.index(i)] = 1.0
    return v


GRAPH = Graph(G, {i: onehot(i) for i in IDS})
COUNTER = len


def qv_for(*targets):
    v = [0.0] * len(IDS)
    for k, t in enumerate(targets):
        v[IDS.index(t)] = 1.0 - 0.01 * k
    return v


def tools(targets):
    log = []
    return log, {
        "embed_query": lambda text: qv_for(*targets),
        "gen_coverage": lambda ref: log.append(("gen", ref)) or {"status": "OK", "route_ref": "R1"},
        "verify_preview": lambda ref: log.append(("verify", ref)) or {"result": "pass", "preview_ref": "PV1",
                                                                       "est_end_pct": 61.5},
        "propose_home_route": lambda ref: log.append(("home", ref)) or {"shown_hash": "h1"},
        "manual_search": lambda text, qv: {"results": [], "degraded": False},
    }


def scripted(replies):
    seq = list(replies)
    calls = []

    def model(call):
        calls.append(call)
        return seq.pop(0) if seq else '{"action":"FINISH","ids":[],"params":{}}'
    model.calls = calls
    return model


class M4bTests(unittest.TestCase):
    def test_gate_thin(self):
        c = M4bController({}, None, GRAPH, COUNTER)
        self.assertEqual(c.request("   ")["status"], "INVALID_INPUT")
        self.assertEqual(c.request("字" * 201)["status"], "TOO_LONG")

    def test_flight_only_no_proposal(self):
        m = scripted(['{"directions":["flight_request"]}', '{"action":"DECLINE_FLIGHT","ids":[],"params":{}}',
                      '{"action":"FINISH","ids":[],"params":{}}', '{"reply":"飛控請用指令區"}'])
        _, T = tools([])
        r = M4bController(T, m, GRAPH, COUNTER).request("起飛")
        self.assertEqual(r["proposals"], [])
        self.assertIn("flight_notice", r["artifacts"])
        self.assertEqual(r["status"], "DONE")

    def test_mixed_sentence_model_omits_flight(self):
        # 模型漏判飛控方向：只規劃，程式仍補固定說明；沒有任何飛行動作可選
        m = scripted(['{"directions":["plan"]}',
                      '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}',
                      '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"FINISH","ids":[],"params":{}}', 'bad'])
        log, T = tools(["A001"])
        r = M4bController(T, m, GRAPH, COUNTER, summary_llm=True).request("規劃A區巡檢然後起飛")
        self.assertIn("flight_notice", r["artifacts"])
        self.assertEqual(r["artifacts"]["flight_notice"]["by"], "program")
        self.assertIn(FLIGHT_NOTICE, r["reply_zh"])
        self.assertEqual(r["dir_status"]["plan"], "DONE")
        self.assertEqual(r["reply_source"], "template")

    def test_plan_then_ui_order_and_propose(self):
        m = scripted(['{"directions":["ui","plan"]}'])   # 之後全部回 FINISH → 規則腳本不會用到；改用無模型
        log, T = tools(["A001", "U100"])
        r = M4bController(T, None, GRAPH, COUNTER).request("規劃A區巡檢放到首頁")
        self.assertEqual(r["directions"][:2], ["plan", "ui"])
        self.assertEqual([p["action"] for p in r["proposals"]], ["PROPOSE_HOME_ROUTE"])
        self.assertEqual(r["proposals"][0]["state"], "PROPOSED")
        self.assertEqual(r["status"], "DONE")
        r2 = M4bController(T, m, GRAPH, COUNTER, summary_llm=False).request("規劃A區巡檢放到首頁")
        self.assertEqual(r2["directions"][:2], ["plan", "ui"])

    def test_layout_text_size_enum_only(self):
        m = scripted(['{"directions":["layout"]}',
                      '{"action":"UI_LAYOUT_PROPOSE","ids":["P001"],"params":{"value":"120%"}}',
                      '{"action":"UI_LAYOUT_PROPOSE","ids":["P001"],"params":{"value":"大"}}',
                      '{"action":"FINISH","ids":[],"params":{}}'])
        _, T = tools(["P001"])
        r = M4bController(T, m, GRAPH, COUNTER, summary_llm=False).request("文字放大")
        self.assertEqual(len(r["proposals"]), 1)
        self.assertEqual(r["proposals"][0]["params"], {"value": "大"})
        self.assertTrue(any("允許值" in json.dumps(t["replies"], ensure_ascii=False) or len(t["replies"]) == 2
                            for t in r["traces"] if t["purpose"] == "step:layout"))

    def test_id_outside_candidates_rejected(self):
        m = scripted(['{"directions":["color"]}', '{"action":"UI_THEME_PROPOSE","ids":["T999"],"params":{}}',
                      '{"action":"UI_THEME_PROPOSE","ids":["A001"],"params":{}}'])
        _, T = tools(["T001"])
        r = M4bController(T, m, GRAPH, COUNTER, summary_llm=False).request("改成深色")
        st = [s for s in r["steps"] if s["direction"] == "color"]
        self.assertEqual(st[0]["source"], "rule")             # 兩次都不合格 → 規則腳本
        self.assertEqual(r["proposals"][0]["ids"], ["T001"])

    def test_direction_cap_parks(self):
        m = scripted(['{"directions":["layout","color","model","manual"]}'])
        _, T = tools([])
        r = M4bController(T, m, GRAPH, COUNTER).request("文字放大改深色切規則模式查手冊")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["proposals"], [])

    def test_summary_number_must_come_from_facts(self):
        m = scripted(['{"directions":["plan"]}', '{"action":"QUERY_AREA","ids":["A001"],"params":{}}',
                      '{"action":"GEN_COVERAGE","ids":[],"params":{}}', '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}',
                      '{"action":"FINISH","ids":[],"params":{}}',
                      '{"reply":"預估電量 70%"}', '{"reply":"預估落地電量 61.5%"}'])
        _, T = tools(["A001"])
        r = M4bController(T, m, GRAPH, COUNTER).request("規劃A區巡檢")
        self.assertEqual(r["reply_source"], "model")
        self.assertIn("61.5", r["reply_zh"])

    def test_query_vector_once_after_stage1(self):
        n = []
        _, T = tools(["A001"])
        T["embed_query"] = lambda text: n.append(text) or qv_for("A001")
        M4bController(T, None, GRAPH, COUNTER).request("規劃A區巡檢")
        self.assertEqual(len(n), 1)

    def test_layout_without_value_not_proposed(self):
        m = scripted(['{"directions":["layout"]}', '{"action":"UI_LAYOUT_PROPOSE","ids":["C014","P002"],"params":{}}',
                      '{"action":"FINISH","ids":[],"params":{}}'])
        _, T = tools(["C014", "P002"])
        r = M4bController(T, m, GRAPH, COUNTER, summary_llm=False).request("風速計調整一下")
        self.assertEqual(r["proposals"], [])
        self.assertEqual(r["status"], "PARKED")

    def test_rule_uses_named_ids_and_text_value(self):
        _, T = tools([])                                   # 向量全零：規則只能靠名稱比對
        r = M4bController(T, None, GRAPH, COUNTER).request("把風速計放大")
        self.assertEqual([(p["ids"], p["params"]) for p in r["proposals"]], [(["C014", "P002"], {"value": "放大"})])

    def test_locked_hide_blocked(self):
        _, T = tools([])
        r = M4bController(T, None, GRAPH, COUNTER).request("隱藏指令區")
        self.assertEqual(r["proposals"], [])

    def test_batches_run_pending_directions(self):
        big = lambda text: 1100 if "｜" in text and "說明" not in text else 1   # 三份必要資料共 3,300 → 兩批
        _, T = tools(["T001", "M003"])
        r = M4bController(T, None, GRAPH, big).request("改成深色主題，改用規則模式，風速計放大")
        self.assertEqual([b["directions"] for b in r["packing"]["batches"]], [["layout", "color"], ["model"]])
        self.assertEqual(sorted(p["action"] for p in r["proposals"]),
                         ["MODEL_SWITCH_PROPOSE", "UI_LAYOUT_PROPOSE", "UI_THEME_PROPOSE"])
        self.assertEqual(r["status"], "DONE")

    def test_over_dir_limit_needs_user(self):
        _, T = tools(["T001"])
        r = M4bController(T, None, GRAPH, lambda text: 1600 if "T00" in text else 0).request("改成深色主題")
        self.assertEqual(r["status"], "PARKED")
        self.assertEqual(r["packing"]["over_dir_limit"], ["color"])


if __name__ == "__main__":
    unittest.main()
