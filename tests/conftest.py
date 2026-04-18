"""
pytest conftest for the Velure repo tests.

Two responsibilities:
  1. Make `backend/` importable regardless of the cwd from which pytest
     is launched (handy for IDE runners and CI).
  2. Force a fresh asyncio event loop per session so tests that touch
     the singleton ensemble don't share loop state across runs.
"""
import asyncio
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND   = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so the singleton ensemble doesn't bind to
    a per-test loop that gets closed mid-suite."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
