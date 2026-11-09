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
tracks = {}
sources = {}
measured = {}
past_end = 0

function add_source(name, len, loud, hz)
    sources[name] = {len = len, loud = loud, hz = hz or 48000}
end

function add_track()
    tracks[#tracks + 1] = {items = {}}
    return #tracks - 1
end

function add_item(track, pos, len, src_name, offs, rate, loop, midi)
    local take = nil
    if src_name ~= nil then
        take = {midi = midi or false, src = sources[src_name],
                values = {D_STARTOFFS = offs or 0, D_PLAYRATE = rate or 1}}
    end
    local item = {takes = {take}, active = take,
                  values = {D_POSITION = pos, D_LENGTH = len, B_LOOPSRC = loop and 1 or 0}}
    local items = tracks[track + 1].items
    items[#items + 1] = item
    return #items - 1
end

add_source("blocks", 10, {{0, 2}, {2.2, 3.2}, {3.7, 4.7}, {5.7, 6.7}, {8.7, 10}})
add_source("short_gap", 10, {{0, 2}, {2.4999, 10}})
add_source("seam", 10, {{0.3, 9.8}})
add_source("tail", 10, {{0, 9.9}})
add_source("silent", 10, {})
add_source("broken", 10, {{0, 10}})
sources.broken.broken = true
add_source("zero", 0, {})
add_track()
add_item(0, 10, 10, "blocks")

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
    CountTracks = function() return #tracks end,
    GetTrack = function(_, i) return tracks[i + 1] end,
    CountTrackMediaItems = function(t) return #t.items end,
    GetTrackMediaItem = function(t, i) return t.items[i + 1] end,
    GetActiveTake = function(item) return item.active end,
    TakeIsMIDI = function(take) return take.midi end,
    GetMediaItemTake_Source = function(take) return take.src end,
    GetMediaItemInfo_Value = function(item, key) return item.values[key] or 0 end,
    GetMediaItemTakeInfo_Value = function(take, key) return take.values[key] or 0 end,
    GetMediaSourceLength = function(s) return s.len, false end,
    GetMediaSourceSampleRate = function(s) return s.hz end,
    CalculateNormalization = function(s, mode, target, a, b)
        measured[#measured + 1] = {mode, target, a, b}
        if a < 0 or a >= s.len or b > s.len + 1e-9 then
            past_end = past_end + 1
            return 1.0
        end
        if s.broken then return 0 / 0 end
        for _, l in ipairs(s.loud) do
            if l[1] < b and l[2] > a then return 0.5 end
        end
        return 4.0
    end,
}
"""


@pytest.fixture
def bridge(tmp_path):
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

    def send(func, *args):
        (mailbox / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = mailbox / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    send.lua = lua
    send.g = lua.globals()
    return send


def ranges(out):
    return [(s["start"], s["end"]) for s in out["silences"]]


def close(found, expected, tol=1e-4):
    assert len(found) == len(expected), (found, expected)
    for f, e in zip(found, expected):
        assert f[0] == pytest.approx(e[0], abs=tol) and f[1] == pytest.approx(e[1], abs=tol), (found, expected)


def item(bridge, *args):
    return bridge.lua.eval("add_item")(*args)


def test_a_plain_item_reports_its_quiet_stretches_in_project_time(bridge):
    out = bridge("FindSilence", 0, -1, -40, 0.5)
    assert out["ok"] is True, out
    close(ranges(out), [(13.2, 13.7), (14.7, 15.7), (16.7, 18.7)])
    first = out["silences"][0]
    assert first["item_index"] == 0
    assert first["length"] == pytest.approx(0.5, abs=1e-4)
    assert (first["at_item_start"], first["at_item_end"], first["beyond_source"]) == (False, False, False)
    assert out["items_scanned"] == 1
    assert out["skipped"] == []
    assert (out["threshold_db"], out["min_length_s"]) == (-40, 0.5)
    assert isinstance(out["scan_ms"], int)


def test_the_measurement_is_peak_mode_at_the_threshold(bridge):
    bridge("FindSilence", 0, -1, -37.5, 0.5)
    modes = {tuple(m.values())[:2] for m in bridge.g.measured.values()}
    assert modes == {(2, -37.5)}


def test_a_stretch_exactly_the_minimum_is_kept_and_a_shorter_one_dropped(bridge):
    close(ranges(bridge("FindSilence", 0, -1, -40, 0.2)), [(12.0, 12.2), (13.2, 13.7), (14.7, 15.7), (16.7, 18.7)])
    item(bridge, 0, 30, 10, "short_gap")
    assert ranges(bridge("FindSilence", 0, 1, -40, 0.5)) == []
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.4)), [(32.0, 32.4999)])


def test_edges_land_within_a_sample(bridge):
    out = bridge("FindSilence", 0, -1, -40, 0.5)
    for s, (a, b) in zip(out["silences"], [(13.2, 13.7), (14.7, 15.7), (16.7, 18.7)]):
        assert abs(s["start"] - a) <= 1 / 48000
        assert abs(s["end"] - b) <= 1 / 48000


def test_offset_and_play_rate_map_source_time_to_project_time(bridge):
    item(bridge, 0, 10, 4, "blocks", 1.5, 2.0)
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.5)), [(11.6, 12.1), (12.6, 13.6)])
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.1)), [(10.25, 10.35), (10.85, 11.1), (11.6, 12.1), (12.6, 13.6)])


def test_a_slow_rate_stretches_the_source(bridge):
    item(bridge, 0, 10, 20, "blocks", 0, 0.5)
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.5)), [(16.4, 17.4), (19.4, 21.4), (23.4, 27.4)])
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.4)), [(14.0, 14.4), (16.4, 17.4), (19.4, 21.4), (23.4, 27.4)])


def test_stretches_touching_the_item_edges_are_flagged(bridge):
    item(bridge, 0, 10, 4, "blocks", 3.3, 1.0)
    out = bridge("FindSilence", 0, 1, -40, 0.2)
    close(ranges(out), [(10.0, 10.4), (11.4, 12.4), (13.4, 14.0)])
    flags = [(s["at_item_start"], s["at_item_end"], s["beyond_source"]) for s in out["silences"]]
    assert flags == [(True, False, False), (False, False, False), (False, True, False)]


def test_an_item_past_its_source_reports_the_tail_without_scanning_it(bridge):
    item(bridge, 0, 10, 12, "blocks")
    out = bridge("FindSilence", 0, 1, -40, 0.5)
    close(ranges(out), [(13.2, 13.7), (14.7, 15.7), (16.7, 18.7), (20.0, 22.0)])
    tail = out["silences"][-1]
    assert (tail["at_item_start"], tail["at_item_end"], tail["beyond_source"]) == (False, True, True)
    assert out["silences"][-2]["beyond_source"] is False
    assert bridge.g.past_end == 0


def test_quiet_audio_at_the_source_end_joins_the_tail(bridge):
    item(bridge, 0, 10, 12, "tail")
    out = bridge("FindSilence", 0, 1, -40, 0.5)
    close(ranges(out), [(19.9, 22.0)])
    assert out["silences"][0]["beyond_source"] is True
    assert bridge.g.past_end == 0


def test_an_item_starting_past_its_source_is_all_tail(bridge):
    item(bridge, 0, 10, 3, "blocks", 12.0, 1.0)
    out = bridge("FindSilence", 0, 1, -40, 0.5)
    close(ranges(out), [(10.0, 13.0)])
    assert out["silences"][0]["beyond_source"] is True
    assert bridge.g.past_end == 0


def test_a_looped_item_repeats_each_stretch_and_joins_the_seam(bridge):
    item(bridge, 0, 10, 25, "seam", 0, 1.0, True)
    out = bridge("FindSilence", 0, 1, -40, 0.5)
    close(ranges(out), [(19.8, 20.3), (29.8, 30.3)])
    assert all(s["beyond_source"] is False for s in out["silences"])
    assert bridge.g.past_end == 0


def test_a_looped_item_with_an_offset_shifts_the_seam(bridge):
    item(bridge, 0, 10, 25, "seam", 3.0, 1.0, True)
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.5)), [(16.8, 17.3), (26.8, 27.3)])
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.2)), [(16.8, 17.3), (26.8, 27.3)])


def test_a_looped_item_repeats_ordinary_stretches_in_time_order(bridge):
    item(bridge, 0, 10, 25, "blocks", 0, 1.0, True)
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.5)), [
        (13.2, 13.7), (14.7, 15.7), (16.7, 18.7), (23.2, 23.7), (24.7, 25.7), (26.7, 28.7), (33.2, 33.7)])
    close(ranges(bridge("FindSilence", 0, 1, -40, 0.3)), [
        (13.2, 13.7), (14.7, 15.7), (16.7, 18.7), (23.2, 23.7), (24.7, 25.7), (26.7, 28.7), (33.2, 33.7), (34.7, 35.0)])
    assert bridge.g.past_end == 0


def test_a_silent_looped_source_is_one_stretch_over_the_whole_item(bridge):
    item(bridge, 0, 10, 25, "silent", 0, 1.0, True)
    out = bridge("FindSilence", 0, 1, -40, 0.5)
    close(ranges(out), [(10.0, 35.0)])
    assert (out["silences"][0]["at_item_start"], out["silences"][0]["at_item_end"]) == (True, True)


def test_the_whole_track_scans_every_audio_item_and_lists_the_rest(bridge):
    bridge.lua.execute("add_item(0, 30, 2, 'blocks', 0, 1, false, true); add_item(0, 40, 2, nil)")
    item(bridge, 0, 50, 10, "blocks", 3.3, 1.0)
    out = bridge("FindSilence", 0, -1, -40, 0.5)
    assert out["ok"] is True, out
    assert out["items_scanned"] == 2
    assert out["skipped"] == [{"item_index": 1, "reason": "MIDI item"}, {"item_index": 2, "reason": "empty item"}]
    assert [s["item_index"] for s in out["silences"]] == [0, 0, 0, 3, 3, 3]
    close(ranges(out)[3:], [(51.4, 52.4), (53.4, 55.4), (56.7, 60.0)])
    assert [s["beyond_source"] for s in out["silences"]] == [False, False, False, False, False, True]


def test_a_source_reaper_cannot_measure_is_skipped_with_a_reason(bridge):
    item(bridge, 0, 30, 10, "broken")
    item(bridge, 0, 50, 10, "zero")
    out = bridge("FindSilence", 0, -1, -40, 0.5)
    assert out["items_scanned"] == 1
    assert out["skipped"] == [{"item_index": 1, "reason": "REAPER could not measure this source"},
                              {"item_index": 2, "reason": "REAPER could not measure this source"}]


def test_a_track_without_items_answers_an_empty_list(bridge):
    bridge.lua.execute("add_track()")
    out = bridge("FindSilence", 1, -1, -40, 0.5)
    assert out == {"ok": True, "items_scanned": 0, "skipped": [], "silences": [],
                   "threshold_db": -40, "min_length_s": 0.5, "scan_ms": out["scan_ms"], "id": "x"}


@pytest.mark.parametrize("args, error", [
    ((9, -1, -40, 0.5), "Track not found at index 9"),
    ((-1, -1, -40, 0.5), "Track not found at index -1"),
    ((0, 5, -40, 0.5), "Media item not found at index 5 on track 0"),
    ((0, -1, "loud", 0.5), "threshold_db must be a number of dBFS (got loud)"),
    ((0, -1, -40, 0.01), "min_length_s must be at least 0.05 seconds (got 0.01)"),
    ((0, -1, -40, "long"), "min_length_s must be at least 0.05 seconds (got long)"),
])
def test_find_silence_refuses_without_measuring(bridge, args, error):
    out = bridge("FindSilence", *args)
    assert out["ok"] is False
    assert out["error"] == error
    assert len(bridge.g.measured) == 0
