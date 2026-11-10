"""Execution scope, isolated across threads and asyncio tasks."""

import os
from contextlib import contextmanager
from contextvars import ContextVar

_session = ContextVar("pet_session", default=None)
_request = ContextVar("pet_request", default=None)
_user_text = ContextVar("pet_user_text", default=None)


def session_id():
    return _session.get() or os.environ.get("BRIDGE_SESSION_ID", "local")


def request_id():
    return _request.get()


def user_text():
    return _user_text.get()


@contextmanager
def scope(session, request=None, text=None):
    tokens = (_session.set(str(session)), _request.set(request), _user_text.set(text))
    try:
        yield
    finally:
        for var, token in zip((_session, _request, _user_text), tokens):
            var.reset(token)
