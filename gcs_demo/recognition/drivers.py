"""辨識模型執行方式（driver SPI）。借用 MausBot driver 介面的做法，不安裝 MausBot。

每個 driver 回報自己在這台機器能不能用；registry 只把 driver 可用的模型列為已安裝。
目前只有 stub 真的能跑（合成權重，示範流程用）。onnx / tflite 在套件存在時才可用；
neuron（Genio 520 NPU）要等 MediaTek 工具鏈查證後才實作，現在一律回報不可用。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json


class Driver:
    name = "base"

    def available(self):
        """回傳 (可用與否, 原因)。"""
        return False, "未實作"

    def load(self, manifest, path):
        raise NotImplementedError


class StubSession:
    """合成辨識：畫面裡的「真實物件」只要類別在模型類別內，就以固定的偽隨機信心值回報。"""

    def __init__(self, manifest, weights, alias):
        self.manifest = manifest
        self.seed = int(weights["seed"])
        self.alias = alias
        self.classes = {alias.get(c, c) for c in manifest["classes"]}

    def infer(self, frame):
        out = []
        for i, obj in enumerate(frame.get("objects", [])):
            cls = self.alias.get(obj["class"], obj["class"])
            if cls not in self.classes:
                continue
            h = hashlib.sha256(f"{self.seed}|{frame['frame_id']}|{i}".encode()).digest()
            conf = round(0.35 + 0.6 * h[0] / 255, 3)
            out.append({"class": cls, "conf": conf, "bbox": list(obj["bbox"])})
        return out

    def close(self):
        self.classes = set()


class StubDriver(Driver):
    name = "stub"

    def __init__(self, alias):
        self.alias = alias

    def available(self):
        return True, "內建（合成權重）"

    def load(self, manifest, path):
        with open(path, encoding="utf-8") as f:
            weights = json.load(f)
        if not weights.get("stub_weights") or weights.get("model_id") != manifest["id"]:
            raise ValueError("stub 權重與 manifest 不符")
        return StubSession(manifest, weights, self.alias)


class _PackageDriver(Driver):
    package = ""

    def available(self):
        if importlib.util.find_spec(self.package) is None:
            return False, f"本機沒有 {self.package} 套件"
        return False, f"{self.package} 存在，但 driver 尚未實作（等模型下載同意後再做）"


class OnnxDriver(_PackageDriver):
    name = "onnx"
    package = "onnxruntime"


class TfliteDriver(_PackageDriver):
    name = "tflite"
    package = "tflite_runtime"


class NeuronDriver(Driver):
    name = "neuron"

    def available(self):
        return False, "Genio 520 NPU 工具鏈尚未查證"


def default_drivers(alias):
    return {d.name: d for d in (StubDriver(alias), OnnxDriver(), TfliteDriver(), NeuronDriver())}
