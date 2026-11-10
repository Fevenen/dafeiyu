"""OS-owned locks released automatically when the process exits."""

import os
from contextlib import contextmanager
from . import settings


def is_running(name):
    try:
        with singleton(name):
            return False
    except RuntimeError:
        return True


@contextmanager
def singleton(name):
    settings.ensure_dirs()
    stream = (settings.DATA_DIR / "state" / (name + ".lock")).open("a+b")
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError(name + " is already running for this data directory")
    try:
        yield
    finally:
        stream.close()
