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
log = {}
tracks = {}
master = {name = "MASTER", values = {I_TCPH = 0}, selected = false, items = {}}
master_flags = 0
play_rate = 1.0
reorder_refuses = false
adjusted = 0
dirty = {}

local function new_track(name)
    local t = {name = name, selected = false, items = {},
               values = {B_SHOWINTCP = 1, B_SHOWINMIXER = 1, I_HEIGHTOVERRIDE = 0, I_TCPH = 60}}
    tracks[#tracks + 1] = t
    return t
end
for _, name in ipairs({"A", "B", "C", "D"}) do new_track(name) end

local take1 = {name = "Take 1", number = 0}
local take2 = {name = "Take 2", number = 1}
tracks[1].items = {{takes = {take1, take2}, active = take2}}
tracks[2].items = {{takes = {}, active = nil}}

markers = {
    {num = 1, isrgn = false, pos = 10, rgnend = 0, name = "Verse", color = 111},
    {num = 1, isrgn = true, pos = 20, rgnend = 30, name = "Intro", color = 222},
    {num = 2, isrgn = false, pos = 40, rgnend = 0, name = "Bridge", color = 333},
}

local function index_of(t)
    for i, x in ipairs(tracks) do if x == t then return i - 1 end end
    return -1
end

local function selected_list(wantmaster)
    local out = {}
    if wantmaster and master.selected then out[#out + 1] = master end
    for _, t in ipairs(tracks) do if t.selected then out[#out + 1] = t end end
    return out
end

function order()
    local names = {}
    for _, t in ipairs(tracks) do names[#names + 1] = t.name end
    return table.concat(names, ",")
end

function selection()
    local names = {}
    for _, t in ipairs(selected_list(true)) do names[#names + 1] = t.name end
    return table.concat(names, ",")
end

function count_log(name)
    local n = 0
    for _, entry in ipairs(log) do if entry[1] == name then n = n + 1 end end
    return n
end

function last_log(name)
    for i = #log, 1, -1 do if log[i][1] == name then return log[i] end end
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
    CountTracks = function() return #tracks end,
    GetTrack = function(_, i) return tracks[i + 1] end,
    GetMasterTrack = function() return master end,
    CountSelectedTracks2 = function(_, wantmaster) return #selected_list(wantmaster) end,
    GetSelectedTrack2 = function(_, i, wantmaster) return selected_list(wantmaster)[i + 1] end,
    SetTrackSelected = function(t, selected) t.selected = selected end,
    ValidatePtr2 = function(_, p) return p == master or index_of(p) >= 0 end,
    ReorderSelectedTracks = function(before, mode)
        log[#log + 1] = {"ReorderSelectedTracks", before, mode}
        if reorder_refuses then return false end
        local moving, rest, anchor = {}, {}, nil
        for i, t in ipairs(tracks) do
            if t.selected then moving[#moving + 1] = t else rest[#rest + 1] = t end
            if i - 1 >= before and not t.selected and not anchor then anchor = t end
        end
        local out = {}
        for _, t in ipairs(rest) do
            if t == anchor then for _, m in ipairs(moving) do out[#out + 1] = m end end
            out[#out + 1] = t
        end
        if not anchor then for _, m in ipairs(moving) do out[#out + 1] = m end end
        tracks = out
        return true
    end,
    TrackList_AdjustWindows = function() adjusted = adjusted + 1 end,
    UpdateArrange = function() end,
    GetMediaTrackInfo_Value = function(t, key)
        if key == "IP_TRACKNUMBER" then return t == master and -1 or index_of(t) + 1 end
        return t.values[key] or 0
    end,
    SetMediaTrackInfo_Value = function(t, key, value)
        log[#log + 1] = {"SetMediaTrackInfo_Value", t.name, key, value}
        t.values[key] = value
        return true
    end,
    GetMasterTrackVisibility = function() return master_flags end,
    SetMasterTrackVisibility = function(flags)
        local old = master_flags
        master_flags = flags
        return old
    end,
    GetTrackName = function(t) return true, t.name end,
    GetSetMediaTrackInfo_String = function(t, key) return true, key == "GUID" and ("{" .. t.name .. "}") or "" end,
    CountTrackMediaItems = function(t) return #t.items end,
    GetTrackMediaItem = function(t, i) return t.items[i + 1] end,
    GetActiveTake = function(item) return item.active end,
    TakeIsMIDI = function() return false end,
    GetTake = function(item, i) return item.takes[i + 1] end,
    GetSetMediaItemTakeInfo_String = function(take, key, value, set)
        if set then take.name = value end
        return true, take.name
    end,
    GetMediaItemTakeInfo_Value = function(take, key) return key == "IP_TAKENUMBER" and take.number or 0 end,
    GetTakeName = function(take) return take.name end,
    TrackFX_GetCount = function() return 0 end,
    TrackFX_GetFXName = function() return true, "" end,
    EnumProjectMarkers = function(i)
        local m = markers[i + 1]
        if not m then return 0 end
        return i + 1, m.isrgn, m.pos, m.rgnend, m.name, m.num
    end,
    SetProjectMarker4 = function(_, num, isrgn, pos, rgnend, name, color, flags)
        log[#log + 1] = {"SetProjectMarker4", num, isrgn, pos, rgnend, name, color, flags}
        for _, m in ipairs(markers) do
            if m.num == num and m.isrgn == isrgn then
                m.pos, m.rgnend = pos, rgnend
                if flags & 1 ~= 0 then m.name = "" elseif name ~= "" then m.name = name end
                if color ~= 0 then m.color = color end
            end
        end
        return true
    end,
    Master_GetPlayRate = function() return play_rate end,
    CSurf_OnPlayRateChange = function(rate) log[#log + 1] = {"CSurf_OnPlayRateChange", rate}; play_rate = rate end,
    CountProjectMarkers = function() return #markers, 2, 1 end,
    EnumProjects = function() return nil, "/songs/demo.rpp" end,
    GetProjectLength = function() return 60 end,
    GetProjectTimeSignature2 = function() return 120, 4 end,
    CreateNewMIDIItemInProj = function(t)
        local item = {takes = {}, active = nil}
        t.items[#t.items + 1] = item
        return item
    end,
    MarkTrackItemsDirty = function(t, item) dirty[#dirty + 1] = {track = t, item = item} end,
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


def order(bridge):
    return bridge.g.order()


def selection(bridge):
    return bridge.g.selection()


# --- MoveTracks ---

def test_move_tracks_moves_a_track_above_the_destination(bridge):
    out = bridge("MoveTracks", [2], 0, False)
    assert out["ok"] is True, out
    assert order(bridge) == "C,A,B,D"
    assert out["tracks"] == [{"from": 2, "to": 0}]
    assert list(bridge.g.last_log("ReorderSelectedTracks").values()) == ["ReorderSelectedTracks", 0, 0]
    assert bridge.g.adjusted == 1


def test_move_tracks_reports_each_listed_track_in_the_order_given(bridge):
    out = bridge("MoveTracks", [3, 1], 0, False)
    assert out["ok"] is True, out
    assert order(bridge) == "B,D,A,C"
    assert out["tracks"] == [{"from": 3, "to": 1}, {"from": 1, "to": 0}]


def test_move_tracks_to_the_end(bridge):
    out = bridge("MoveTracks", [0], 4, False)
    assert out["ok"] is True, out
    assert order(bridge) == "B,C,D,A"
    assert out["tracks"] == [{"from": 0, "to": 3}]


def test_into_folder_asks_reaper_for_a_child_of_the_track_above(bridge):
    assert bridge("MoveTracks", [3], 1, True)["ok"] is True
    assert list(bridge.g.last_log("ReorderSelectedTracks").values()) == ["ReorderSelectedTracks", 1, 1]


def test_move_tracks_puts_the_selection_back(bridge):
    bridge.lua.execute("tracks[1].selected = true; master.selected = true; tracks[4].selected = true")
    assert bridge("MoveTracks", [2, 3], 0, False)["ok"] is True
    assert order(bridge) == "C,D,A,B"
    assert selection(bridge) == "MASTER,D,A"


def test_move_tracks_puts_the_selection_back_when_reaper_moves_nothing(bridge):
    bridge.lua.execute("tracks[2].selected = true; reorder_refuses = true")
    out = bridge("MoveTracks", [0], 3, False)
    assert out == {"ok": False, "error": "REAPER did not move the tracks", "id": "x"}
    assert selection(bridge) == "B"
    assert order(bridge) == "A,B,C,D"


@pytest.mark.parametrize("args, fragment", [
    (([1], 5, False), "before_index must be between 0 and 4 (got 5)"),
    (([1], -1, False), "before_index must be between 0 and 4"),
    (([1], 1.5, False), "before_index must be between 0 and 4"),
    (([], 0, False), "track_indices must list at least one track"),
    (([7], 0, False), "Track not found at index 7"),
    (([-1], 0, False), "Track not found at index -1"),
    (([0.5], 0, False), "Track not found at index 0.5"),
    (([1, 1], 0, False), "Track 1 is listed twice"),
])
def test_move_tracks_refuses_without_touching_the_project(bridge, args, fragment):
    bridge.lua.execute("tracks[3].selected = true")
    out = bridge("MoveTracks", *args)
    assert out["ok"] is False
    assert fragment in out["error"]
    assert order(bridge) == "A,B,C,D"
    assert selection(bridge) == "C"
    assert bridge.g.count_log("ReorderSelectedTracks") == 0


# --- SetTrackDisplay ---

def values(bridge, n):
    return dict(bridge.lua.eval(f"tracks[{n + 1}].values").items())


def test_hiding_in_the_arrange_view_touches_nothing_else(bridge):
    out = bridge("SetTrackDisplay", [1], 0, -1, -1)
    assert out["ok"] is True, out
    assert values(bridge, 1) == {"B_SHOWINTCP": 0, "B_SHOWINMIXER": 1, "I_HEIGHTOVERRIDE": 0, "I_TCPH": 60}
    assert out["tracks"] == [{"index": 1, "hidden_in": ["arrange"]}]
    assert bridge.g.adjusted == 1


def test_showing_again_drops_hidden_in(bridge):
    bridge.lua.execute("tracks[1].values.B_SHOWINMIXER = 0")
    out = bridge("SetTrackDisplay", [0], -1, 1, -1)
    assert out["tracks"] == [{"index": 0}]
    assert values(bridge, 0)["B_SHOWINMIXER"] == 1


def test_height_zero_is_written_as_the_reset(bridge):
    bridge.lua.execute("tracks[3].values.I_HEIGHTOVERRIDE = 140")
    assert bridge("SetTrackDisplay", [2, 3], -1, -1, 0)["ok"] is True
    assert values(bridge, 2)["I_HEIGHTOVERRIDE"] == 0
    assert values(bridge, 3)["I_HEIGHTOVERRIDE"] == 0
    assert bridge.g.count_log("SetMediaTrackInfo_Value") == 2


def test_a_height_is_written_as_given(bridge):
    out = bridge("SetTrackDisplay", [0], -1, -1, 1)
    assert out["tracks"] == [{"index": 0}]
    assert values(bridge, 0) == {"B_SHOWINTCP": 1, "B_SHOWINMIXER": 1, "I_HEIGHTOVERRIDE": 1, "I_TCPH": 60}


def test_a_bad_track_later_in_the_list_changes_nothing(bridge):
    out = bridge("SetTrackDisplay", [0, 9], 0, 0, 80)
    assert out["ok"] is False
    assert out["error"] == "Track not found at index 9"
    assert bridge.g.count_log("SetMediaTrackInfo_Value") == 0
    assert bridge.g.adjusted == 0


@pytest.mark.parametrize("flags, arrange, mixer, expected_flags, hidden_in", [
    (0, 1, -1, 1, None),
    (1, -1, 0, 3, ["mixer"]),
    (3, -1, 1, 1, None),
    (1, 0, -1, 0, ["arrange"]),
    (2, 1, 1, 1, None),
    (0, 0, 0, 2, ["arrange", "mixer"]),
])
def test_the_master_uses_its_visibility_flags(bridge, flags, arrange, mixer, expected_flags, hidden_in):
    bridge.lua.execute(f"master_flags = {flags}")
    out = bridge("SetTrackDisplay", [-1], arrange, mixer, -1)
    assert out["ok"] is True, out
    assert bridge.g.master_flags == expected_flags
    expected = {"index": -1}
    if hidden_in:
        expected["hidden_in"] = hidden_in
    assert out["tracks"] == [expected]
    assert bridge.g.count_log("SetMediaTrackInfo_Value") == 0


def test_master_height_alone_leaves_its_visibility(bridge):
    bridge.lua.execute("master_flags = 2")
    assert bridge("SetTrackDisplay", [-1], -1, -1, 50)["ok"] is True
    assert bridge.g.master_flags == 2
    assert dict(bridge.lua.eval("master.values").items())["I_HEIGHTOVERRIDE"] == 50


@pytest.mark.parametrize("args, fragment", [
    (([0], -1, -1, -1), "Nothing to change"),
    (([0], 2, -1, -1), "must be -1 (unchanged), 0 or 1 (got 2)"),
    (([0], -1, True, -1), "must be -1 (unchanged), 0 or 1"),
    (([0], -1, -1, -2), "height must be a whole number of pixels"),
    (([0], -1, -1, 1.5), "height must be a whole number of pixels"),
    (([], 0, -1, -1), "track_indices must list at least one track"),
    (([0, 0], 0, -1, -1), "Track 0 is listed twice"),
])
def test_set_track_display_refuses_without_changes(bridge, args, fragment):
    out = bridge("SetTrackDisplay", *args)
    assert out["ok"] is False
    assert fragment in out["error"]
    assert bridge.g.count_log("SetMediaTrackInfo_Value") == 0


# --- hidden_in on track reads ---

@pytest.mark.parametrize("setup, hidden_in", [
    ("", None),
    ("tracks[1].values.B_SHOWINTCP = 0", ["arrange"]),
    ("tracks[1].values.B_SHOWINMIXER = 0", ["mixer"]),
    ("tracks[1].values.B_SHOWINTCP = 0; tracks[1].values.B_SHOWINMIXER = 0", ["arrange", "mixer"]),
])
def test_get_track_info_reports_hidden_in_only_when_hidden(bridge, setup, hidden_in):
    bridge.lua.execute(setup)
    info = bridge("GetTrackInfo", 0)["info"]
    assert info.get("hidden_in") == hidden_in
    assert ("hidden_in" in info) is (hidden_in is not None)


@pytest.mark.parametrize("flags, hidden_in", [(0, ["arrange"]), (1, None), (3, ["mixer"]), (2, ["arrange", "mixer"])])
def test_the_master_reports_hidden_in_from_its_flags(bridge, flags, hidden_in):
    bridge.lua.execute(f"master_flags = {flags}")
    assert bridge("GetTrackInfo", -1)["info"].get("hidden_in") == hidden_in


def test_get_all_tracks_carries_hidden_in(bridge):
    bridge.lua.execute("tracks[3].values.B_SHOWINMIXER = 0")
    tracks = bridge("GetAllTracksInfo")["tracks"]
    assert [t.get("hidden_in") for t in tracks] == [None, None, ["mixer"], None]


def test_the_project_summary_carries_hidden_in(bridge):
    bridge.lua.execute("tracks[2].values.B_SHOWINTCP = 0")
    summary = bridge("GetProjectSummary")
    assert summary["ok"] is True, summary
    assert [t.get("hidden_in") for t in summary["tracks"]] == [None, ["arrange"], None, None]


@pytest.mark.parametrize("flags, hidden_in", [(0, ["arrange"]), (1, None), (3, ["mixer"])])
def test_the_project_summary_reports_the_master_hidden_in(bridge, flags, hidden_in):
    bridge.lua.execute(f"master_flags = {flags}")
    assert bridge("GetProjectSummary")["master"].get("hidden_in") == hidden_in


# --- RenameMarker ---

def marker(bridge, n):
    return dict(bridge.lua.eval(f"markers[{n + 1}]").items())


def test_rename_marker_keeps_position_and_color(bridge):
    out = bridge("RenameMarker", 1, False, "Chorus")
    assert out == {"ok": True, "index": 1, "name": "Chorus", "id": "x"}
    assert list(bridge.g.last_log("SetProjectMarker4").values()) == [
        "SetProjectMarker4", 1, False, 10, 0, "Chorus", 0, 0]
    assert marker(bridge, 0)["color"] == 111
    assert marker(bridge, 1)["name"] == "Intro"


def test_rename_region_keeps_its_bounds_and_leaves_the_marker_with_its_number(bridge):
    out = bridge("RenameMarker", 1, True, "Outro")
    assert out["name"] == "Outro"
    region = marker(bridge, 1)
    assert (region["pos"], region["rgnend"], region["color"]) == (20, 30, 222)
    assert marker(bridge, 0)["name"] == "Verse"


def test_an_empty_name_clears_it(bridge):
    out = bridge("RenameMarker", 2, False, "")
    assert out["name"] == ""
    assert list(bridge.g.last_log("SetProjectMarker4").values())[-1] == 1
    assert marker(bridge, 2)["name"] == ""


@pytest.mark.parametrize("args, error", [
    ((9, False, "x"), "No marker numbered 9"),
    ((2, True, "x"), "No region numbered 2"),
    ((1, False, 5), "name must be text"),
])
def test_rename_marker_refuses(bridge, args, error):
    out = bridge("RenameMarker", *args)
    assert out["ok"] is False
    assert out["error"] == error
    assert bridge.g.count_log("SetProjectMarker4") == 0


# --- SetTakeName ---

def test_set_take_name_renames_the_active_take(bridge):
    out = bridge("SetTakeName", 0, 0, -1, "Lead")
    assert out == {"ok": True, "take_index": 1, "name": "Lead", "id": "x"}
    assert bridge.lua.eval("tracks[1].items[1].takes[1].name") == "Take 1"


def test_set_take_name_renames_an_explicit_take(bridge):
    out = bridge("SetTakeName", 0, 0, 0, "Comp A")
    assert out["take_index"] == 0
    assert bridge.lua.eval("tracks[1].items[1].takes[1].name") == "Comp A"
    assert bridge.lua.eval("tracks[1].items[1].takes[2].name") == "Take 2"


@pytest.mark.parametrize("args, error", [
    ((1, 0, -1, "x"), "Item 0 on track 1 has no takes"),
    ((0, 0, 5, "x"), "Take not found at index 5"),
    ((0, 3, -1, "x"), "Media item not found at index 3 on track 0"),
    ((9, 0, -1, "x"), "Track not found at index 9"),
    ((-1, 0, -1, "x"), "Track not found at index -1"),
    ((0, 0, -1, 7), "name must be text"),
])
def test_set_take_name_refuses(bridge, args, error):
    out = bridge("SetTakeName", *args)
    assert out["ok"] is False
    assert out["error"] == error
    assert bridge.lua.eval("tracks[1].items[1].takes[2].name") == "Take 2"


# --- play rate ---

def test_get_play_rate(bridge):
    bridge.lua.execute("play_rate = 0.75")
    assert bridge("GetPlayRate")["rate"] == 0.75


@pytest.mark.parametrize("rate", [0.25, 1.5, 4])
def test_set_play_rate_reads_the_rate_back(bridge, rate):
    out = bridge("SetPlayRate", rate)
    assert out == {"ok": True, "rate": rate, "id": "x"}
    assert bridge.g.play_rate == rate


@pytest.mark.parametrize("rate", [0.2, 4.5, -1, "fast"])
def test_set_play_rate_refuses_a_rate_out_of_range(bridge, rate):
    out = bridge("SetPlayRate", rate)
    assert out["ok"] is False
    assert "rate must be between 0.25 and 4" in out["error"]
    assert bridge.g.count_log("CSurf_OnPlayRateChange") == 0
    assert bridge.g.play_rate == 1.0


# --- CreateMIDIItem undo ---

def test_a_new_midi_item_is_marked_for_the_undo_history(bridge):
    out = bridge("CreateMIDIItem", 2, 0.0, 1.0)
    assert out == {"ok": True, "item_index": 0, "id": "x"}
    assert bridge.lua.eval("#dirty") == 1
    assert bridge.lua.eval("dirty[1].track == tracks[3] and dirty[1].item == tracks[3].items[1]") is True
