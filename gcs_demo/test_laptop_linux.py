"""筆電（Linux）版執行器輔助函式：埠歸屬（/proc）、ollama RAM 取樣、環境變數指定模型根與執行檔。只在 Linux 跑。"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from gcs_demo import m4_runner as R


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
class LaptopLinuxTest(unittest.TestCase):
    def test_listener_pids_finds_own_child(self):
        p = subprocess.Popen([sys.executable, "-c",
                              "import socket,time;s=socket.socket();s.bind(('127.0.0.1',0));s.listen();"
                              "print(s.getsockname()[1],flush=True);time.sleep(30)"], stdout=subprocess.PIPE, text=True)
        try:
            port = int(p.stdout.readline())
            self.assertEqual(R.listener_pids(port), {p.pid})
        finally:
            p.kill(); p.wait()
        self.assertEqual(R.listener_pids(port), set())

    def test_free_port_has_no_listener(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        self.assertEqual(R.listener_pids(port), set())

    def test_ram_sampler_counts_processes_named_ollama(self):
        base = R.RamSampler.sample_all()
        d = tempfile.mkdtemp()
        fake = os.path.join(d, "ollama")
        shutil.copy(shutil.which("sleep"), fake)
        p = subprocess.Popen([fake, "30"])
        try:
            for _ in range(50):
                got = R.RamSampler.sample_all()
                if got > base:
                    break
                time.sleep(0.05)
            self.assertGreater(got, base)
        finally:
            p.kill(); p.wait(); shutil.rmtree(d)

    def test_env_overrides(self):
        env = dict(os.environ, GCS_OLLAMA_MODELS="/x/models", GCS_OLLAMA_BIN="/x/bin/ollama")
        out = subprocess.run([sys.executable, "-c",
                              "from gcs_demo import m4_runner as R, gemma4_tokenizer as T;"
                              "print(R.MODELS_ROOT, R.OLLAMA_BIN, T.MODELS)"], env=env, capture_output=True, text=True,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(out.stdout.split(), ["/x/models", "/x/bin/ollama", "/x/models"], out.stderr)


class FakeProc:
    """替身子程序：記錄 terminate／kill／wait；hang=True 時第一次 wait 逾時。"""
    def __init__(self, hang=False, exited=False):
        self.pid = 424242
        self.returncode = 0 if exited else None
        self.hang = hang
        self.calls = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self.hang and self.calls.count("wait") == 1:
            raise subprocess.TimeoutExpired("ollama", timeout)
        self.returncode = -15
        return self.returncode


class StartOllamaCleanupTest(unittest.TestCase):
    """CODEX-APP-0450 第 1 點：Popen 之後、交回之前的失敗都要回收自己的子程序，並保留原本的錯誤。"""

    def run_start(self, proc, listener_exc):
        saved = (R.subprocess.Popen, R.listener_pids, R.port_free)
        R.subprocess.Popen = lambda *a, **k: proc
        R.port_free = lambda port: True

        def boom(port):
            raise listener_exc
        R.listener_pids = boom
        try:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(BaseException) as cm:
                    R.start_ollama(11555, os.path.join(d, "serve.log"))
            return cm.exception
        finally:
            R.subprocess.Popen, R.listener_pids, R.port_free = saved

    def test_listener_error_reaps_child_and_keeps_error(self):
        err = SystemExit("看不到擁有者")
        proc = FakeProc()
        got = self.run_start(proc, err)
        self.assertIs(got, err)
        self.assertEqual(proc.calls, ["terminate", "wait"])
        self.assertIsNotNone(proc.returncode)

    def test_timeout_kills_only_own_child(self):
        err = SystemExit("看不到擁有者")
        proc = FakeProc(hang=True)
        got = self.run_start(proc, err)
        self.assertIs(got, err)
        self.assertEqual(proc.calls, ["terminate", "wait", "kill", "wait"])

    def test_keyboard_interrupt_is_kept(self):
        err = KeyboardInterrupt()
        proc = FakeProc()
        got = self.run_start(proc, err)
        self.assertIs(got, err)
        self.assertEqual(proc.calls, ["terminate", "wait"])

    def test_reap_failure_does_not_hide_original_error(self):
        err = SystemExit("看不到擁有者")
        proc = FakeProc()
        proc.terminate = lambda: (_ for _ in ()).throw(OSError("terminate 失敗"))
        got = self.run_start(proc, err)
        self.assertIs(got, err)

    def test_already_exited_child_not_signalled(self):
        proc = FakeProc(exited=True)          # 子程序自己先結束：走「已結束」錯誤，不送訊號
        got = self.run_start(proc, SystemExit("不會走到 listener"))
        self.assertIn("已結束", str(got))
        self.assertEqual(proc.calls, [])

    def test_real_child_reaped_when_listener_check_fails(self):
        """真的子程序（sleep）：listener 拋錯後，程序確實已結束。"""
        saved = (R.OLLAMA_BIN, R.listener_pids, R.port_free)
        started = []
        real_popen = subprocess.Popen

        def popen(cmd, **k):
            p = real_popen([shutil.which("sleep"), "30"], **k)
            started.append(p)
            return p
        R.port_free = lambda port: True
        R.listener_pids = lambda port: (_ for _ in ()).throw(SystemExit("看不到擁有者"))
        R.subprocess.Popen = popen
        try:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(SystemExit):
                    R.start_ollama(11555, os.path.join(d, "serve.log"))
        finally:
            R.subprocess.Popen = real_popen
            R.OLLAMA_BIN, R.listener_pids, R.port_free = saved
        self.assertEqual(len(started), 1)
        self.assertIsNotNone(started[0].poll())


if __name__ == "__main__":
    unittest.main()
