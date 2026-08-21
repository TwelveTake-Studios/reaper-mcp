"""The request id that proves an answer belongs to the caller (issue #16).

Exclusive-create claiming makes a slot provably yours, but `reaper_call_file` falls back
to an unclaimed write whenever the version probe has no verdict yet, and the response
carried nothing to check against. In that window a response read out of a slot you do not
own is a well-formed WRONG ANSWER rather than a timeout, which for a server that edits
someone's project is the worse failure by a wide margin.

The id also closes the abandonment case: a slot reclaimed after a timeout could read the
previous call's answer, because the stale response was newer than the new request and
nothing distinguished them.
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import reaper_mcp_server as srv

REPO = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "FILE_POLL_INTERVAL", 0.005)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.6)
    return tmp_path


async def _answer(mailbox, reply, mutate_id=None, delay=0.02):
    """Wait for the request to land, then write a response beside it.

    Answers the slot the transport actually claimed rather than assuming one, so the
    test does not quietly depend on the counter's starting position.
    """
    deadline = time.time() + 2.0
    while time.time() < deadline:
        reqs = list(mailbox.glob("request_*.json"))
        for r in reqs:
            text = r.read_text()
            if not text.strip():
                continue  # mid-claim: the zero-byte window, same as the bridge sees
            sent = json.loads(text)
            out = dict(reply)
            if mutate_id is None:
                out["id"] = sent.get("id")
            elif mutate_id is not False:
                out["id"] = mutate_id
            await asyncio.sleep(delay)
            slot = r.name[len("request_"):-len(".json")]
            (mailbox / f"response_{slot}.json").write_text(json.dumps(out))
            return sent
        await asyncio.sleep(0.005)
    raise AssertionError("no request file ever appeared")


def test_request_carries_an_id(mailbox):
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        sent = await _answer(mailbox, {"ok": True, "ret": 5})
        return sent, await task
    sent, res = run(go())
    assert isinstance(sent.get("id"), str) and sent["id"], f"no id in request: {sent}"
    assert res["ok"] is True and res["ret"] == 5


def test_matching_id_is_accepted(mailbox):
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        await _answer(mailbox, {"ok": True, "ret": 7})
        return await task
    assert run(go())["ret"] == 7


def test_foreign_id_is_never_returned(mailbox):
    """The whole point. Another process's answer must not become ours."""
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        await _answer(mailbox, {"ok": True, "ret": 999}, mutate_id="somebody-elses-id")
        return await task
    res = run(go())
    assert res["ok"] is False, f"returned another process's answer: {res}"
    assert "timed out" in res["error"]
    assert res.get("ret") != 999


def test_foreign_response_is_left_for_its_owner(mailbox):
    """Deleting it would strand the process that is still waiting for it."""
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        await _answer(mailbox, {"ok": True, "ret": 999}, mutate_id="somebody-elses-id")
        await task
    run(go())
    leftovers = list(mailbox.glob("response_*.json"))
    assert leftovers, "the foreign response was consumed; its owner will now hang"
    assert json.loads(leftovers[0].read_text())["id"] == "somebody-elses-id"


def test_response_without_an_id_is_still_accepted(mailbox):
    """A bridge older than the echo, and the malformed-JSON path which has no id to echo.

    The first is exactly today's behaviour and must not regress into a timeout; the
    second hands back an error rather than a plausible answer, so it is safe to take.
    """
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        await _answer(mailbox, {"ok": True, "ret": 3}, mutate_id=False)
        return await task
    res = run(go())
    assert res["ok"] is True and res["ret"] == 3


def test_ids_differ_between_calls(mailbox):
    seen = set()
    for _ in range(3):
        async def go():
            task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
            sent = await _answer(mailbox, {"ok": True, "ret": 0})
            await task
            return sent
        seen.add(run(go())["id"])
    assert len(seen) == 3, f"ids repeated across calls: {seen}"


def test_counter_starts_from_the_pid_not_zero():
    """Every process starting at 0 aimed every first unclaimed write at slot 1.

    Checked in a real subprocess: the module global moves as soon as anything calls, so
    asserting it in-process would only ever see whatever this session has done to it.
    """
    out = subprocess.run(
        [sys.executable, "-c",
         "import os, sys; sys.path.insert(0, r'%s'); import reaper_mcp_server as s; "
         "print(s.request_counter, os.getpid() %% 999)" % REPO],
        capture_output=True, text=True, timeout=90,
    )
    assert out.returncode == 0, out.stderr[-1500:]
    counter, expected = (int(x) for x in out.stdout.split())
    assert counter == expected, (
        f"request_counter starts at {counter}, not the PID-derived {expected}; "
        "every process would start on the same slot again"
    )
    assert counter != 0 or expected == 0
