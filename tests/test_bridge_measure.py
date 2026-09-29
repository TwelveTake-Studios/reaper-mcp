import json
import math
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = r"""
ext_state = {}
at_exit = {}
clock = 1000
gmem = {}
calls = {}
analyzer_installed = true
analyzer_protocol = 1
stats_text = nil
play_state = 0
fail_render = false
analyzer_samples = {peak = 0.5, true_peak = 0.6, sll = 100, srr = 100, slr = 100}

local function new_track(name)
    return {name = name, selected = false, vol = 1, pan = 0, fxen = 1, fx = {}, sends = {}, items = {},
            D_PAN = 0, D_WIDTH = 1, envelopes = {}}
end
master = new_track("MASTER")
tracks = {new_track("Drums"), new_track("Bass")}
function new_item(track, pos, len)
    local it = {track = track, pos = pos, len = len, mute = 0, selected = false}
    table.insert(track.items, it)
    return it
end
items = {new_item(tracks[1], 0, 10), new_item(tracks[2], 0, 4), new_item(tracks[2], 3, 6), new_item(tracks[2], 20, 5)}
ts = {5, 7}
loop = {1, 2}
cursor = 12.5

local function all_items()
    local out = {}
    for _, t in ipairs(tracks) do for _, it in ipairs(t.items) do out[#out + 1] = it end end
    return out
end

local function render_stats(action)
    if fail_render then error("render blew up") end
    local snap = {action = action, ts = {ts[1], ts[2]}, selected = {}, muted = {}, track_count = #tracks, sends = {}}
    for i, t in ipairs(tracks) do if t.selected then snap.selected[#snap.selected + 1] = t.name end end
    for _, t in ipairs(tracks) do
        for _, sd in ipairs(t.sends) do
            snap.sends[#snap.sends + 1] = t.name .. ">" .. sd.dst.name .. ":" .. tostring(sd.I_SENDMODE) .. ":" .. tostring(sd.D_VOL)
        end
    end
    cursor = 0
    for i, it in ipairs(all_items()) do snap.muted[i] = it.mute end
    calls[#calls + 1] = snap
    local analyzer_on
    for _, t in ipairs(tracks) do
        for _, fx in ipairs(t.fx) do if fx.analyzer and t.selected then analyzer_on = true end end
    end
    for _, fx in ipairs(master.fx) do if fx.analyzer and master.fxen == 1 then analyzer_on = true end end
    if analyzer_on and (gmem[0] or 0) == 1 then
        local a = analyzer_samples
        gmem[1] = analyzer_protocol
        gmem[2] = 48000; gmem[3] = a.peak; gmem[4] = a.peak; gmem[5] = a.true_peak; gmem[6] = a.true_peak
        gmem[7] = a.sll; gmem[8] = a.srr; gmem[9] = a.slr
        gmem[12] = 3; gmem[13] = 10; gmem[14] = 48000; gmem[15] = 4096; gmem[16] = 1536
        local k = math.floor(1000 / (48000 / 4096) + 0.5)
        gmem[1024 + k] = 1e6; gmem[1024 + 2049 + k] = 1e6; gmem[1024 + 2 * 2049 + k] = 1e6
    end
    if stats_text then return stats_text end
    local peak = 20 * math.log(analyzer_samples.peak, 10)
    local one = "LENGTH:0:10.000;PEAK:" .. string.format("%.6f", peak) .. ";LUFSMMAX:-10.5;LUFSSMAX:-11.25;LUFSI:-14.125;LRA:6.4"
    local parts = {}
    for _, t in ipairs(tracks) do
        if t.selected and action ~= "42440" and action ~= "42441" then
            local body = t.name == "__twelvetake_measure__" and one:gsub("LUFSI:%-14.125", "LUFSI:-99") or one
            parts[#parts + 1] = "FILE:" .. t.name .. ";" .. body
        end
    end
    if action == "42440" or action == "42441" then parts[#parts + 1] = "FILE:untitled;" .. one end
    return table.concat(parts, ";")
end

local function track_at(i) return tracks[i + 1] end

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
    Undo_BeginBlock = function() undo_depth = (undo_depth or 0) + 1 end,
    Undo_EndBlock = function(desc) undo_depth = undo_depth - 1; last_undo_desc = desc end,
    Undo_EndBlock2 = function(_, desc, flags) undo_depth = undo_depth - 1; last_undo_desc = desc; last_undo_flags = flags end,
    GetTrackStateChunk = function(t) return true, "<TRACK\nNAME \"" .. t.name .. "\"\n>\n" end,
    SetTrackStateChunk = function(t, chunk, isundo)
        last_chunk, last_chunk_isundo = chunk, isundo
        if not analyzer_installed then return false end
        if chunk:find("<JS", 1, true) then
            table.insert(t.fx, {name = "JS: TwelveTake MCP Analyzer", analyzer = true, added_as = chunk})
        end
        return true
    end,
    TrackFX_GetCount = function(t) return #t.fx end,
    GetTrackEnvelopeByName = function(t, name) return t.envelopes[name] end,
    CountEnvelopePoints = function(env) return env.points end,
    file_exists = function(path)
        if path:find("twelvetake_mcp_analyzer.jsfx", 1, true) then
            return analyzer_installed and path:find("/Effects/TwelveTake/", 1, true) ~= nil
        end
        local f = io.open(path, "r")
        if f then f:close() return true end
        return false
    end,
    GetMasterTrack = function() return master end,
    GetTrack = function(_, i) return track_at(i) end,
    CountTracks = function() return #tracks end,
    IsTrackSelected = function(t) return t.selected end,
    SetTrackSelected = function(t, s) t.selected = s end,
    GetTrackMediaItem = function(t, i) return t.items[i + 1] end,
    CountTrackMediaItems = function(t) return #t.items end,
    CountMediaItems = function() return #all_items() end,
    GetMediaItem = function(_, i) return all_items()[i + 1] end,
    IsMediaItemSelected = function(it) return it.selected end,
    SetMediaItemSelected = function(it, s) it.selected = s end,
    SelectAllMediaItems = function(_, s)
        select_all_calls = (select_all_calls or 0) + 1
        for _, it in ipairs(all_items()) do it.selected = s end
    end,
    GetMediaItemInfo_Value = function(it, key)
        if key == "D_POSITION" then return it.pos elseif key == "D_LENGTH" then return it.len
        elseif key == "B_MUTE" then return it.mute end
    end,
    SetMediaItemInfo_Value = function(it, key, v) if key == "B_MUTE" then it.mute = v end end,
    GetSet_LoopTimeRange2 = function(_, set, is_loop, s, e)
        local r = is_loop and loop or ts
        if set then
            r[1], r[2] = s, e
            if not is_loop then loop[1], loop[2] = s, e end
        end
        return r[1], r[2]
    end,
    GetCursorPosition = function() return cursor end,
    SetEditCurPos = function(t) cursor = t end,
    GetProjectLength = function() return 25 end,
    GetPlayState = function() return play_state end,
    InsertTrackAtIndex = function(i) table.insert(tracks, i + 1, new_track("")) end,
    DeleteTrack = function(t)
        for i, x in ipairs(tracks) do if x == t then table.remove(tracks, i) break end end
        for _, x in ipairs(tracks) do
            for j = #x.sends, 1, -1 do if x.sends[j].dst == t then table.remove(x.sends, j) end end
        end
    end,
    GetSetMediaTrackInfo_String = function(t, key, v, set) if set and key == "P_NAME" then t.name = v end return true, t.name end,
    SetMediaTrackInfo_Value = function(t, key, v)
        if key == "D_VOL" then t.vol = v elseif key == "D_PAN" then t.pan = v end
        t[key] = v
    end,
    GetMediaTrackInfo_Value = function(t, key)
        if key == "D_VOL" then return t.vol elseif key == "I_FXEN" then return t.fxen end
        return t[key] or 0
    end,
    CreateTrackSend = function(src, dst)
        table.insert(src.sends, {dst = dst})
        return #src.sends - 1
    end,
    SetTrackSendInfo_Value = function(t, cat, idx, key, v) t.sends[idx + 1][key] = v end,
    TrackFX_AddByName = function(t, name)
        fx_added = (fx_added or 0) + 1
        if not analyzer_installed then return -1 end
        table.insert(t.fx, {name = "JS: TwelveTake MCP Analyzer", analyzer = true, added_as = name})
        return #t.fx - 1
    end,
    TrackFX_GetFXName = function(t, i) local fx = t.fx[i + 1] return fx ~= nil, fx and fx.name or "" end,
    TrackFX_Delete = function(t, i) table.remove(t.fx, i + 1) end,
    TrackFX_GetParam = function(t, fx, p) return analyzer_protocol, 0, 1000 end,
    gmem_attach = function() end,
    gmem_write = function(i, v) gmem[i] = v end,
    gmem_read = function(i) return gmem[i] or 0 end,
    GetSetProjectInfo_String = function(_, key, value)
        if key == "RENDER_STATS" then return true, render_stats(value) end
        return true, ""
    end,
    PreventUIRefresh = function() end,
    UpdateArrange = function() end,
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

    send.lua = lua
    send.eval = lua.eval
    send.run = lua.execute
    return send


def state(bridge):
    return json.loads(bridge.eval("""(function()
        local names, sel, fx, sends, muted, isel = {}, {}, {}, {}, {}, {}
        for i, t in ipairs(tracks) do
            names[i] = t.name; sel[i] = t.selected; fx[i] = #t.fx; sends[i] = #t.sends
        end
        for i, t in ipairs(tracks) do for j, it in ipairs(t.items) do
            muted[#muted + 1] = it.mute; isel[#isel + 1] = it.selected
        end end
        local function j(v)
            local parts = {}
            for _, x in ipairs(v) do parts[#parts + 1] = tostring(x) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        return string.format('{"names":["%s"],"sel":%s,"fx":%s,"sends":%s,"muted":%s,"item_sel":%s,' ..
            '"master_fx":%d,"master_sel":%s,"ts":[%s,%s],"loop":[%s,%s],"cursor":%s}',
            table.concat(names, '","'), j(sel), j(fx), j(sends), j(muted), j(isel),
            #master.fx, tostring(master.selected), ts[1], ts[2], loop[1], loop[2], cursor)
    end)()"""))


def last_call(bridge):
    return json.loads(bridge.eval("""(function()
        local c = calls[#calls]
        local function j(v) local p = {} for _, x in ipairs(v) do p[#p + 1] = '"' .. tostring(x) .. '"' end return "[" .. table.concat(p, ",") .. "]" end
        return string.format('{"action":"%s","ts":[%s,%s],"selected":%s,"muted":%s,"track_count":%d,"sends":%s}',
            c.action, c.ts[1], c.ts[2], j(c.selected), j(c.muted), c.track_count, j(c.sends))
    end)()"""))


def call_count(bridge):
    return bridge.eval("#calls")


@pytest.fixture
def before(bridge):
    bridge.run("tracks[1].selected = true; items[3].selected = true; master.selected = false")
    return state(bridge)


def test_parse_render_stats_reads_every_entry(bridge):
    parse = bridge.eval("__MEASURE_TEST.parse_render_stats")
    entries = parse("FILE:a;b;LENGTH:1:02:03.500;PEAK:-3.0;LUFSI:-inf;LRA:+4.5;FILE:c;LENGTH:0:10.000;PEAK:-1")
    first, second = entries[1], entries[2]
    assert first["name"] == "a;b"
    assert first["length"] == pytest.approx(3723.5)
    assert first["PEAK"] == -3.0 and first["LRA"] == 4.5
    assert first["LUFSI"] is None
    assert second["name"] == "c" and second["length"] == 10.0 and second["PEAK"] == -1


def test_stereo_figures_for_mono_and_antiphase(bridge):
    stereo = bridge.eval("__MEASURE_TEST.stereo_from_sums")
    mono = stereo(1.0, 1.0, 1.0)
    assert mono["correlation"] == pytest.approx(1.0) and mono["balance_db"] == pytest.approx(0.0)
    assert mono["side_to_mid_db"] is None
    anti = stereo(1.0, 1.0, -1.0)
    assert anti["correlation"] == pytest.approx(-1.0) and anti["side_to_mid_db"] is None
    left = stereo(1.0, 0.0, 0.0)
    assert left["correlation"] is None and left["side_to_mid_db"] == pytest.approx(0.0)


def test_spectrum_puts_a_1k_tone_in_the_1k_band_at_its_level(bridge):
    bridge.run("""
        spec_pl, spec_pr, spec_cross = {}, {}, {}
        for k = 0, 2048 do spec_pl[k] = 0; spec_pr[k] = 0; spec_cross[k] = 0 end
        local n, frames, wsum2 = 4096, 10, 1536
        local k = 85
        local ms = 10 ^ (-20 / 10) / 2
        spec_pl[k] = ms * n * wsum2 * frames / 2
        spec_pr[k] = spec_pl[k]
        spec_cross[k] = spec_pl[k]
        spec = __MEASURE_TEST.spectrum_from_bins(spec_pl, spec_pr, spec_cross, 2049, frames, 48000, n, wsum2)
    """)
    bands = bridge.eval("spec.bands")
    levels = {bands[i]["hz"]: bands[i]["dbfs"] for i in range(1, len(bands) + 1)}
    assert levels[1000] == pytest.approx(-20.0, abs=0.05)
    assert all(v == float("-inf") for hz, v in levels.items() if hz != 1000)
    assert bridge.eval("spec.centroid_hz") == pytest.approx(85 * 48000 / 4096, abs=1)


def test_spectrum_tilt_is_flat_for_equal_octave_energy(bridge):
    bridge.run("""
        spec_pl, spec_pr, spec_cross = {}, {}, {}
        for k = 0, 2048 do spec_pl[k] = 0; spec_pr[k] = 0; spec_cross[k] = 0 end
        local bin_hz = 48000 / 4096
        for _, c in ipairs({31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000}) do
            local k = math.floor(c / bin_hz + 0.5)
            if k < 1 then k = 1 end
            if k * bin_hz >= c / math.sqrt(2) then spec_pl[k] = 1e6; spec_pr[k] = 1e6 end
        end
        spec = __MEASURE_TEST.spectrum_from_bins(spec_pl, spec_pr, spec_cross, 2049, 10, 48000, 4096, 1536)
    """)
    assert bridge.eval("spec.tilt_db_per_octave") == pytest.approx(0.0, abs=0.01)


def test_master_loudness_restores_everything(bridge, before):
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["ok"] is True, res
    assert res["target"] == "master"
    assert res["integrated_lufs"] == -14.13 and res["loudness_range_lu"] == 6.4
    assert res["short_term_max_lufs"] == -11.25 and res["momentary_max_lufs"] == -10.5
    assert res["sample_peak_dbfs"] == pytest.approx(-6.02, abs=0.01)
    assert res["true_peak_dbtp"] == pytest.approx(20 * math.log10(0.6), abs=0.01)
    assert res["samples_over_0dbfs"] == 3
    assert "note" not in res
    assert last_call(bridge)["action"] == "42440"
    assert state(bridge) == before


def test_master_true_peak_follows_the_master_fader(bridge, before):
    bridge.run("master.vol = 0.5")
    bridge.run("analyzer_samples = {peak = 0.5, true_peak = 0.6, sll = 100, srr = 100, slr = 100}")
    bridge.run("stats_text = 'FILE:untitled;LENGTH:0:10.000;PEAK:-12.041200;LUFSI:-20'")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["true_peak_dbtp"] == pytest.approx(20 * math.log10(0.3), abs=0.01)
    assert "note" not in res


def test_master_automation_is_flagged(bridge, before):
    bridge.run("stats_text = 'FILE:untitled;LENGTH:0:10.000;PEAK:-9.0;LUFSI:-20'")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["ok"] is True
    assert "approximate" in res["note"]


def test_track_loudness_uses_a_helper_that_is_removed(bridge, before):
    res = bridge("MeasureLoudness", 1, -1, -1, -1)
    assert res["ok"] is True, res
    call = last_call(bridge)
    assert call["action"] == "42438"
    assert call["selected"] == ["__twelvetake_measure__", "Bass"]
    assert call["track_count"] == 3
    assert call["sends"] == ["Bass>__twelvetake_measure__:0:1"]
    assert res["true_peak_dbtp"] == pytest.approx(20 * math.log10(0.6), abs=0.01)
    assert res["integrated_lufs"] == -14.13
    assert state(bridge) == before


def test_track_range_sets_and_restores_the_time_selection(bridge, before):
    res = bridge("MeasureLoudness", 0, -1, 2.0, 8.5)
    assert res["ok"] is True
    call = last_call(bridge)
    assert call["action"] == "42439"
    assert call["ts"] == [2.0, 8.5]
    assert state(bridge) == before


def test_item_mutes_only_its_overlapping_neighbors_and_restores_them(bridge, before):
    res = bridge("MeasureLoudness", 1, 1, -1, -1)
    assert res["ok"] is True and res["target"] == "item"
    call = last_call(bridge)
    assert call["action"] == "42439"
    assert call["ts"] == [3.0, 9.0]
    assert call["muted"] == ["0", "1", "0", "0"]
    assert state(bridge) == before


def test_spectrum_reports_bands_and_stereo(bridge, before):
    res = bridge("MeasureSpectrum", 0, -1, -1, -1)
    assert res["ok"] is True, res
    levels = {b["hz"]: b["dbfs"] for b in res["bands"]}
    assert levels[1000] is not None
    assert levels[63] is None
    assert res["correlation"] == pytest.approx(1.0)
    assert res["balance_db"] == pytest.approx(0.0)
    assert state(bridge) == before


def test_without_the_analyzer_loudness_still_reports_reaper_figures(bridge, before):
    bridge.run("analyzer_installed = false")
    res = bridge("MeasureLoudness", 0, -1, -1, -1)
    assert res["ok"] is True
    assert res["integrated_lufs"] == -14.13
    assert "true_peak_dbtp" not in res
    assert "--install-bridge" in res["note"]
    assert state(bridge) == before


def test_without_the_analyzer_spectrum_refuses_before_rendering(bridge):
    bridge.run("analyzer_installed = false")
    res = bridge("MeasureSpectrum", -1, -1, -1, -1)
    assert res["ok"] is False and "--install-bridge" in res["hint"]
    assert call_count(bridge) == 0


def test_a_mismatched_analyzer_is_reported_and_removed(bridge, before):
    bridge.run("analyzer_protocol = 99")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["ok"] is True and "does not match" in res["note"]
    assert "true_peak_dbtp" not in res
    assert state(bridge) == before


def test_a_bypassed_master_chain_is_reported(bridge, before):
    bridge.run("master.fxen = 0")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["ok"] is True and res["note"].startswith("The master's FX chain is bypassed")
    assert "true_peak_dbtp" not in res
    assert bridge.eval("fx_added") is None


def test_a_failure_mid_measurement_still_restores(bridge, before):
    bridge.run("fail_render = true")
    res = bridge("MeasureLoudness", 1, 1, -1, -1)
    assert res["ok"] is False and "render blew up" in res["error"]
    assert state(bridge) == before


@pytest.mark.parametrize("args, message", [
    ((7, -1, -1, -1), "Track not found"),
    ((-1, 0, -1, -1), "Items are on tracks"),
    ((1, 9, -1, -1), "Item not found"),
    ((1, 0, 1.0, 2.0), "its own span"),
    ((-1, -1, 1.0, -1), "both start_time and end_time"),
    ((-1, -1, 4.0, 4.0), "after start_time"),
])
def test_bad_targets_are_refused_without_rendering(bridge, before, args, message):
    res = bridge("MeasureLoudness", *args)
    assert res["ok"] is False and message in res["error"]
    assert call_count(bridge) == 0
    assert state(bridge) == before


def test_measuring_while_playing_is_refused(bridge):
    bridge.run("play_state = 1")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert res["ok"] is False and "Stop playback" in res["error"]
    assert call_count(bridge) == 0


def test_master_pan_is_flagged(bridge, before):
    bridge.run("master.D_PAN = -1")
    res = bridge("MeasureSpectrum", -1, -1, -1, -1)
    assert res["ok"] is True and "approximate" in res["note"]


def test_master_volume_automation_is_flagged(bridge, before):
    bridge.run("master.envelopes['Volume'] = {points = 3}")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert "approximate" in res["note"]


def test_pre_fx_master_automation_is_not_flagged(bridge, before):
    bridge.run("master.envelopes['Volume (Pre-FX)'] = {points = 3}")
    res = bridge("MeasureLoudness", -1, -1, -1, -1)
    assert "note" not in res


def test_a_channel_far_below_the_other_counts_as_silent(bridge):
    stereo = bridge.eval("__MEASURE_TEST.stereo_from_sums")
    hard_left = stereo(1.0, 1e-30, 1e-16)
    assert hard_left["correlation"] is None and hard_left["balance_db"] is None


def test_a_track_measurement_adds_the_analyzer_without_an_undo_point(bridge, before):
    bridge("MeasureLoudness", 1, -1, -1, -1)
    assert bridge.eval("undo_depth") is None
    assert bridge.eval("last_chunk_isundo") is False
    chunk = bridge.eval("last_chunk")
    assert '<JS "TwelveTake/twelvetake_mcp_analyzer.jsfx" ""' in chunk
    assert "\n- - - - " in chunk and "\n1 " not in chunk
    assert bridge.eval("fx_added") is None


def test_a_master_measurement_is_one_block_closed_with_no_state_flags_even_on_error(bridge, before):
    bridge("MeasureLoudness", -1, -1, -1, -1)
    assert bridge.eval("undo_depth") == 0
    assert bridge.eval("last_undo_desc") == "" and bridge.eval("last_undo_flags") == 0
    bridge.run("fail_render = true; last_undo_flags = nil")
    bridge("MeasureLoudness", -1, -1, -1, -1)
    assert bridge.eval("undo_depth") == 0 and bridge.eval("last_undo_flags") == 0


def test_item_selection_is_never_touched(bridge, before):
    bridge("MeasureLoudness", 1, 1, -1, -1)
    bridge("MeasureSpectrum", -1, -1, -1, -1)
    assert bridge.eval("select_all_calls") is None
    assert state(bridge)["item_sel"] == before["item_sel"]
