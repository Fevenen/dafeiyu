"""v0_load.py — 加载内置的 _v0 模块（只加载一次）。"""

import importlib


def _get(name):
    return importlib.import_module("bridge._v0." + name)


def config():
    return _get("config")


def vault():
    return _get("vault").vault


def sender():
    return _get("sender")


def reminders():
    return _get("reminders")


def when():
    return _get("when")


def name_match():
    return _get("name_match")