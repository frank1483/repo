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


if __name__ == "__main__":
    unittest.main()
