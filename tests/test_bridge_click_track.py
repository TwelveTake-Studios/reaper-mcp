import asyncio
import json
import os
from pathlib import Path

import pytest

import reaper_mcp_server as srv

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
ext_state = {}
at_exit = {}
clock = 1000
cursor = 7.5
project_length = 95.0
click_works = true
actions = {}

local function new_track(name) return {name = name, selected = false, media = {}} end
master = new_track("MASTER")
tracks = {new_track("Drums"), new_track("Bass")}
tracks[2].selected = true
last_touched = tracks[1]
local function new_item(track, pos, len, selected)
    local it = {track = track, pos = pos, len = len, selected = selected, source = "WAVE"}
    track.media[#track.media + 1] = it
    return it
end
new_item(tracks[1], 0, 30, true)
new_item(tracks[2], 10, 20, false)

local function all_items()
    local out = {}
    for _, t in ipairs(tracks) do for _, it in ipairs(t.media) do out[#out + 1] = it end end
    return out
end

local function index_of(t)
    for i, tr in ipairs(tracks) do if tr == t then return i end end
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
    Undo_BeginBlock = function() end,
    Undo_EndBlock = function() end,
    PreventUIRefresh = function() end,
    UpdateArrange = function() end,
    GetProjectLength = function() return project_length end,
    CountTracks = function() return #tracks end,
    GetTrack = function(_, i) return tracks[i + 1] end,
    GetMasterTrack = function() return master end,
    InsertTrackAtIndex = function(i) table.insert(tracks, i + 1, new_track("")) end,
    DeleteTrack = function(t) table.remove(tracks, index_of(t)) end,
    GetSetMediaTrackInfo_String = function(t, key, value, set)
        if key == "P_NAME" and set then t.name = value end
        return true, t.name
    end,
    IsTrackSelected = function(t) return t.selected end,
    SetTrackSelected = function(t, s) t.selected = s end,
    GetLastTouchedTrack = function() return last_touched end,
    GetCursorPosition = function() return cursor end,
    SetEditCurPos = function(t) cursor = t end,
    Main_OnCommand = function(cmd)
        actions[#actions + 1] = cmd
        if cmd == 40914 then
            for _, t in ipairs(tracks) do if t.selected then last_touched = t; return end end
        elseif cmd == 40013 then
            for _, it in ipairs(all_items()) do it.selected = false end
            local it = new_item(last_touched, math.floor(cursor), 10, true)
            it.source = click_works and "CLICK" or "WAVE"
            cursor = cursor + 10
        end
    end,
    CountMediaItems = function() return #all_items() end,
    GetMediaItem = function(_, i) return all_items()[i + 1] end,
    IsMediaItemSelected = function(it) return it.selected end,
    SetMediaItemSelected = function(it, s) it.selected = s end,
    CountTrackMediaItems = function(t) return #t.media end,
    GetTrackMediaItem = function(t, i) return t.media[i + 1] end,
    GetActiveTake = function(it) return {item = it} end,
    GetMediaItemTake_Source = function(take) return {item = take.item} end,
    GetMediaSourceType = function(src) return src.item.source end,
    SetMediaItemInfo_Value = function(it, key, v)
        if key == "D_POSITION" then it.pos = v elseif key == "D_LENGTH" then it.len = v end
    end,
}
"""


@pytest.fixture
def bridge(tmp_path, monkeypatch):
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

    async def reaper_call(func, *args, timeout=None):
        (mailbox / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = mailbox / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    monkeypatch.setattr(srv, "reaper_call", reaper_call)
    return lua.globals()


def run(coro):
    return asyncio.run(coro)


def names(g):
    return [g.tracks[i].name for i in range(1, len(g.tracks) + 1)]


def click_item(g):
    track = g.tracks[len(g.tracks)]
    return track.media[1]


def test_a_click_track_covers_the_project_on_a_new_last_track(bridge):
    out = run(srv.create_click_track())
    assert out["ok"] is True, out
    assert names(bridge) == ["Drums", "Bass", "Click"]
    assert out["track_index"] == 2 and out["item_index"] == 0
    assert (out["start"], out["end"]) == (0, 95.0)
    item = click_item(bridge)
    assert (item.pos, item.len, item.source) == (0, 95.0, "CLICK")


def test_start_end_and_name_set_the_item_span_and_track_name(bridge):
    out = run(srv.create_click_track(4.0, 60.0, "Metronome"))
    assert out["ok"] is True, out
    assert names(bridge)[-1] == "Metronome"
    item = click_item(bridge)
    assert (item.pos, item.len) == (4.0, 56.0)


def test_the_item_starts_at_start_even_when_reaper_snaps_the_insert(bridge):
    out = run(srv.create_click_track(4.5, 60.0))
    assert out["ok"] is True, out
    item = click_item(bridge)
    assert (item.pos, item.len) == (4.5, 55.5)


def test_cursor_selection_and_last_touched_track_are_put_back(bridge):
    run(srv.create_click_track(4.0, 60.0))
    assert bridge.cursor == 7.5
    assert [bridge.tracks[i].selected for i in range(1, 4)] == [False, True, False]
    assert bridge.last_touched.name == "Drums"
    assert bridge.tracks[1].media[1].selected is True
    assert bridge.tracks[2].media[1].selected is False
    assert click_item(bridge).selected is False


def test_an_empty_project_without_end_is_refused_and_adds_nothing(bridge):
    bridge.project_length = 0
    out = run(srv.create_click_track())
    assert out["ok"] is False
    assert "pass end" in out["error"]
    assert names(bridge) == ["Drums", "Bass"]


def test_end_before_start_is_refused_and_adds_nothing(bridge):
    out = run(srv.create_click_track(30.0, 10.0))
    assert out["ok"] is False
    assert out["error"] == "end must be after start"
    assert names(bridge) == ["Drums", "Bass"]


def test_a_failed_click_source_removes_the_new_track_and_restores_state(bridge):
    bridge.click_works = False
    out = run(srv.create_click_track(4.0, 60.0))
    assert out["ok"] is False
    assert names(bridge) == ["Drums", "Bass"]
    assert bridge.cursor == 7.5
    assert bridge.tracks[1].media[1].selected is True


def test_an_empty_name_falls_back_to_click(bridge):
    out = run(srv.create_click_track(0.0, 10.0, ""))
    assert out["ok"] is True, out
    assert names(bridge)[-1] == "Click"
