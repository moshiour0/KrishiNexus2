from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.getenv("VERCEL"):
    os.environ.setdefault("FIELD_SHIFT_CACHE_DIR", "/tmp/fieldshift_cache")
    # Try the public NASA POWER Daily API for each analysis. The engine keeps an
    # explicit synthetic fallback if the upstream service is unavailable.
    # Set FIELD_SHIFT_LIVE_NASA=0 to force a fully offline run.
    os.environ.setdefault("FIELD_SHIFT_LIVE_NASA", "1")

from fieldshift.api.app import app

__all__ = ["app"]
