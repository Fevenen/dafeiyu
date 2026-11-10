"""Desktop input uses the same route and confirmation service as other entry points."""

from .router import route


def handle(text):
    result = route(text)
    return result is not None, result or ""
