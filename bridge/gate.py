"""Desktop input uses the same route and confirmation service as other entry points."""

from .router import route
from .intent import classify


def handle(text, recent_messages=None):
    result = route(text, classifier=lambda value, catalogue: classify(value, catalogue, recent_messages),
                   recent_messages=recent_messages, allow_screen=False)
    return result is not None, result or ""
