"""install_ab_into_ui.sh 的合成副本測試（不需要正式 UI；只檢查插入位置、雜湊、拒絕重裝與失敗不留痕）。"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SH = HERE / "install_ab_into_ui.sh"
SHELL = """Item {
    id: root
    // MVP 插槽：主畫面浮動層
    Item { id: mvpFloatingLayer }

    // UI agent：每個畫面都能叫出（右側 AI 按鈕）；只換頁與調整版面，所有變更可復原
    GcpAgentOverlay {
        anchors.fill: parent
    }
}
"""
PLANNER = """Item {
    id: root
                    Binding {
                        target: mvpMissionSlot.item
                        when: mvpMissionSlot.item !== null && ("activeVehicle" in mvpMissionSlot.item)
                    }

                    GcpMapTypeSwitch {
                    }
}
"""
CMAKE = """qt_add_qml_module(x
    QML_FILES
        MvpSlots/GcpMvpInstalled.js
        # MVP plugin files (install_mvp_into_ui.sh inserts AiMission/AiAlerts entries below)
        AiMission/GcpMissionAiPanel.qml
        GcpMainShell.qml
)
"""


def fixture(root):
    g = Path(root) / "GCP"
    (g / "MvpSlots").mkdir(parents=True)
    (g / "Agent").mkdir()
    (g / "MvpSlots/.install_mvp_receipt").write_text("mvp-install-v1\n")
    (g / "Agent/GcpAgentState.qml").write_text("QtObject {}\n")
    (g / "GcpMainShell.qml").write_text(SHELL.replace("\n", "\r\n"))     # CRLF 也要能裝
    (g / "GcpMissionPlannerPage.qml").write_text(PLANNER)
    (g / "CMakeLists.txt").write_text(CMAKE)
    return g


def run(*args):
    return subprocess.run(["bash", str(SH), *args], capture_output=True, text=True)


class InstallAbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.g = fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_install_b(self):
        r = run("B", "8768", self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        shell = (self.g / "GcpMainShell.qml").read_text()
        self.assertLess(shell.index("abAgentSlot"), shell.index("GcpAgentOverlay"))
        planner = (self.g / "GcpMissionPlannerPage.qml").read_text()
        self.assertLess(planner.index('("activeVehicle" in'), planner.index("abRouteSinkSlot"))
        self.assertLess(planner.index("abRouteSinkSlot"), planner.index("GcpMapTypeSwitch"))
        build = (self.g / "AiAgent/GcpAiAgentBuild.js").read_text()
        self.assertIn('var PLAN = "B"', build)
        self.assertIn("http://127.0.0.1:8768", build)
        cm = (self.g / "CMakeLists.txt").read_text()
        for f in ("GcpAiAgentPanel.qml", "GcpAiAgentRouteSink.qml", "GcpAiAgentCore.js", "GcpAiAgentBus.js", "GcpAiAgentBuild.js"):
            self.assertEqual(cm.count("        AiAgent/" + f + "\n"), 1, f)
            self.assertTrue((self.g / "AiAgent" / f).is_file())
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".ab-install.lock")))
        again = run("B", "8768", self.tmp)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("prior AiAgent", again.stderr)

    def test_refuses_without_mvp(self):
        (self.g / "MvpSlots/.install_mvp_receipt").unlink()
        r = run("A", "8767", self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.g / "AiAgent").exists())

    def test_missing_anchor_leaves_copy(self):
        (self.g / "GcpMissionPlannerPage.qml").write_text("Item {}\n")
        before = (self.g / "GcpMainShell.qml").read_bytes()
        r = run("A", "8767", self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.g / "GcpMainShell.qml").read_bytes(), before)
        self.assertFalse((self.g / "AiAgent").exists())

    def test_bad_args(self):
        self.assertEqual(run("C", "8767", self.tmp).returncode, 2)
        self.assertEqual(run("A", "x", self.tmp).returncode, 2)


if __name__ == "__main__":
    unittest.main()
