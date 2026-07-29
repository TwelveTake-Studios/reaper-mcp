"""Request-slot claiming: two servers on one mailbox must not collide.

One stdio server is spawned per MCP client, and the file mailbox is shared
machine-wide, so running Claude Desktop and Claude Code at once means two live
servers on one directory. ``request_counter`` is a per-process global starting
at 0, so both allocated ``request_1.json`` on their first call.

PART A runs against an isolated temp mailbox with no bridge draining it, so
occupancy is stable and assertable. PART B needs a live bridge and is marked
``live`` (opt in with ``pytest -m live``).
"""

import asyncio
import json
import os
import time

import pytest

import reaper_mcp_server as srv

SENTINEL = "SQUATTER"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    """An isolated mailbox that nothing is draining.

    BRIDGE_DIR_PROBLEM is neutralised because it is computed at import from the
    real REAPER resource path: on a CI runner with no REAPER installed it is
    set, and reaper_call_file would refuse before reaching the claim logic these
    tests are about.
    """
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None, raising=False)
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.2)  # nothing will answer; fail fast
    monkeypatch.setattr(srv, "request_counter", 0)
    return tmp_path


def occupy(mailbox, lo, hi):
    for n in range(lo, hi + 1):
        (mailbox / f"request_{n}.json").write_text(SENTINEL)


def test_claim_skips_occupied_slots(mailbox):
    occupy(mailbox, 1, 11)

    run(srv.reaper_call_file("CountTracks", [0]))

    assert srv.request_counter > 11, (
        f"claimed slot {srv.request_counter}, which another process already owns"
    )


def test_claim_never_overwrites_an_occupied_slot(mailbox):
    occupy(mailbox, 1, 11)

    run(srv.reaper_call_file("CountTracks", [0]))

    survivors = [
        n for n in range(1, 12)
        if (mailbox / f"request_{n}.json").read_text() == SENTINEL
    ]
    assert survivors == list(range(1, 12)), "a pending request was overwritten"


def test_exhausted_mailbox_refuses_cleanly(mailbox):
    occupy(mailbox, 1, 999)

    result = run(srv.reaper_call_file("CountTracks", [0]))

    assert result["ok"] is False
    assert "No free bridge request slot" in result["error"]


def test_timeout_cleans_up_its_own_request_file(mailbox):
    """A call that times out must not leave its slot burned forever."""
    run(srv.reaper_call_file("CountTracks", [0]))

    assert list(mailbox.glob("request_*.json")) == []


# --------------------------------------------------------------------------
# PART B -- needs a running REAPER with the bridge loaded
# --------------------------------------------------------------------------

@pytest.mark.live
def test_interleaved_calls_each_get_their_own_answer():
    """Cross-talk returns a well-formed WRONG answer, which is worse than a
    timeout for anything that measures. The two calls have different answer
    TYPES, so a swap shows up as a type error rather than a plausible number.
    """
    async def burst():
        return await asyncio.gather(*[
            srv.reaper_call_file("CountTracks", [0]),
            srv.reaper_call_file("GetAppVersion", []),
            srv.reaper_call_file("CountTracks", [0]),
            srv.reaper_call_file("GetAppVersion", []),
            srv.reaper_call_file("CountTracks", [0]),
            srv.reaper_call_file("GetAppVersion", []),
        ])

    results = run(burst())
    assert all(r.get("ok") for r in results), results

    counts = [results[i]["ret"] for i in (0, 2, 4)]
    versions = [results[i]["ret"] for i in (1, 3, 5)]
    assert all(isinstance(v, (int, float)) for v in counts), counts
    assert all(isinstance(v, str) for v in versions), versions


@pytest.mark.live
def test_stale_response_is_not_mistaken_for_ours(monkeypatch):
    """An abandoned call leaves its response behind. The mailbox held exactly
    such an orphan for 12 days, so the response is gated on mtime.
    """
    monkeypatch.setattr(srv, "request_counter", 400)
    poison = srv.BRIDGE_DIR / "response_401.json"
    poison.write_text(json.dumps({"ok": True, "ret": "STALE-POISON"}))
    backdated = time.time() - 600
    os.utime(poison, (backdated, backdated))

    try:
        result = run(srv.reaper_call_file("CountTracks", [0]))
        assert result.get("ret") != "STALE-POISON"
    finally:
        poison.unlink(missing_ok=True)
