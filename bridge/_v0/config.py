"""config.py（bridge 内置版）— 配置来源：bridge/config.json → 环境变量 → 默认值。

和原 v0 的 config.py 接口保持兼容：
    config（dict）、int_cfg()、onebot_url()、onebot_token()、token_source()、LOG_DIR
"""

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pet\bridge
LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_CFG_FILE = os.path.join(BASE, "config.json")

_KEYS = (
    "LLM_API_KEY", "LLM_BASE", "LLM_MODEL",
    "ONEBOT_URL", "ONEBOT_TOKEN",
    "NAPCAT_URL", "NAPCAT_TOKEN",
    "DRY_RUN", "CONFIRM_TIMEOUT", "VAULT_TOKEN_TTL", "MAX_SEND_PER_MINUTE",
    "GREETING", "GREETING_ASCII", "VAULT_RESOLVE_PER_MINUTE",
)


def load():
    cfg = {}
    # 1) bridge/config.json
    if os.path.exists(_CFG_FILE):
        try:
            with open(_CFG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            # 允许两种写法：扁平键 或 嵌套 onebot 段
            if isinstance(data, dict):
                for k, v in data.items():
                    if k.startswith("//"):
                        continue
                    cfg[k.upper()] = v
                ob = data.get("onebot") or {}
                if isinstance(ob, dict):
                    if ob.get("url"):
                        cfg["ONEBOT_URL"] = ob["url"]
                    if ob.get("token"):
                        cfg["ONEBOT_TOKEN"] = ob["token"]
        except Exception:
            pass

    # 2) 环境变量覆盖
    for k in _KEYS:
        if k in os.environ:
            cfg[k] = os.environ[k]
    return cfg


config = load()


def int_cfg(name, default):
    try:
        return int(config.get(name, default))
    except (TypeError, ValueError):
        return default


def onebot_url() -> str:
    url = config.get("ONEBOT_URL") or config.get("NAPCAT_URL") or "http://127.0.0.1:3000"
    return str(url).rstrip("/")


def onebot_token() -> str:
    return str(config.get("ONEBOT_TOKEN") or config.get("NAPCAT_TOKEN") or "")


def token_source() -> str:
    if config.get("ONEBOT_TOKEN"):
        return "config.json: onebot.token / ONEBOT_TOKEN"
    if config.get("NAPCAT_TOKEN"):
        return "NAPCAT_TOKEN"
    return "（未配置）"
