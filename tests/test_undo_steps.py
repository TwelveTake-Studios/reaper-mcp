"""Every edit is one named undo step; reads, transport and undo itself are not.

The bridge opens an undo block only for a request that carries an `undo` label, so the
label the server sends is the whole mechanism. These pin which tools send one, what it
says, that it reaches the request file, and that the annotations it is derived from are
explicit on every tool.
"""
import asyncio
import json
import time

import pytest

import reaper_mcp_server as srv


REAL_BRIDGE_DIR = srv.BRIDGE_DIR


def run(coro):
    return asyncio.run(coro)


def test_mocked_tests_never_point_at_the_real_bridge():
    assert srv.BRIDGE_DIR != REAL_BRIDGE_DIR


def tools():
    return {t.name: t for t in srv.mcp._tool_manager.list_tools()}


def is_read_only(tool):
    return tool.annotations is not None and tool.annotations.readOnlyHint is True


@pytest.fixture
def labels(monkeypatch):
    seen = []

    async def fake(func, *args, timeout=None):
        seen.append((func, srv.undo_label.get()))
        return {"ok": True, "ret": 0}

    async def fake_batch(*calls, timeout=None):
        for func, *_ in calls:
            seen.append((func, srv.undo_label.get()))
        return {"ok": True, "results": [{"ok": True, "ret": 0} for _ in calls]}

    monkeypatch.setattr(srv, "reaper_call", fake)
    monkeypatch.setattr(srv, "reaper_batch", fake_batch)
    return seen


def test_every_tool_declares_read_only_or_destructive_explicitly():
    vague = [
        name for name, t in tools().items()
        if not is_read_only(t)
        and (t.annotations is None or t.annotations.destructiveHint is None)
    ]
    assert not vague, f"tools relying on the spec's destructive-by-default: {vague}"


def test_no_read_only_tool_claims_to_be_destructive():
    both = [
        name for name, t in tools().items()
        if is_read_only(t) and t.annotations.destructiveHint is not None
    ]
    assert not both, both


def test_the_undo_step_tools_are_exactly_the_non_exempt_writes():
    expected = {
        name for name, t in tools().items()
        if not is_read_only(t) and name not in srv.UNDO_EXEMPT_TOOLS
    }
    assert set(srv.UNDO_STEP_TOOLS) == expected


def test_every_exempt_name_is_a_real_tool():
    assert srv.UNDO_EXEMPT_TOOLS <= set(tools())


def test_undo_and_redo_are_never_wrapped():
    assert "undo" not in srv.UNDO_STEP_TOOLS
    assert "redo" not in srv.UNDO_STEP_TOOLS


def test_a_write_sends_its_tool_label(labels):
    run(srv.set_track_volume(0, -6.0))
    assert labels == [("SetMediaTrackInfo_Value", "MCP: set track volume")]


def test_the_registered_tool_and_the_module_function_are_the_same_wrapper(labels):
    registered = tools()["delete_track"].fn
    assert registered is srv.delete_track
    run(registered(1))
    assert labels == [("DeleteTrack", "MCP: delete track")]


def test_a_read_sends_no_label(labels):
    run(srv.get_track(0))
    assert labels == [("GetTrackInfo", None)]


@pytest.mark.parametrize("tool", ["undo", "redo", "play", "run_action"])
def test_exempt_tools_send_no_label(labels, tool):
    fn = getattr(srv, tool)
    run(fn(40001) if tool == "run_action" else fn())
    assert labels and all(label is None for _, label in labels), labels


def test_the_label_does_not_leak_past_the_call(labels):
    async def session():
        await srv.set_track_volume(0, -6.0)
        await srv.get_track(0)
        return srv.undo_label.get()
    assert run(session()) is None
    assert labels[-1] == ("GetTrackInfo", None)


def test_a_multi_call_tool_labels_every_call_with_its_own_name(labels):
    run(srv.create_bus("Drums", [0, 1]))
    assert labels
    assert all(label == "MCP: create bus" for _, label in labels), labels


@pytest.fixture
def request_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    monkeypatch.setattr(srv, "FILE_POLL_INTERVAL", 0.005)
    monkeypatch.setattr(srv, "FILE_TIMEOUT", 0.6)
    return tmp_path


async def _capture(request_dir, reply):
    deadline = time.time() + 2.0
    while time.time() < deadline:
        for r in request_dir.glob("request_*.json"):
            text = r.read_text(encoding="utf-8")
            if not text.strip():
                continue
            sent = json.loads(text)
            slot = r.name[len("request_"):-len(".json")]
            out = dict(reply, id=sent.get("id"))
            (request_dir / f"response_{slot}.json").write_text(json.dumps(out))
            return sent
        await asyncio.sleep(0.005)
    raise AssertionError("no request file ever appeared")


def test_the_label_is_written_into_the_request(request_dir):
    async def go():
        srv.undo_label.set("MCP: delete track")
        task = asyncio.ensure_future(srv.reaper_call_file("DeleteTrack", [2]))
        sent = await _capture(request_dir, {"ok": True})
        await task
        return sent
    sent = run(go())
    assert sent["undo"] == "MCP: delete track"
    assert sent["func"] == "DeleteTrack"


def test_an_unlabelled_request_has_no_undo_key(request_dir):
    async def go():
        task = asyncio.ensure_future(srv.reaper_call_file("CountTracks", [0]))
        sent = await _capture(request_dir, {"ok": True, "ret": 1})
        await task
        return sent
    assert "undo" not in run(go())


def test_a_batch_is_one_request_carrying_every_call(request_dir, monkeypatch):
    async def current():
        return None
    monkeypatch.setattr(srv, "ensure_bridge_current", current)

    async def go():
        srv.undo_label.set("MCP: insert track")
        task = asyncio.ensure_future(srv.reaper_batch(
            ("InsertTrackAtIndex", 3, True),
            ("GetSetMediaTrackInfo_String", 3, "P_NAME", "Bass", True),
        ))
        sent = await _capture(request_dir, {"ok": True, "results": [{"ok": True}, {"ok": True}]})
        return sent, await task
    sent, result = run(go())
    assert "func" not in sent
    assert sent["calls"] == [
        {"func": "InsertTrackAtIndex", "args": [3, True]},
        {"func": "GetSetMediaTrackInfo_String", "args": [3, "P_NAME", "Bass", True]},
    ]
    assert sent["undo"] == "MCP: insert track"
    assert result["ok"] is True
    assert len(list(request_dir.glob("request_*.json"))) == 0
