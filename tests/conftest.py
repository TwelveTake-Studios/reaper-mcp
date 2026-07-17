"""Shared pytest fixtures.

Tools call the module-level ``reaper_call`` to reach REAPER. We monkeypatch that
single function with a recorder, so every tool can be exercised without REAPER (or the
bridge) running — we assert on the (func, args) the tool would have sent and on how it
handles the response.
"""

import copy
import sys
from pathlib import Path

import pytest

# reaper_mcp_server.py lives at the repo root, one level up from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reaper_mcp_server as srv  # noqa: E402


class Recorder:
    """Stand-in for reaper_call: records calls and returns a canned response.

    The response is deep-copied on the way out, and the recorded args are deep-copied on the
    way in. Both matter, and neither is paranoia:

    * Returning ``self.response`` itself made every ``assert run(tool(...)) == reaper.response``
      a tautology -- the tool's return value and the expected value were the SAME object, so the
      assertion read ``x == x`` and could not fail. A tool corrupting the bridge's reply in place
      (``resp["notes_changed"] = 0``) sailed through every such test. The current passthrough
      test (``test_bridge_reply_passes_through_unchanged``) no longer relies on this -- it compares
      against an INDEPENDENT literal, which catches in-place corruption on its own. So the
      copy-out is defense-in-depth: it keeps even a ``== reaper.response``-style test honest,
      should one ever be written again.
    * Copying the args IS load-bearing: recording them by reference would let a tool mutate a
      dict it already sent (the filter object) and have the recorded call quietly agree with it,
      defeating the marshalling assertions.
    """

    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {"ok": True, "ret": 0}

    async def __call__(self, func, *args):
        self.calls.append((func, copy.deepcopy(list(args))))
        return copy.deepcopy(self.response)

    @property
    def last(self):
        assert self.calls, "no reaper_call was made"
        return self.calls[-1]


@pytest.fixture
def reaper(monkeypatch):
    """Patch reaper_call with a Recorder and hand it to the test."""
    rec = Recorder()
    monkeypatch.setattr(srv, "reaper_call", rec)
    return rec
