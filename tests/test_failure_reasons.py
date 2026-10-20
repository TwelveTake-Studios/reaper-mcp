import asyncio
import json

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


DELETES = [
    (lambda: srv.delete_marker(7), "No marker numbered 7"),
    (lambda: srv.delete_region(3), "No region numbered 3"),
    (lambda: srv.delete_send(2, 5), "Track 2 has no send with index 5"),
]
DELETE_IDS = ["delete_marker", "delete_region", "delete_send"]


@pytest.mark.parametrize("call, message", DELETES, ids=DELETE_IDS)
def test_a_failed_delete_names_what_was_not_found(reaper, call, message):
    reaper.response = {"ok": False}
    assert run(call()) == {"ok": False, "error": message}


@pytest.mark.parametrize("call, message", DELETES, ids=DELETE_IDS)
def test_a_failed_delete_keeps_the_bridges_own_error(reaper, call, message):
    reaper.response = {"ok": False, "error": "Track not found"}
    assert run(call()) == {"ok": False, "error": "Track not found"}


@pytest.mark.parametrize("call, message", DELETES, ids=DELETE_IDS)
def test_a_successful_delete_is_returned_unchanged(reaper, call, message):
    reaper.response = {"ok": True, "ret": True}
    assert run(call()) == {"ok": True, "ret": True}


def test_any_tool_failing_without_a_reason_gets_one(reaper):
    reaper.response = {"ok": False, "ret": False}
    assert run(srv.set_track_pan(1, 0.5)) == {
        "ok": False, "ret": False,
        "error": "set_track_pan did not succeed; REAPER reported no reason",
    }


def test_an_empty_error_counts_as_missing(reaper):
    reaper.response = {"ok": False, "error": ""}
    assert run(srv.get_track(4))["error"] == "get_track did not succeed; REAPER reported no reason"


@pytest.mark.parametrize("reply", [{"ok": True}, {"ret": 3}, {"ok": False, "error": "Track not found"}])
def test_replies_that_are_not_silent_failures_are_untouched(reaper, reply):
    reaper.response = dict(reply)
    assert run(srv.get_track(4)) == reply


def test_every_registered_tool_is_covered_and_is_the_module_function():
    registered = srv.mcp._tool_manager.list_tools()
    assert set(srv.FAILURE_REASON_TOOLS) == {t.name for t in registered}
    for tool in registered:
        assert getattr(srv, tool.name) is tool.fn, tool.name


def test_the_reason_reaches_the_client_through_the_mcp_layer(reaper):
    reaper.response = {"ok": False}
    content = run(srv.mcp.call_tool("delete_region", {"region_index": 3}))
    assert json.loads(content[0].text) == {"ok": False, "error": "No region numbered 3"}


def test_an_edit_still_sends_its_undo_label_inside_the_reason_wrapper(monkeypatch):
    seen = []

    async def fake(func, *args, timeout=None):
        seen.append(srv.undo_label.get())
        return {"ok": False}

    monkeypatch.setattr(srv, "reaper_call", fake)
    assert run(srv.delete_marker(7))["error"] == "No marker numbered 7"
    assert seen == ["MCP: delete marker"]
