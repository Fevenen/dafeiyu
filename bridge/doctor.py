"""Read-only diagnostics. Does not contact QQ or send messages unless --network checks health."""

import argparse
import importlib.util
import json
import sys
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
            for m in ("requests", "pypinyin", "rapidfuzz", "mcp")
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
    args = parser.parse_args()
    report = inspect(args.network)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return (
        0 if report["bundled_helpers"] and all(report["dependencies"].values()) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
