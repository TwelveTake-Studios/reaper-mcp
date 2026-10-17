import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
ext_state = {}
at_exit = {}
clock = 1000
track = {media = {}}
local function new_item(name, selected)
    local it = {take = name and {name = name} or nil, selected = selected}
    track.media[#track.media + 1] = it
    return it
end
new_item("Vocal take 3", true)
new_item(nil, true)

local function selected_items()
    local out = {}
    for _, it in ipairs(track.media) do if it.selected then out[#out + 1] = it end end
    return out
end

reaper = {
    GetResourcePath = function() return RESOURCE end,
    RecursiveCreateDirectory = function() return 1 end,
    ShowConsoleMsg = function() end,
    defer = function() end,
    GetExtState = function(section, key) return ext_state[section .. "/" .. key] or "" end,
    SetExtState = function(section, key, value) ext_state[section .. "/" .. key] = value end,
    DeleteExtState = function(section, key) ext_state[section .. "/" .. key] = nil end,
    time_precise = function() clock = clock + 0.01; return clock end,
    atexit = function(fn) at_exit[#at_exit + 1] = fn end,
    EnumerateFiles = function(dir, i) return list_dir(dir, i) end,
    CountTracks = function() return 1 end,
    GetTrack = function(_, i) if i == 0 then return track end end,
    CountTrackMediaItems = function(t) return #t.media end,
    GetTrackMediaItem = function(t, i) return t.media[i + 1] end,
    CountSelectedMediaItems = function() return #selected_items() end,
    GetSelectedMediaItem = function(_, i) return selected_items()[i + 1] end,
    GetMediaItem_Track = function() return track end,
    GetActiveTake = function(it) return it.take end,
    TakeIsMIDI = function() return false end,
    GetTakeName = function(take) return take.name end,
    GetMediaItemInfo_Value = function() return 0 end,
}
"""


@pytest.fixture
def send(tmp_path):
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    mailbox = tmp_path / "Scripts" / "mcp_bridge_data"
    mailbox.mkdir(parents=True)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)

    def list_dir(directory, index):
        if index < 0:
            return None
        names = sorted(os.listdir(mailbox))
        return names[index] if index < len(names) else None

    lua.globals().list_dir = list_dir
    lua.globals().RESOURCE = str(tmp_path).replace("\\", "/")
    lua.execute(STUB)
    lua.execute(BRIDGE.read_text(encoding="utf-8"))

    def call(func, *args):
        (mailbox / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = mailbox / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    return call


@pytest.mark.parametrize("func, args", [("GetTrackItems", [0]), ("GetSelectedItems", []), ("GetAllItems", [])])
def test_item_readers_report_the_take_name(send, func, args):
    out = send(func, *args)
    assert out["ok"] is True, out
    assert [item["name"] for item in out["items"]] == ["Vocal take 3", ""]
