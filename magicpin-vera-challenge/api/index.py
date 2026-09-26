"""Vercel Python entrypoint — Vercel's Python runtime auto-detects an ASGI
callable named `app` in this file and serves it behind the routes configured
in vercel.json."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import app  # noqa: E402,F401
