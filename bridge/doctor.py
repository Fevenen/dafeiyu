"""Inspect local services and optionally run a synthetic model readiness check."""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import settings
from bridge.net import urlopen


def inspect(network=False):
    report = {
        "python": sys.executable,
        "config": str(settings.CONFIG_PATH),
        "config_exists": settings.CONFIG_PATH.exists(),
        "data_dir": str(settings.DATA_DIR),
        "pet_api": settings.PET_API,
        "session_directory_exists": settings.SESSIONS_DIR.is_dir(),
        "dependencies": {
            m: importlib.util.find_spec(m) is not None
            for m in ("requests", "pypinyin", "rapidfuzz", "mcp", "zstandard")
        },
        "bundled_helpers": (settings.BRIDGE_ROOT / "_v0/sender.py").exists(),
    }
    if network:
        try:
            with urlopen(settings.PET_API + "/api/health", timeout=3) as response:
                report["backend"] = json.load(response)
        except Exception as exc:
            report["backend"] = {"ok": False, "error": type(exc).__name__}
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--warmup", action="store_true", help="run a synthetic KVMem intent check after startup")
    args = parser.parse_args()
    report = inspect(args.network)
    if args.warmup:
        from bridge.capabilities import REGISTRY
        from bridge.intent import IntentTransportError, warmup

        started = time.perf_counter()
        try:
            ready = warmup(REGISTRY)
            report["model_warmup"] = {"ok": ready}
            if not ready:
                report["model_warmup"]["error"] = "invalid_intent_result"
        except IntentTransportError as exc:
            report["model_warmup"] = {"ok": False, "error": str(exc)}
        report["model_warmup"]["seconds"] = round(time.perf_counter() - started, 2)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.warmup and not report["model_warmup"]["ok"]:
        return 1
    return (
        0 if report["bundled_helpers"] and all(report["dependencies"].values()) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
