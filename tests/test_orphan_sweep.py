"""Tests for the startup orphan-response sweep (issue #13's precondition).

A timed-out call leaves its ``response_N.json`` behind, and a process restart makes
the file unreachable forever: ``request_counter`` restarts at 1, so a short session
never revisits the high slot that would have cleared it at claim time. Those files
tax the bridge's per-tick directory enumeration, which is exactly what killed the
first EnumerateFiles attempt (revert ``331d12f``: 0.07s -> 0.53s round trip with 60
stale files). The sweep runs once at server startup and deletes ONLY aged response
files — never requests, never fresh responses another server may be waiting on.
"""

import os
import time
from pathlib import Path

import pytest

import reaper_mcp_server as srv


def age(path: Path, seconds: float) -> None:
    """Backdate a file's mtime by ``seconds``."""
    past = time.time() - seconds
    os.utime(path, (past, past))


@pytest.fixture
def mailbox(tmp_path):
    return tmp_path


def test_old_response_is_swept(mailbox):
    orphan = mailbox / "response_15.json"
    orphan.write_text('{"ok": true}')
    age(orphan, 60)
    assert srv.sweep_orphaned_responses(mailbox) == 1
    assert not orphan.exists()


def test_fresh_response_survives(mailbox):
    """A response inside the timeout window may still have a live reader."""
    inflight = mailbox / "response_3.json"
    inflight.write_text('{"ok": true}')
    assert srv.sweep_orphaned_responses(mailbox) == 0
    assert inflight.exists()


def test_request_files_are_never_touched(mailbox):
    """An orphaned request is the bridge's to answer, not ours to delete."""
    request = mailbox / "request_7.json"
    request.write_text('{"func": "CountTracks", "args": []}')
    age(request, 3600)
    assert srv.sweep_orphaned_responses(mailbox) == 0
    assert request.exists()


def test_pid_namespaced_response_is_swept(mailbox):
    """WS4 will rename responses to response_<pid>_<n>.json; the sweep already covers it."""
    orphan = mailbox / "response_4242_15.json"
    orphan.write_text('{"ok": true}')
    age(orphan, 60)
    assert srv.sweep_orphaned_responses(mailbox) == 1
    assert not orphan.exists()


def test_lookalikes_survive(mailbox):
    """Only the exact response shapes are ours; anything else is left alone."""
    for name in (
        "response_.json",        # no slot number
        "response_7.json.bak",   # backup copy someone made
        "xresponse_1.json",      # prefix mismatch
        "response_a.json",       # non-numeric slot
        "response_1_2_3.json",   # more underscores than either naming scheme
        "notes.txt",
    ):
        f = mailbox / name
        f.write_text("keep me")
        age(f, 3600)
    assert srv.sweep_orphaned_responses(mailbox) == 0
    assert sorted(p.name for p in mailbox.iterdir()) == sorted(
        ["response_.json", "response_7.json.bak", "xresponse_1.json",
         "response_a.json", "response_1_2_3.json", "notes.txt"]
    )


def test_missing_directory_is_a_noop(tmp_path):
    """First run on a machine: the mailbox may not exist yet. Do not create or raise."""
    ghost = tmp_path / "never_created"
    assert srv.sweep_orphaned_responses(ghost) == 0
    assert not ghost.exists()


def test_counts_every_file_swept(mailbox):
    for n in (1, 2, 3):
        f = mailbox / f"response_{n}.json"
        f.write_text("{}")
        age(f, 60)
    assert srv.sweep_orphaned_responses(mailbox) == 3


def test_future_mtime_orphan_is_swept(mailbox):
    """A response stamped in the future (clock ran fast, then was stepped back:
    dual-boot RTC mismatch, VM restore, NTP) has no live reader either, and with a
    signed age check it would dodge the sweep at every restart until wall time
    caught up — leaving the mailbox unbounded exactly when restarts should bound it."""
    orphan = mailbox / "response_21.json"
    orphan.write_text('{"ok": true}')
    age(orphan, -3600)  # one hour in the FUTURE
    assert srv.sweep_orphaned_responses(mailbox) == 1
    assert not orphan.exists()


def test_slightly_future_response_survives(mailbox):
    """Ordinary sub-window skew must not eat a response a reader may still claim."""
    inflight = mailbox / "response_22.json"
    inflight.write_text('{"ok": true}')
    age(inflight, -2)  # 2s ahead: inside the FILE_TIMEOUT + 2s window
    assert srv.sweep_orphaned_responses(mailbox) == 0
    assert inflight.exists()


def test_age_gate_tracks_file_timeout_at_call_time(mailbox, monkeypatch):
    """FILE_TIMEOUT is resolved when the sweep runs, so monkeypatching works.

    The same file is inside the window under the real timeout and outside it when
    the timeout shrinks; only the second call may sweep it.
    """
    f = mailbox / "response_9.json"
    f.write_text("{}")
    age(f, 4)  # younger than FILE_TIMEOUT(5) + 2s slack, older than 0 + 2s slack
    assert srv.sweep_orphaned_responses(mailbox) == 0
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.5)
    assert srv.sweep_orphaned_responses(mailbox) == 1


def test_main_sweeps_at_startup(mailbox, monkeypatch):
    """The wiring: a file-mode server start clears the mailbox before serving."""
    orphan = mailbox / "response_15.json"
    orphan.write_text('{"ok": true}')
    age(orphan, 60)
    monkeypatch.setattr(srv, "BRIDGE_DIR", mailbox)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "COMM_MODE", "file")
    monkeypatch.setattr(srv.mcp, "run", lambda: None)
    monkeypatch.setattr(srv.sys, "argv", ["twelvetake-reaper-mcp"])
    srv.main()
    assert not orphan.exists()


def test_http_mode_does_not_sweep(mailbox, monkeypatch):
    """HTTP mode never touches the file mailbox, so it must not delete from it either."""
    orphan = mailbox / "response_15.json"
    orphan.write_text('{"ok": true}')
    age(orphan, 60)
    monkeypatch.setattr(srv, "BRIDGE_DIR", mailbox)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "COMM_MODE", "http")
    monkeypatch.setattr(srv.mcp, "run", lambda: None)
    monkeypatch.setattr(srv.sys, "argv", ["twelvetake-reaper-mcp"])
    srv.main()
    assert orphan.exists()
