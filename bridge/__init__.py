"""Portable desktop companion bridge. All helper modules are bundled."""

import os

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
from .settings import DATA_DIR

STATE_DIR = str(DATA_DIR / "state")
