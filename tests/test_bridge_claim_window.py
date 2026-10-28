import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
ext_state = {}
clock = 1000
reaper = {
    GetResourcePath = function() return RESOURCE end,
    RecursiveCreateDirectory = function() return 1 end,
    ShowConsoleMsg = function() end,
    defer = function() end,
    GetExtState = function(section, key) return (ext_state[section .. "/" .. key]) or "" end,
    SetExtState = function(section, key, value, persist) ext_state[section .. "/" .. key] = value end,
    DeleteExtState = function(section, key, persist) ext_state[section .. "/" .. key] = nil end,
    time_precise = function() clock = clock + 0.01; return clock end,
    atexit = function(fn) end,
    EnumerateFiles = function(dir, i) return list_dir(dir, i) end,
    Undo_BeginBlock = function() end,
    Undo_EndBlock = function(label, flags) end,
    CountTracks = function() return 2 end,
}
"""


@pytest.fixture
def mailbox(tmp_path):
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    folder = tmp_path / "Scripts" / "mcp_bridge_data"
    folder.mkdir(parents=True)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)

    def list_dir(directory, index):
        if index < 0:
            return None
        names = sorted(os.listdir(folder))
        return names[index] if index < len(names) else None

    lua.globals().list_dir = list_dir
    lua.globals().RESOURCE = str(tmp_path).replace("\\", "/")
    lua.execute(STUB)
    lua.execute(BRIDGE.read_text(encoding="utf-8"))
    lua.globals().main()
    for name in os.listdir(folder):
        (folder / name).unlink()

    class Box:
        request = folder / "request_1.json"
        response = folder / "response_1.json"

        @staticmethod
        def tick():
            lua.globals().main()

        @classmethod
        def answer(cls):
            return json.loads(cls.response.read_text(encoding="utf-8"))

    return Box


@pytest.mark.parametrize("content", [b"", b"   ", b"\n", b" \r\n\t"])
def test_a_request_read_empty_is_left_for_the_server_to_finish(mailbox, content):
    mailbox.request.write_bytes(content)
    for _ in range(3):
        mailbox.tick()
        assert mailbox.request.exists()
        assert mailbox.request.read_bytes() == content
        assert not mailbox.response.exists()


def test_the_finished_request_is_answered_on_a_later_tick(mailbox):
    mailbox.request.write_bytes(b"")
    mailbox.tick()
    assert mailbox.request.exists()
    mailbox.request.write_text(
        json.dumps({"func": "CountTracks", "args": [0], "id": "abc123"}), encoding="utf-8"
    )
    mailbox.tick()
    assert mailbox.answer() == {"ok": True, "ret": 2, "id": "abc123"}
    assert not mailbox.request.exists()


def test_an_answered_request_is_removed(mailbox):
    mailbox.request.write_text(
        json.dumps({"func": "CountTracks", "args": [0], "id": "abc123"}), encoding="utf-8"
    )
    mailbox.tick()
    assert mailbox.answer()["id"] == "abc123"
    assert not mailbox.request.exists()


def test_a_malformed_request_is_answered_and_removed(mailbox):
    mailbox.request.write_bytes(b"{not json")
    mailbox.tick()
    answer = mailbox.answer()
    assert answer["ok"] is False
    assert "Malformed request JSON" in answer["error"]
    assert not mailbox.request.exists()


def test_a_request_that_fails_inside_the_bridge_is_answered_and_removed(mailbox):
    mailbox.request.write_text(json.dumps({"calls": [5], "id": "abc123"}), encoding="utf-8")
    mailbox.tick()
    answer = mailbox.answer()
    assert answer["ok"] is False
    assert answer["error"].startswith("Bridge error:")
    assert answer["id"] == "abc123"
    assert not mailbox.request.exists()
