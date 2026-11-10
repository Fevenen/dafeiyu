"""Reminder delivery worker. Database leases make multiple workers safe."""

import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge.v0_load import reminders
from bridge.reminder_delivery import deliver
from bridge import settings


def main():
    while True:
        try:
            for item in reminders().due_now():
                deliver(item)
        except Exception as exc:
            settings.ensure_dirs()
            with (settings.LOG_DIR / "scheduler.log").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(type(exc).__name__ + ": " + str(exc) + "\n")
        time.sleep(15)


if __name__ == "__main__":
    try:
        from bridge.singleton import singleton

        with singleton("scheduler"):
            main()
    except KeyboardInterrupt:
        pass
