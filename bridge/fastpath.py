"""Compatibility adapter: all deterministic routing lives in router.py."""

from .router import route


def try_handle(text):
    result = route(text)
    return result is not None, result or ""
