import json
import os
import shutil
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"

STUB = """
ext_state = {}
at_exit = {}
console = {}
clock = 1000
reaper = {
    GetResourcePath = function() return RESOURCE end,
    RecursiveCreateDirectory = function() return 1 end,
    ShowConsoleMsg = function(m) console[#console + 1] = m end,
    defer = function() end,
    EnumerateFiles = function(dir, i) return list_dir(dir, i) end,
    Undo_BeginBlock = function() end,
    Undo_EndBlock = function() end,
    GetExtState = function(section, key) return ext_state[section .. "/" .. key] or "" end,
    SetExtState = function(section, key, value, persist) ext_state[section .. "/" .. key] = value end,
    DeleteExtState = function(section, key, persist) ext_state[section .. "/" .. key] = nil end,
    time_precise = function() return clock end,
    atexit = function(fn) at_exit[#at_exit + 1] = fn end,
}
"""


@pytest.fixture
def harness(tmp_path):
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    requests = tmp_path / "Scripts" / "mcp_bridge_data"
    requests.mkdir(parents=True)
    script = tmp_path / "Scripts" / "reaper_mcp_bridge.lua"
    shutil.copy(BRIDGE, script)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)

    def list_dir(directory, index):
        if index < 0:
            return None
        names = sorted(os.listdir(requests))
        return names[index] if index < len(names) else None

    lua.globals().list_dir = list_dir
    lua.globals().RESOURCE = str(tmp_path).replace("\\", "/")
    lua.execute(STUB)

    class H:
        pass

    h = H()
    h.lua = lua
    h.script = script

    def load():
        lua.globals().dofile(str(script).replace("\\", "/"))

    def send(func, args=()):
        (requests / "request_1.json").write_text(json.dumps({"func": func, "args": list(args), "id": "t"}),
                                                  encoding="utf-8")
        lua.globals().main()
        answer = requests / "response_1.json"
        response = json.loads(answer.read_text(encoding="utf-8"))
        answer.unlink()
        return response

    def console():
        c = lua.globals().console
        return [c[i] for i in range(1, len(c) + 1)]

    def with_version(text):
        source = BRIDGE.read_text(encoding="utf-8")
        assert source.count('local BRIDGE_VERSION = "') == 1
        start = source.index('local BRIDGE_VERSION = "')
        end = source.index("\n", start)
        script.write_text(source[:start] + f'local BRIDGE_VERSION = "{text}"' + source[end:], encoding="utf-8")

    h.load, h.send, h.console, h.with_version = load, send, console, with_version
    return h


def test_a_bridge_loaded_from_a_file_can_reload(harness):
    harness.load()
    answer = harness.send("GetBridgeVersion")
    assert answer["can_reload"] is True
    assert answer["path"].replace("\\", "/").endswith("Scripts/reaper_mcp_bridge.lua")


def test_reload_switches_to_the_file_on_disk(harness):
    harness.load()
    harness.with_version("9.9.9")
    answer = harness.send("ReloadBridge")
    assert answer["ok"] is True and answer["reloading"] is True
    assert answer["path"].replace("\\", "/").endswith("Scripts/reaper_mcp_bridge.lua")
    assert harness.send("GetBridgeVersion")["version"] == "9.9.9"
    assert any("9.9.9 (File-based, Full API) started" in line for line in harness.console())
    assert not any("not started" in line for line in harness.console())


def test_a_file_that_does_not_load_leaves_the_bridge_running(harness):
    harness.load()
    before = harness.send("GetBridgeVersion")["version"]
    harness.script.write_text("this is not lua (\n", encoding="utf-8")
    answer = harness.send("ReloadBridge")
    assert answer["ok"] is False and "Could not load" in answer["error"]
    assert harness.send("GetBridgeVersion")["version"] == before


def test_a_file_that_fails_while_running_leaves_the_old_bridge_running(harness):
    harness.load()
    before = harness.send("GetBridgeVersion")["version"]
    harness.script.write_text('function main() end\nerror("boom at load")\n', encoding="utf-8")
    assert harness.send("ReloadBridge")["ok"] is True
    assert harness.send("GetBridgeVersion")["version"] == before
    assert any("reload failed" in line for line in harness.console())


def test_a_second_copy_does_not_start_while_one_is_running(harness):
    harness.load()
    harness.lua.execute("first_main = main\nfirst_handlers = DSL_FUNCTIONS\nclock = clock + 1")
    harness.load()
    assert harness.lua.eval("main == first_main") is True
    assert harness.lua.eval("DSL_FUNCTIONS == first_handlers") is True
    assert any("another copy is already running" in line for line in harness.console())


def test_a_copy_starts_once_the_running_one_has_stopped(harness):
    harness.load()
    harness.lua.execute("for _, fn in ipairs(at_exit) do fn() end")
    harness.load()
    assert not any("another copy is already running" in line for line in harness.console())


def test_a_stale_heartbeat_does_not_block_a_new_copy(harness):
    harness.load()
    harness.lua.execute("clock = clock + 5")
    harness.load()
    assert not any("another copy is already running" in line for line in harness.console())
