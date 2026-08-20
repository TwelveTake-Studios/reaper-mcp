"""Per-call bridge deadlines (issue #11).

The bridge answers only once the work finishes and renders run at roughly realtime, so
one global 5s deadline reported a failure for every render longer than five seconds. The
env var alone was not the fix: raising it globally makes a genuinely dead bridge take
that long to diagnose on EVERY call. So a call that knows its own work is slow carries
its own deadline, and the rest of the surface keeps the fast one.
"""
import asyncio
import time

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


# --- the deadline reaches the transport ------------------------------------------

def test_render_project_asks_for_the_render_deadline(reaper):
    run(srv.render_project("/tmp/out.wav", start_time=0.0, end_time=1.0))
    assert reaper.last_timeout == srv.RENDER_TIMEOUT, (
        "render_project must carry its own deadline; without it a realtime render "
        "reports a timeout for work REAPER is completing normally (#11)"
    )


def test_ordinary_tools_do_not_carry_a_deadline(reaper):
    """Everything else stays on the fast global, so a dead bridge is still diagnosed fast."""
    run(srv.get_track_count())
    assert reaper.last_timeout is None


def test_reaper_call_forwards_the_deadline_to_dispatch(monkeypatch):
    seen = {}

    async def fake_dispatch(func, args, timeout=None):
        seen["func"], seen["args"], seen["timeout"] = func, args, timeout
        return {"ok": True}

    monkeypatch.setattr(srv, "dispatch", fake_dispatch)
    monkeypatch.setattr(srv, "ensure_bridge_current", lambda: _none())
    run(srv.reaper_call("Whatever", 1, 2, timeout=42.0))
    assert seen["timeout"] == 42.0
    assert seen["args"] == [1, 2], "the deadline must not be swallowed as a REAPER argument"


async def _none():
    return None


def test_timeout_is_keyword_only():
    """A positional slot would eat a REAPER argument at every existing call site."""
    with pytest.raises(TypeError):
        run(srv.reaper_call("CountTracks", 0, 99.0, _positional_deadline=True))


# --- the transport actually honours it -------------------------------------------

def test_transport_waits_the_per_call_deadline_not_the_global(monkeypatch, tmp_path):
    """A short global must not cut a call that asked for longer."""
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.05)
    monkeypatch.setattr(srv, "FILE_POLL_INTERVAL", 0.01)
    start = time.time()
    res = run(srv.reaper_call_file("Slow", [], timeout=0.45))
    elapsed = time.time() - start
    assert res["ok"] is False
    assert elapsed >= 0.4, (
        f"gave up after {elapsed:.2f}s; the per-call deadline was ignored in favour "
        "of the global one"
    )
    assert "0.45s" in res["error"], "the message must name the deadline actually used"


def test_transport_falls_back_to_the_global_when_no_deadline_given(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.05)
    monkeypatch.setattr(srv, "FILE_POLL_INTERVAL", 0.01)
    start = time.time()
    res = run(srv.reaper_call_file("Slow", []))
    assert res["ok"] is False
    assert time.time() - start < 0.4
    assert "0.05s" in res["error"]


def test_global_is_read_at_call_time_not_bound_as_a_default(monkeypatch, tmp_path):
    """The fixtures monkeypatch the module global; a def-time default stops seeing it."""
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "FILE_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.03)
    res = run(srv.reaper_call_file("Slow", []))
    assert "0.03s" in res["error"]


def test_render_timeout_default_is_generous_enough_for_a_realtime_render():
    assert srv.RENDER_TIMEOUT >= 60.0, (
        "renders run at roughly realtime; a small default reintroduces #11"
    )
