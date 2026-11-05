"""Load and verify a feature's recorded harness components using raw file bytes.

本任務只提供版本標記與紀錄能力，不宣稱已完成端到端版本追蹤。閘道只記錄呼叫端送來的 `X-GCS-Harness`，不驗證它是否對應實際元件；未接線的呼叫標示為 `unversioned`。要等各功能完成接線並驗證後，論文才可把紀錄當作完整的版本追溯證據。

Component paths are relative to the repository root (parent of gcs_demo).
Embedded components record the whole containing module, not an extracted prompt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATURES = frozenset(("ui", "alerts", "mission", "report", "recognition"))
COMPONENTS = frozenset(("system_prompt", "schema", "guard", "fallback"))


def digest(manifest: dict) -> str:
    """Canonical UTF-8 JSON, excluding only the top-level harness_sha256 field."""
    payload = {k: v for k, v in manifest.items() if k != "harness_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def load(feature: str) -> dict:
    if feature not in FEATURES:
        raise ValueError(f"unknown harness feature: {feature!r}")
    manifest_path = ROOT / "gcs_demo" / "harness" / feature / "manifest.json"
    with manifest_path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict) or manifest.get("feature") != feature:
        raise ValueError("manifest feature mismatch")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ValueError("manifest version missing")
    if manifest.get("harness_sha256") != digest(manifest):
        raise ValueError("manifest harness_sha256 mismatch")
    components = manifest.get("components")
    if not isinstance(components, dict) or set(components) != COMPONENTS:
        raise ValueError("manifest component set mismatch")
    root = ROOT.resolve()
    for name, component in components.items():
        if not isinstance(component, dict):
            raise ValueError(f"invalid component: {name}")
        if "path" not in component or "sha256" not in component:
            raise ValueError(f"missing component fields: {name}")
        relative = component["path"]
        if relative is None:
            if component["sha256"] is not None or not component.get("note"):
                raise ValueError(f"unavailable component needs null hash and note: {name}")
            continue
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"invalid component path: {name}")
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"component outside repository: {name}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != component["sha256"]:
            raise ValueError(f"component sha256 mismatch: {name}")
    return manifest


def header(feature: str) -> str:
    manifest = load(feature)
    return f"{feature}@{manifest['version']}#{manifest['harness_sha256'][:8]}"
