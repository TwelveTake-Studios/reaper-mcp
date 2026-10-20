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
markers = {[1] = true}
regions = {[2] = true}
tracks = {{sends = 1}, {sends = 0}}

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
    GetTrack = function(_, i) return tracks[i + 1] end,
    DeleteProjectMarker = function(_, number, is_region)
        local set = is_region and regions or markers
        if not set[number] then return false end
        set[number] = nil
        return true
    end,
    TrackFX_SetEQBandEnabled = function() return false end,
    RemoveTrackSend = function(track, category, index)
        if category ~= 0 or index < 0 or index >= track.sends then return false end
        track.sends = track.sends - 1
        return true
    end,
}
"""


@pytest.fixture
def bridge(tmp_path, monkeypatch):
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

    async def reaper_call(func, *args, timeout=None):
        (requests / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = requests / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    monkeypatch.setattr(srv, "reaper_call", reaper_call)
    return lua.globals()


def run(coro):
    return asyncio.run(coro)


def test_deleting_a_marker_that_does_not_exist_names_it(bridge):
    assert run(srv.delete_marker(7)) == {"ok": False, "error": "No marker numbered 7", "id": "x"}


def test_deleting_a_region_that_does_not_exist_names_it(bridge):
    assert run(srv.delete_region(9)) == {"ok": False, "error": "No region numbered 9", "id": "x"}


def test_a_marker_number_is_not_a_region_number(bridge):
    assert run(srv.delete_region(1))["error"] == "No region numbered 1"
    assert bridge.markers[1] is True


def test_deleting_a_send_that_does_not_exist_names_it(bridge):
    assert run(srv.delete_send(1, 0)) == {"ok": False, "ret": False, "error": "Track 1 has no send with index 0",
                                          "id": "x"}


def test_a_missing_track_keeps_the_bridges_message(bridge):
    assert run(srv.delete_send(5, 0))["error"] == "Track not found"


def test_existing_targets_are_still_deleted(bridge):
    assert run(srv.delete_marker(1))["ok"] is True
    assert run(srv.delete_region(2))["ok"] is True
    assert run(srv.delete_send(0, 0))["ok"] is True
    assert bridge.markers[1] is None
    assert bridge.regions[2] is None
    assert bridge.tracks[1].sends == 0


def test_save_fx_preset_always_fails_with_a_reason(bridge):
    out = run(srv.save_fx_preset(0, 0, "Lead"))
    assert out["ok"] is False
    assert out["error"].startswith("Not supported")


def test_a_silent_bridge_failure_gets_a_reason(bridge):
    assert run(srv.set_eq_band_enabled(0, 0, 2, 1, False)) == {
        "ok": False, "ret": False, "id": "x",
        "error": "set_eq_band_enabled did not succeed; REAPER reported no reason",
    }
