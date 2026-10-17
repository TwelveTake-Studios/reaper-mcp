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
FADER_0DB = 716.21785031261

local function new_track(name) return {name = name, envs = {}} end
tracks = {new_track("Drums")}
master = new_track("MASTER")

function add_env(track, name, chunk, mode)
    local env = {name = name, chunk = chunk, mode = mode, points = {}}
    track.envs[name] = env
    return env
end

add_env(tracks[1], "Volume", "<VOLENV2", 1)
add_env(tracks[1], "Volume (Pre-FX)", "<VOLENV", 0)
add_env(tracks[1], "Trim Volume", "<VOLENV3", 1)
add_env(tracks[1], "Pan", "<PANENV2", 0)
add_env(master, "Volume", "<VOLENV2", 0)
fx_env = {name = "Gain / ReaEQ", chunk = "<PARMENV", mode = 0, points = {}}

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
    UpdateArrange = function() end,
    GetTrack = function(_, i) return tracks[i + 1] end,
    GetMasterTrack = function() return master end,
    GetTrackEnvelopeByName = function(t, name) return t.envs[name] end,
    GetTrackEnvelopeByChunkName = function(t, chunk)
        for _, env in pairs(t.envs) do
            if env.chunk == chunk then return env end
        end
        return nil
    end,
    GetEnvelopeName = function(env) return true, env.name end,
    GetEnvelopeScalingMode = function(env) return env.mode end,
    ScaleToEnvelopeMode = function(mode, gain) return mode == 1 and gain * FADER_0DB or gain end,
    ScaleFromEnvelopeMode = function(mode, v) return mode == 1 and v / FADER_0DB or v end,
    Envelope_FormatValue = function(env, v) return env.name .. "=" .. string.format("%.4f", v) end,
    InsertEnvelopePoint = function(env, time, value, shape)
        env.points[#env.points + 1] = {time = time, value = value, shape = shape}
        return true
    end,
    Envelope_SortPoints = function(env)
        table.sort(env.points, function(a, b) return a.time < b.time end)
    end,
    CountEnvelopePoints = function(env) return #env.points end,
    GetEnvelopePointByTime = function(env, time)
        local found = -1
        for i, p in ipairs(env.points) do
            if p.time <= time then found = i - 1 end
        end
        return found
    end,
    GetEnvelopePoint = function(env, i)
        local p = env.points[i + 1]
        if not p then return false end
        return true, p.time, p.value, p.shape, 0, false
    end,
    GetFXEnvelope = function() return fx_env end,
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

    def send(func, args):
        (mailbox / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = mailbox / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    async def reaper_call(func, *args, timeout=None):
        return send(func, args)

    monkeypatch.setattr(srv, "reaper_call", reaper_call)

    def points(track, name):
        env = (lua.globals().master if track == -1 else lua.globals().tracks[track + 1]).envs[name]
        return [(p.time, p.value) for p in env.points.values()]

    send.points = points
    return send


def run(coro):
    return asyncio.run(coro)


GAIN_MINUS_6 = 10 ** (-6 / 20)


def test_value_db_on_a_fader_scaled_volume_envelope_is_scaled_for_that_mode(bridge):
    out = run(srv.add_envelope_point(0, "Volume", 1.0, value_db=-6.0))
    assert out["ok"] is True, out
    assert out["value"] == pytest.approx(GAIN_MINUS_6 * 716.21785031261)
    assert out["value_db"] == pytest.approx(-6.0)
    assert out["scaling"] == "fader"
    assert out["shown"] == "Volume=%.4f" % (GAIN_MINUS_6 * 716.21785031261)
    assert out["point_index"] == 0
    assert bridge.points(0, "Volume") == [(1.0, pytest.approx(GAIN_MINUS_6 * 716.21785031261))]


def test_value_db_on_an_amplitude_scaled_volume_envelope_is_linear_gain(bridge):
    out = run(srv.add_envelope_point(0, "Volume (Pre-FX)", 2.0, value_db=-6.0))
    assert out["ok"] is True, out
    assert out["value"] == pytest.approx(GAIN_MINUS_6)
    assert out["value_db"] == pytest.approx(-6.0)
    assert out["scaling"] == "amplitude"


def test_trim_and_master_volume_take_value_db(bridge):
    assert run(srv.add_envelope_point(0, "Trim Volume", 1.0, value_db=0.0))["value"] == pytest.approx(716.21785031261)
    assert run(srv.add_envelope_point(-1, "Volume", 1.0, value_db=0.0))["value"] == pytest.approx(1.0)


def test_value_db_at_or_below_minus_150_is_silence(bridge):
    out = run(srv.add_envelope_point(0, "Volume", 1.0, value_db=-150.0))
    assert out["value"] == 0
    assert out["value_db"] == -150


def test_value_db_on_a_pan_envelope_is_refused_and_writes_nothing(bridge):
    out = run(srv.add_envelope_point(0, "Pan", 1.0, value_db=-6.0))
    assert out["ok"] is False
    assert "value_db" in out["error"]
    assert bridge.points(0, "Pan") == []


def test_a_negative_raw_value_on_a_volume_envelope_is_refused_and_writes_nothing(bridge):
    out = run(srv.add_envelope_point(0, "Volume", 1.0, -6.0))
    assert out["ok"] is False
    assert "value_db" in out["error"]
    assert bridge.points(0, "Volume") == []


def test_a_negative_raw_value_on_a_pan_envelope_is_written(bridge):
    out = run(srv.add_envelope_point(0, "Pan", 1.0, -1.0))
    assert out["ok"] is True, out
    assert out["value"] == -1.0
    assert out["shown"] == "Pan=-1.0000"
    assert "value_db" not in out and "scaling" not in out


def test_a_raw_volume_value_is_still_written_as_given(bridge):
    out = run(srv.add_envelope_point(0, "Volume", 1.0, 0.5))
    assert out["ok"] is True, out
    assert out["value"] == 0.5
    assert out["value_db"] == pytest.approx(-63.11, abs=0.01)


@pytest.mark.parametrize("name", ["Volume", "Pan"])
def test_a_bridge_request_with_neither_value_is_refused(bridge, name):
    out = bridge("InsertEnvelopePoint", [0, name, 1.0, None, 0, 0, False, False, None])
    assert out["ok"] is False
    assert out["error"] == "Pass value or value_db"
    assert bridge.points(0, name) == []


def test_point_index_is_the_inserted_point_after_sorting(bridge):
    run(srv.add_envelope_point(0, "Pan", 1.0, 0.5))
    run(srv.add_envelope_point(0, "Pan", 3.0, 0.5))
    out = run(srv.add_envelope_point(0, "Pan", 2.0, 0.25))
    assert out["point_index"] == 1
    assert out["time"] == 2.0
    assert out["value"] == 0.25


def test_get_envelope_points_reports_shown_db_and_scaling_on_volume(bridge):
    run(srv.add_envelope_point(0, "Volume", 1.0, value_db=-6.0))
    run(srv.add_envelope_point(0, "Volume", 2.0, value_db=6.0))
    out = run(srv.get_envelope_points(0, "Volume"))
    assert out["ok"] is True, out
    assert out["scaling"] == "fader"
    assert [p["value_db"] for p in out["points"]] == [pytest.approx(-6.0), pytest.approx(6.0)]
    assert all(p["shown"].startswith("Volume=") for p in out["points"])


def test_get_envelope_points_on_pan_has_shown_but_no_db(bridge):
    run(srv.add_envelope_point(0, "Pan", 1.0, 1.0))
    out = run(srv.get_envelope_points(0, "Pan"))
    assert out["points"][0]["shown"] == "Pan=1.0000"
    assert "value_db" not in out["points"][0]
    assert "scaling" not in out


def test_fx_envelope_writes_and_reads_report_shown(bridge):
    out = run(srv.add_fx_envelope_point(0, 0, 1, 1.0, 0.25))
    assert out["ok"] is True, out
    assert out["shown"] == "Gain / ReaEQ=0.2500"
    points = run(srv.get_fx_envelope_points(0, 0, 1))["points"]
    assert points[0]["shown"] == "Gain / ReaEQ=0.2500"
