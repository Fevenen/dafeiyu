"""Shared configuration: CLI overrides > environment > JSON > defaults.
Relative paths resolve against the config directory, never the current cwd.
"""

import json
import os
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = (
    Path(os.environ.get("PET_CONFIG", str(BRIDGE_ROOT / "config.json")))
    .expanduser()
    .resolve()
)
try:
    with CONFIG_PATH.open(encoding="utf-8-sig") as stream:
        CONFIG = json.load(stream)
    if not isinstance(CONFIG, dict):
        raise ValueError("configuration must be an object")
except FileNotFoundError:
    CONFIG = {}


def get(name, default=None, override=None):
    if override is not None:
        return override
    return os.environ.get(
        name.upper(), CONFIG.get(name.lower(), CONFIG.get(name.upper(), default))
    )


def path(name, default, override=None):
    value = Path(str(get(name, default, override))).expanduser()
    return (value if value.is_absolute() else CONFIG_PATH.parent / value).resolve()


DATA_DIR = path("pet_data_dir", "data")
LOG_DIR = DATA_DIR / "logs"
PET_API = str(get("pet_api", "http://127.0.0.1:12393")).rstrip("/")
SESSIONS_DIR = path(
    "dsh_sessions", Path.home() / ".dsh/storages/session_projcache/sessions"
)


def ensure_dirs():
    for folder in (DATA_DIR, LOG_DIR, DATA_DIR / "state"):
        folder.mkdir(parents=True, exist_ok=True)
