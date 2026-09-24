"""Beats and tempo in the bridge, under a project whose tempo changes.

Runs the whole real ``reaper_mcp_bridge.lua`` under lupa. The stub project runs 140 BPM
until 8 QN, then 200 BPM, and ``Master_GetTempo`` answers 200, the tempo at a cursor parked
after the change. That is the project where beats converted at ``Master_GetTempo`` landed
about 30% early.
"""
import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
inserted = {}
markers_set = {}
PPQ = 960
CHANGE_QN = 8
function qn_to_time(qn)
    if qn <= CHANGE_QN then return qn * 60 / 140 end
    return CHANGE_QN * 60 / 140 + (qn - CHANGE_QN) * 60 / 200
end
function time_to_qn(t)
    local change_t = CHANGE_QN * 60 / 140
    if t <= change_t then return t * 140 / 60 end
    return CHANGE_QN + (t - change_t) * 200 / 60
end
ITEM_POS = qn_to_time(4)
local track, item, take = {}, {}, {}
reaper = {
    GetResourcePath = function() return RESOURCE end,
    RecursiveCreateDirectory = function() return 1 end,
    ShowConsoleMsg = function() end,
    defer = function() end,
    EnumerateFiles = function(dir, i) return list_dir(dir, i) end,
    Undo_BeginBlock = function() end,
    Undo_EndBlock = function() end,
    UpdateTimeline = function() end,
    Master_GetTempo = function() return 200 end,
    GetTrack = function(_, i) if i == 0 then return track end end,
    GetTrackMediaItem = function(_, i) if i == 0 then return item end end,
    GetActiveTake = function() return take end,
    TakeIsMIDI = function() return true end,
    GetMediaItemTake_Item = function() return item end,
    GetMediaItemInfo_Value = function(_, key) if key == "D_POSITION" then return ITEM_POS end end,
    MIDI_GetPPQPosFromProjTime = function(_, t) return (time_to_qn(t) - 4) * PPQ end,
    MIDI_GetProjQNFromPPQPos = function(_, ppq) return 4 + ppq / PPQ end,
    MIDI_GetPPQPosFromProjQN = function(_, qn) return (qn - 4) * PPQ end,
    MIDI_InsertNote = function(_, sel, mute, s, e, chan, pitch, vel)
        inserted[#inserted + 1] = {s = s, e = e, chan = chan, pitch = pitch, vel = vel}
        return true
    end,
    MIDI_Sort = function() end,
    TimeMap_GetTimeSigAtTime = function(_, t)
        if t < qn_to_time(CHANGE_QN) then return 4, 4, 140 end
        return 4, 4, 200
    end,
    CountTempoTimeSigMarkers = function() return 2 end,
    GetTempoTimeSigMarker = function(_, i)
        if i == 0 then return true, 0, 0, 0, 140, 4, 4, false end
        return true, qn_to_time(CHANGE_QN), 2, 0, 200, 4, 4, false
    end,
    SetTempoTimeSigMarker = function(_, idx, t, m, b, bpm, num, den, lin)
        markers_set[#markers_set + 1] = {t = t, bpm = bpm, num = num, den = den}
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

    def send(func, *args):
        (requests / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = requests / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    def rows(name):
        table = lua.globals()[name]
        return [dict(table[i]) for i in range(1, len(table) + 1)]

    send.inserted = lambda: rows("inserted")
    send.markers_set = lambda: rows("markers_set")
    return send


def test_a_note_across_the_tempo_change_lands_on_its_beat(bridge):
    response = bridge("InsertMIDINoteBeats", 0, 0, 60, 6.0, 1.0, 90, 2)
    assert response["ok"] is True
    [note] = bridge.inserted()
    assert note["s"] == pytest.approx(6.0 * 960)
    assert note["e"] == pytest.approx(7.0 * 960)
    assert (note["pitch"], note["vel"], note["chan"]) == (60, 90, 2)


def test_a_note_at_beat_zero_lands_on_the_item_start(bridge):
    bridge("InsertMIDINoteBeats", 0, 0, 36, 0.0, 0.25, 100, 0)
    [note] = bridge.inserted()
    assert note["s"] == pytest.approx(0.0)
    assert note["e"] == pytest.approx(240.0)


def test_a_missing_take_is_reported_not_inserted(bridge):
    response = bridge("InsertMIDINoteBeats", 5, 0, 60, 0.0, 1.0, 100, 0)
    assert response["ok"] is False
    assert "Track not found" in response["error"]
    assert bridge.inserted() == []


def test_tempo_map_reports_the_start_tempo_not_the_cursor_tempo(bridge):
    response = bridge("GetTempoMap")
    assert response["ok"] is True
    assert response["ret"] == 140
    assert [(m["time"], m["bpm"]) for m in response["tempo_markers"]] == [
        (0, 140), (pytest.approx(8 * 60 / 140), 200)]


def test_time_signature_keeps_the_start_tempo(bridge):
    response = bridge("SetTimeSignature", 3, 4)
    assert response["ok"] is True
    [marker] = bridge.markers_set()
    assert marker == {"t": 0, "bpm": 140, "num": 3, "den": 4}
