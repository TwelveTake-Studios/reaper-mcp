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
project_length = 60
string_settings = {RENDER_FILE = "D:/UserRenders", RENDER_PATTERN = "$project", RENDER_FORMAT = "OGGV"}
numeric_settings = {
    RENDER_SETTINGS = 0, RENDER_BOUNDSFLAG = 2, RENDER_STARTPOS = 10.5, RENDER_ENDPOS = 99.25,
    RENDER_DELAY = 0, RENDER_NORMALIZE = 4 << 16,
}
renders = {}

local function target()
    return string_settings.RENDER_FILE .. "/" .. string_settings.RENDER_PATTERN .. ".wav"
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
    GetSetProjectInfo_String = function(_, key, val, is_set)
        if key == "RENDER_TARGETS" then return true, target() end
        if string_settings[key] == nil then return false, "" end
        if is_set then string_settings[key] = val end
        return true, string_settings[key]
    end,
    GetSetProjectInfo = function(_, key, val, is_set)
        if numeric_settings[key] == nil then return 0 end
        if is_set then numeric_settings[key] = val end
        return numeric_settings[key]
    end,
    Main_OnCommand = function(cmd)
        if cmd ~= 42230 then return end
        renders[#renders + 1] = {
            bounds = numeric_settings.RENDER_BOUNDSFLAG,
            start = numeric_settings.RENDER_STARTPOS,
            finish = numeric_settings.RENDER_ENDPOS,
        }
        local f = io.open(target(), "wb") f:write("RIFF") f:close()
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
    sent = []

    async def reaper_call(func, *args, timeout=None):
        sent.append(func)
        (mailbox / "request_1.json").write_text(
            json.dumps({"func": func, "args": list(args), "id": "x"}), encoding="utf-8")
        lua.globals().main()
        answer = mailbox / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    monkeypatch.setattr(srv, "reaper_call", reaper_call)
    g = lua.globals()
    g.sent = sent
    return g


def run(coro):
    return asyncio.run(coro)


def renders(g):
    return [dict(r.items()) for r in g.renders.values()]


def output(tmp_path, name="mix.wav"):
    return (tmp_path / name).as_posix()


def test_only_a_start_renders_from_the_start_to_the_project_end(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), start_time=12.5))
    assert out["ok"] is True, out
    assert renders(bridge) == [{"bounds": 0, "start": 12.5, "finish": 60}]


def test_only_an_end_renders_from_the_project_start(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), end_time=20.0))
    assert out["ok"] is True, out
    assert renders(bridge) == [{"bounds": 0, "start": 0, "finish": 20}]


def test_the_tail_extends_a_range_given_only_a_start(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), start_time=12.5, tail_seconds=2.0))
    assert out["ok"] is True, out
    assert renders(bridge) == [{"bounds": 0, "start": 12.5, "finish": 62}]


def test_the_tail_extends_a_range_given_only_an_end(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), end_time=20.0, tail_seconds=2.0))
    assert out["ok"] is True, out
    assert renders(bridge) == [{"bounds": 0, "start": 0, "finish": 22}]


def test_both_bounds_render_exactly_that_range(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), start_time=5.0, end_time=9.0))
    assert out["ok"] is True, out
    assert renders(bridge) == [{"bounds": 0, "start": 5, "finish": 9}]


def test_no_bounds_still_render_the_entire_project(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path)))
    assert out["ok"] is True, out
    assert renders(bridge)[0]["bounds"] == 1
    assert "GetProjectLength" not in bridge.sent


@pytest.mark.parametrize("start, end", [(9.0, 5.0), (5.0, 5.0)])
def test_an_end_at_or_before_the_start_is_refused_and_nothing_renders(bridge, tmp_path, start, end):
    out = run(srv.render_project(output(tmp_path), start_time=start, end_time=end))
    assert out["ok"] is False
    assert "end_time" in out["error"] and "start_time" in out["error"]
    assert renders(bridge) == []
    assert not (tmp_path / "mix.wav").exists()


def test_an_end_at_or_before_zero_with_no_start_is_refused(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), end_time=0.0))
    assert out["ok"] is False
    assert renders(bridge) == []


def test_a_start_at_or_after_the_project_end_is_refused(bridge, tmp_path):
    out = run(srv.render_project(output(tmp_path), start_time=60.0))
    assert out["ok"] is False
    assert "60" in out["error"]
    assert renders(bridge) == []
