"""Undo blocks and batched calls in the bridge's request handler.

Runs the whole real ``reaper_mcp_bridge.lua`` under lupa against a stub ``reaper`` table,
writes request files into a temp directory, and drives one poll with ``main()``.
"""
import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
undo_log = {}
written = {}
reaper = {
    GetResourcePath = function() return RESOURCE end,
    RecursiveCreateDirectory = function() return 1 end,
    ShowConsoleMsg = function() end,
    defer = function() end,
    EnumerateFiles = function(dir, i) return list_dir(dir, i) end,
    Undo_BeginBlock = function() undo_log[#undo_log + 1] = "begin" end,
    Undo_EndBlock = function(label, flags)
        undo_log[#undo_log + 1] = "end:" .. tostring(label) .. ":" .. tostring(flags)
    end,
    CountTracks = function() return 2 end,
    InsertTrackAtIndex = function(idx, defaults)
        if idx == 99 then error("boom") end
        written[#written + 1] = "insert:" .. tostring(idx)
    end,
    StubWrite = function(tag)
        written[#written + 1] = "write:" .. tostring(tag)
        return true
    end,
}
"""


@pytest.fixture
def bridge(tmp_path):
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    requests = tmp_path / "Scripts" / "mcp_bridge_data"
    requests.mkdir(parents=True)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)

    def list_dir(directory, index):
        if index < 0:
            return None
        names = sorted(os.listdir(requests))
        return names[index] if index < len(names) else None

    lua.globals().list_dir = list_dir
    lua.globals().RESOURCE = str(tmp_path).replace("\\", "/")
    lua.execute(STUB)
    lua.execute(BRIDGE.read_text(encoding="utf-8"))

    def send(request):
        (requests / "request_1.json").write_text(json.dumps(request), encoding="utf-8")
        lua.globals().main()
        answer = requests / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    def log(name):
        table = lua.globals()[name]
        return [table[i] for i in range(1, len(table) + 1)]

    send.undo_log = lambda: log("undo_log")
    send.written = lambda: log("written")
    return send


def test_a_labelled_request_is_one_named_undo_block(bridge):
    response = bridge({"func": "StubWrite", "args": ["a"], "id": "x", "undo": "MCP: set thing"})
    assert response["ok"] is True
    assert bridge.undo_log() == ["begin", "end:MCP: set thing:-1"]


def test_an_unlabelled_request_opens_no_block(bridge):
    response = bridge({"func": "CountTracks", "args": [0], "id": "x"})
    assert response["ok"] is True
    assert bridge.undo_log() == []


def test_a_batch_runs_every_call_inside_one_block(bridge):
    response = bridge({
        "calls": [
            {"func": "InsertTrackAtIndex", "args": [2, True]},
            {"func": "StubWrite", "args": ["name"]},
        ],
        "id": "x",
        "undo": "MCP: insert track",
    })
    assert response["ok"] is True
    assert len(response["results"]) == 2
    assert all(r["ok"] for r in response["results"])
    assert bridge.written() == ["insert:2", "write:name"]
    assert bridge.undo_log() == ["begin", "end:MCP: insert track:-1"]


def test_a_batch_stops_at_the_first_failed_call(bridge):
    response = bridge({
        "calls": [
            {"func": "StubWrite", "args": ["first"]},
            {"func": "NoSuchFunction", "args": []},
            {"func": "StubWrite", "args": ["never"]},
        ],
        "id": "x",
        "undo": "MCP: create bus",
    })
    assert response["ok"] is False
    assert response["failed_at"] == 1
    assert "NoSuchFunction" in response["error"]
    assert len(response["results"]) == 2
    assert bridge.written() == ["write:first"]
    assert bridge.undo_log() == ["begin", "end:MCP: create bus:-1"]


def test_a_handler_that_raises_still_closes_its_block(bridge):
    response = bridge({"func": "InsertTrackAtIndex", "args": [99, True], "id": "x",
                       "undo": "MCP: insert track"})
    assert response["ok"] is False
    assert "boom" in response["error"]
    assert bridge.undo_log() == ["begin", "end:MCP: insert track:-1"]


def test_the_next_request_after_a_raise_is_not_inside_a_stale_block(bridge):
    bridge({"func": "InsertTrackAtIndex", "args": [99, True], "id": "x", "undo": "MCP: a"})
    bridge({"func": "CountTracks", "args": [0], "id": "y"})
    assert bridge.undo_log() == ["begin", "end:MCP: a:-1"]


def test_an_empty_label_opens_no_block(bridge):
    bridge({"func": "StubWrite", "args": ["a"], "id": "x", "undo": ""})
    assert bridge.undo_log() == []
