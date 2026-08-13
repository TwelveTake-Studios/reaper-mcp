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
    # Claiming is gated on the deployed bridge carrying the mid-claim guard, so these
    # tests declare that bridge. Without it reaper_call_file takes the single-shot
    # fallback and there is no claim to test.
    monkeypatch.setitem(srv._bridge_check, "claims_ok", True)
    return tmp_path


@pytest.fixture
def mailbox_old_bridge(mailbox, monkeypatch):
    """The same mailbox against a bridge that predates the mid-claim guard."""
    monkeypatch.setitem(srv._bridge_check, "claims_ok", False)
    return mailbox


def test_old_bridge_is_never_sent_the_zero_byte_window(mailbox_old_bridge, monkeypatch):
    """The exclusive create is what makes request_N.json briefly visible at zero
    bytes. A bridge without the mid-claim guard answers that window with a false
    'Malformed request JSON', so against one the claim must not happen at all."""
    import os as real_os
    claims = []

    class RecordingOS:
        def __getattr__(self, name):
            return getattr(real_os, name)

        def open(self, path, flags, *args, **kwargs):
            if flags & real_os.O_EXCL:
                claims.append(path)
            return real_os.open(path, flags, *args, **kwargs)

    monkeypatch.setattr(srv, "os", RecordingOS())
    run(srv.reaper_call_file("CountTracks", [0]))
    assert claims == [], "claimed a slot against a bridge that cannot tolerate it"


def test_old_bridge_still_clears_a_stale_response(mailbox_old_bridge):
    """The orphan that would otherwise be read back as this call's answer."""
    (mailbox_old_bridge / "response_1.json").write_text('{"ok": true, "ret": 99}')
    out = run(srv.reaper_call_file("CountTracks", [0]))
    assert out["ok"] is False, "a stale orphan was returned as this call's answer"
    assert not (mailbox_old_bridge / "response_1.json").exists()


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


def test_write_fault_is_not_reported_as_a_full_mailbox(mailbox, monkeypatch):
    """No permission, full disk, read-only mount: that fault hits every slot,
    not just this one. Reported as "all 999 in use" it sends whoever reads the
    error hunting for stale request files that are not there.

    ``srv.os`` is swapped for a proxy rather than patching ``os.open`` itself,
    so only the module under test sees the failure.
    """
    class DeniedOS:
        def __getattr__(self, name):
            return getattr(os, name)

        def open(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(srv, "os", DeniedOS())

    result = run(srv.reaper_call_file("CountTracks", [0]))

    assert result["ok"] is False
    assert "No free bridge request slot" not in result["error"], result["error"]
    assert "Permission denied" in result["error"], result["error"]


def test_timeout_cleans_up_its_own_request_file(mailbox):
    """A call that times out must not leave its slot burned forever."""
    run(srv.reaper_call_file("CountTracks", [0]))

    assert list(mailbox.glob("request_*.json")) == []


# --------------------------------------------------------------------------
# PART B -- needs a running REAPER with the bridge loaded
# --------------------------------------------------------------------------

_BRIDGE_PROBE = None


@pytest.fixture
def live_bridge():
    """Skip unless a bridge actually answers.

    The ``live`` marker only LABELS a test -- a plain ``pytest`` run still
    executes it, and only ``-m "not live"`` deselects it. Enforcing the skip
    here means these tests are correct under any invocation rather than
    depending on how the runner was called.
    """
    global _BRIDGE_PROBE
    if _BRIDGE_PROBE is None:
        original = srv.FILE_TIMEOUT
        srv.FILE_TIMEOUT = 2.0  # a loaded bridge answers in milliseconds
        try:
            probe = run(srv.reaper_call_file("GetAppVersion", []))
        finally:
            srv.FILE_TIMEOUT = original
        _BRIDGE_PROBE = probe if probe.get("ok") else False
    if _BRIDGE_PROBE is False:
        pytest.skip("no live REAPER bridge on this machine")


@pytest.mark.live
def test_interleaved_calls_each_get_their_own_answer(live_bridge):
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
def test_stale_response_is_not_mistaken_for_ours(live_bridge, monkeypatch):
    """An abandoned call leaves its response behind. The mailbox held exactly
    such an orphan for 12 days. Claiming the slot unlinks whatever response_N
    is sitting in it, so the orphan is gone before the poll loop can read it.

    Asserts the real answer arrived, not merely that the poison did not. A
    bare `ret != "STALE-POISON"` is satisfied by a timeout, which has no `ret`
    at all -- so it would pass on a machine with no bridge and could never
    fail for the right reason.
    """
    monkeypatch.setattr(srv, "request_counter", 400)
    poison = srv.BRIDGE_DIR / "response_401.json"
    poison.write_text(json.dumps({"ok": True, "ret": "STALE-POISON"}))
    backdated = time.time() - 600
    os.utime(poison, (backdated, backdated))

    try:
        result = run(srv.reaper_call_file("CountTracks", [0]))
        assert result.get("ok"), result
        assert result["ret"] != "STALE-POISON"
        assert isinstance(result["ret"], (int, float)), result
    finally:
        poison.unlink(missing_ok=True)
