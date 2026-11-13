"""面板依賴的 server 回傳欄位（示範情境：reset→plan→start→alerts）。不連模型（GCS_LLM_BACKEND 預設規則）。"""
import json, subprocess, unittest, os

from gcs_demo import server

HERE = os.path.dirname(__file__)


class PanelContract(unittest.TestCase):
    def test_demo_flow_fields(self):
        server.handle("/api/reset", {})
        plan = server.handle("/api/plan", {})
        body = json.loads(subprocess.check_output(["node", "-e",
            "const fs=require('fs'),vm=require('vm');const m={exports:{}};"
            "vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8').replace(/^\\.pragma library/,''),{module:m,String,Number});"
            "process.stdout.write(JSON.stringify(m.exports.startBody(JSON.parse(fs.readFileSync(0,'utf8')))))",
            os.path.join(HERE, "..", "GcpAiAlertsCore.js")], input=json.dumps(plan).encode()))
        self.assertIsNotNone(body)
        r = server.handle("/api/start", body)
        self.assertNotEqual(r.get("ok"), False, r)
        j = server.handle("/api/alerts", {})
        self.assertTrue(j["alerts"], "示範情境應產生至少一則告警")
        for a in j["alerts"]:
            for k in ("severity", "title", "text_zh", "source", "alert_id", "alert_version", "active", "key", "t_s"):
                self.assertIn(k, a)
        info = server.handle("/api/scenario", {})
        self.assertIn("model", info["llm"])
        server.handle("/api/reset", {})


if __name__ == "__main__":
    unittest.main()
