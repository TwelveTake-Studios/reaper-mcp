"""Response-shape tests for the bridge's RenderProject handler.

One render_project call used to rewrite seven of the project's render settings and
restore none of them (#12, reported by @SNChicago), and reported success without
checking that a file was produced — after ``overwrite=true`` had already deleted the
previous output. The handler now snapshots the settings, restores them on
every exit path, refuses when an existing target cannot be deleted, and refuses to
claim success for a file that does not exist (or exists at zero bytes, which is the
husk REAPER leaves when a render starts and dies).

Like ``test_bridge_encoder.py``, these run the *actual* Lua from
``reaper_mcp_bridge.lua`` under lupa against a stub REAPER. The mocked suite cannot
see any of this — it pins the Python-side function name, while both bugs live
entirely in Lua.

Stub fidelity notes (each guards a real regression class):

* String and numeric render keys live in SEPARATE tables and each API refuses the
  other channel, the way the real API does — so a future edit that snapshots a
  numeric key through GetSetProjectInfo_String (or restores a string key through the
  numeric API) fails here instead of clobbering user settings live.
* RENDER_TARGETS is DERIVED from the live settings at read time (REAPER computes it
  from RENDER_FILE/PATTERN/FORMAT), so hoisting the read out of the mutated-settings
  window — the ordering the bridge comment calls load-bearing — turns tests red.
"""
import json
import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"


@pytest.fixture(scope="module")
def bridge_src():
    return BRIDGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def encoder_block(bridge_src):
    """Same slice as test_bridge_encoder.py: as_array + encode_json, REAPER-free."""
    m = re.search(r"local ARRAY_MARKER = \{\}.*?\n(?=-- Better JSON decoding)", bridge_src, re.S)
    assert m, "could not locate the as_array/encode_json block — did the encoder move?"
    return m.group(0)


@pytest.fixture(scope="module")
def decoder_block(bridge_src):
    """Same slice as test_bridge_encoder.py: decode_json, REAPER-free."""
    m = re.search(r"-- Better JSON decoding.*?\n(?=-- Read file contents)", bridge_src, re.S)
    assert m, "could not locate the decode_json block — did the decoder move?"
    return m.group(0)


@pytest.fixture(scope="module")
def render_block(bridge_src):
    m = re.search(r"-- Render the master mix.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate RenderProject — did it move or get renamed?"
    return m.group(0)


@pytest.fixture
def lua_tmp(tmp_path):
    """tmp_path, but only when Lua's io.open can actually address it.

    lupa hands Lua the chunk as UTF-8 bytes while Lua's io.open is C fopen, which on
    Windows decodes filenames in the ANSI code page; the two agree only on ASCII. A
    non-ASCII username makes every tmp_path non-ASCII, which would fail these tests
    against perfectly correct production code.
    """
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    return tmp_path


def stub_render_reaper(targets_lua=None, action_lua=""):
    """A REAPER stand-in for the render surface.

    The settings hold recognisably non-default user values so a restore-to-defaults
    bug would be caught. ``during_render`` snapshots what the settings were at the
    moment Main_OnCommand fired — the only moment they may legitimately differ from
    the user's own. ``action_lua`` simulates what the render command does: create
    the file, nothing (how REAPER signals failure), or throw. ``targets_lua``
    overrides the derived RENDER_TARGETS for multi-target/edge-case tests.
    """
    targets_expr = targets_lua if targets_lua is not None else "derived_targets()"
    return f"""
string_settings = {{
    RENDER_FILE = "D:/UserRenders", RENDER_PATTERN = "$project", RENDER_FORMAT = "OGGV",
}}
numeric_settings = {{
    RENDER_SETTINGS = 3, RENDER_BOUNDSFLAG = 2, RENDER_STARTPOS = 10.5, RENDER_ENDPOS = 99.25,
}}
function all_settings()
    local merged = {{}}
    for k, v in pairs(string_settings) do merged[k] = v end
    for k, v in pairs(numeric_settings) do merged[k] = v end
    return merged
end
local function derived_targets()
    -- What REAPER does: compute the target from the CURRENT file/pattern/format.
    local ext = string_settings.RENDER_FORMAT == "evaw" and ".wav" or ".ogg"
    return string_settings.RENDER_FILE .. "/" .. string_settings.RENDER_PATTERN .. ext
end
initial = all_settings()
render_ran = false
during_render = nil
local function render_action() {action_lua} end
reaper = {{
    GetSetProjectInfo_String = function(_, key, val, is_set)
        if key == "RENDER_TARGETS" then return true, {targets_expr} end
        if string_settings[key] == nil then return false, "" end -- wrong channel, like the real API
        if is_set then string_settings[key] = val end
        return true, string_settings[key]
    end,
    GetSetProjectInfo = function(_, key, val, is_set)
        if numeric_settings[key] == nil then return 0 end -- wrong channel, like the real API
        if is_set then numeric_settings[key] = val end
        return numeric_settings[key]
    end,
    GetProjectLength = function(_) return 60 end,
    Main_OnCommand = function(cmd, _)
        render_ran = true
        during_render = all_settings()
        during_render.cmd = cmd
        render_action()
    end,
}}
"""


@pytest.fixture
def render_call(encoder_block, render_block):
    """Run RenderProject against a stub REAPER; return response + settings evidence."""
    def _run(setup_lua, call, prelude=""):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        source = (
            f"{setup_lua}\n{encoder_block}\n{render_block}\n{prelude}\n"
            f"local response = {call}\n"
            "return encode_json({response = response, settings = all_settings(),"
            " initial = initial, during_render = during_render, render_ran = render_ran})"
        )
        return json.loads(lua.execute(source))
    return _run


def make_file_action(path, content="RIFF"):
    """Lua that simulates a render actually producing its output file."""
    return f'local f = io.open("{path}", "wb") f:write("{content}") f:close()'


def test_render_success_shape_unchanged(render_call, lua_tmp):
    """The original success shape must survive: ok, ret, output, targets."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"] == {"ok": True, "ret": True, "output": target, "targets": target}
    assert out["render_ran"] is True
    assert out["during_render"]["cmd"] == 42230


def test_render_restores_settings_after_success(render_call, lua_tmp):
    """#12: the user's render settings survive a successful render untouched."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["settings"] == out["initial"]
    # And the mutation really happened in between — this test would pass vacuously
    # if RenderProject had stopped writing the settings at all.
    assert out["during_render"]["RENDER_SETTINGS"] == 0
    assert out["during_render"]["RENDER_FILE"] == lua_tmp.as_posix()
    assert out["during_render"]["RENDER_PATTERN"] == "mix"


def test_render_refusal_restores_settings_and_does_not_render(render_call, lua_tmp):
    """#12's worst path before the fix: refuse the render but keep the mutation."""
    target = lua_tmp / "mix.wav"
    target.write_bytes(b"precious")
    out = render_call(
        stub_render_reaper(),
        f'RenderProject("{target.as_posix()}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert "already exists" in out["response"]["error"]
    assert out["render_ran"] is False
    assert out["settings"] == out["initial"]
    assert target.read_bytes() == b"precious"


def test_render_overwrite_deletes_then_renders(render_call, lua_tmp):
    target = lua_tmp / "mix.wav"
    target.write_bytes(b"OLD")
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target.as_posix())),
        f'RenderProject("{target.as_posix()}", -1, -1, 0, true)',
    )
    assert out["response"]["ok"] is True
    assert target.read_bytes() == b"RIFF"


def test_render_undeletable_target_is_refused_before_rendering(render_call, lua_tmp):
    """A locked target survives os.remove; rendering over it would pop REAPER's
    modal overwrite prompt and then report the stale file as fresh output."""
    target = lua_tmp / "mix.wav"
    target.write_bytes(b"held open elsewhere")
    out = render_call(
        stub_render_reaper(),
        f'RenderProject("{target.as_posix()}", -1, -1, 0, true)',
        prelude='os.remove = function() return nil, "locked" end',
    )
    assert out["response"]["ok"] is False
    assert "Could not delete" in out["response"]["error"]
    assert out["render_ran"] is False
    assert out["settings"] == out["initial"]
    assert target.read_bytes() == b"held open elsewhere"


def test_render_that_produces_nothing_is_a_failure(render_call, lua_tmp):
    """Main_OnCommand signals failure by doing nothing; the output is the check."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(),  # render action: nothing
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert "produced no output" in out["response"]["error"]
    assert out["render_ran"] is True
    assert out["settings"] == out["initial"]


def test_render_zero_byte_output_is_a_failure(render_call, lua_tmp):
    """REAPER creates the target at zero bytes when a render starts; a render that
    starts and dies leaves that husk behind, and it is not output."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=f'local f = io.open("{target}", "wb") f:close()'),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert "produced no output" in out["response"]["error"]
    assert out["settings"] == out["initial"]


def test_render_failure_after_overwrite_names_the_deletion(render_call, lua_tmp):
    """The data-destroying combination: overwrite=true deletes the previous file,
    then the render does not run. The error must say the old file is gone."""
    target = lua_tmp / "mix.wav"
    target.write_bytes(b"precious")
    out = render_call(
        stub_render_reaper(),  # render action: nothing
        f'RenderProject("{target.as_posix()}", -1, -1, 0, true)',
    )
    assert out["response"]["ok"] is False
    assert "produced no output" in out["response"]["error"]
    assert "deleted" in out["response"]["error"]
    assert not target.exists()


def test_render_throw_still_restores_settings(render_call, lua_tmp):
    """#12: a render that throws must not leave the settings mutated, and must come
    back as this handler's structured error rather than unwinding into the generic
    "Bridge error" path, which would discard it."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua='error("boom")'),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert out["response"]["error"].startswith("Render failed:")
    assert "boom" in out["response"]["error"]
    assert out["settings"] == out["initial"]


def test_render_custom_bounds_active_only_during_render(render_call, lua_tmp):
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", 2, 5, 1, nil)',
    )
    assert out["during_render"]["RENDER_BOUNDSFLAG"] == 0
    assert out["during_render"]["RENDER_STARTPOS"] == 2
    assert out["during_render"]["RENDER_ENDPOS"] == 6  # end + tail
    assert out["settings"] == out["initial"]


def test_render_tail_only_extends_project_length(render_call, lua_tmp):
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 3, nil)',
    )
    assert out["during_render"]["RENDER_BOUNDSFLAG"] == 0
    assert out["during_render"]["RENDER_STARTPOS"] == 0
    assert out["during_render"]["RENDER_ENDPOS"] == 63  # GetProjectLength(60) + tail


def test_render_default_bounds_is_entire_project(render_call, lua_tmp):
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["during_render"]["RENDER_BOUNDSFLAG"] == 1
    # The range keys are never written on this branch, so they hold user values.
    assert out["during_render"]["RENDER_STARTPOS"] == 10.5
    assert out["during_render"]["RENDER_ENDPOS"] == 99.25


def test_render_format_forced_only_for_wav(render_call, lua_tmp):
    wav = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(wav)),
        f'RenderProject("{wav}", -1, -1, 0, nil)',
    )
    assert out["during_render"]["RENDER_FORMAT"] == "evaw"

    ogg = (lua_tmp / "mix.ogg").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(ogg)),
        f'RenderProject("{ogg}", -1, -1, 0, nil)',
    )
    assert out["during_render"]["RENDER_FORMAT"] == "OGGV"  # untouched


def test_render_checks_every_target_reaper_computed(render_call, lua_tmp):
    """RENDER_TARGETS can list several files (stems); all must exist for success."""
    a = lua_tmp / "a.wav"
    b = lua_tmp / "b.wav"
    out = render_call(
        stub_render_reaper(
            targets_lua=f'"{a.as_posix()};{b.as_posix()}"',
            action_lua=make_file_action(a.as_posix()),  # only a is produced
        ),
        f'RenderProject("{a.as_posix()}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    missing_list = out["response"]["error"].split("produced no output at: ")[1]
    assert b.as_posix() in missing_list
    assert a.as_posix() not in missing_list


def test_render_semicolon_filename_succeeds(render_call, lua_tmp):
    """";" is REAPER's target separator AND a legal filename character. A fresh
    single output whose name contains ";" must not be mis-split into fragments and
    reported as "produced no output" after a successful render."""
    target = (lua_tmp / "mix;v2.wav").as_posix()
    out = render_call(
        stub_render_reaper(action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is True, out["response"]
    assert out["response"]["output"] == target


def test_render_semicolon_existing_target_is_refused(render_call, lua_tmp):
    """When the ";"-bearing file already exists, the unsplit string names a real
    file and the overwrite refusal must fire on the WHOLE path, not on fragments."""
    target = lua_tmp / "mix;v2.wav"
    target.write_bytes(b"precious")
    out = render_call(
        stub_render_reaper(),
        f'RenderProject("{target.as_posix()}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert "already exists" in out["response"]["error"]
    assert target.as_posix() in out["response"]["error"]
    assert out["render_ran"] is False


def test_render_empty_targets_falls_back_to_the_callers_path(render_call, lua_tmp):
    """When REAPER reports no computed targets, the caller's path is the contract."""
    target = (lua_tmp / "mix.wav").as_posix()
    out = render_call(
        stub_render_reaper(targets_lua='""', action_lua=make_file_action(target)),
        f'RenderProject("{target}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is True
    assert out["response"]["output"] == target


def test_render_empty_targets_fallback_still_refuses_existing(render_call, lua_tmp):
    target = lua_tmp / "mix.wav"
    target.write_bytes(b"precious")
    out = render_call(
        stub_render_reaper(targets_lua='""'),
        f'RenderProject("{target.as_posix()}", -1, -1, 0, nil)',
    )
    assert out["response"]["ok"] is False
    assert "already exists" in out["response"]["error"]
    assert out["render_ran"] is False


# --- the dispatcher glue ------------------------------------------------------
#
# Everything above calls RenderProject directly, which leaves the process_request
# branch — arg validation, tonumber coercions, POSITIONAL ORDER, the result merge —
# unpinned. test_tools.py pins the Python half of the wire (["RenderProject", path,
# -1, -1, 0, False]); this pins the Lua half that unpacks it, driven through the
# real decode_json so a JSON false is proven to reach the handler as Lua false.


@pytest.fixture(scope="module")
def dispatch_body(bridge_src):
    m = re.search(
        r'(?m)^ {20}elseif fname == "RenderProject" then\n(.*?)\n^ {20}elseif ',
        bridge_src, re.S,
    )
    assert m, "could not locate the RenderProject dispatcher branch — did it move?"
    return m.group(1)


@pytest.fixture
def dispatch_render(encoder_block, decoder_block, dispatch_body):
    """Feed a raw request JSON through decode_json and the real dispatcher branch,
    with RenderProject stubbed to capture its exact positional arguments."""
    def _run(request_json):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        source = f"""
{encoder_block}
{decoder_block}
local captured = nil
RenderProject = function(...) captured = table.pack(...) return {{ok = true, ret = true}} end
local request = decode_json('{request_json}')
local fname = request.func
local args = request.args or {{}}
local response = {{ok = false}}
if fname == "RenderProject" then
{dispatch_body}
end
local out = {{ok = response.ok}}
if response.error ~= nil then out.error = response.error end
if response.ret ~= nil then out.ret = response.ret end
if captured then
    out.n = captured.n
    out.a1, out.a2, out.a3, out.a4, out.a5 = captured[1], captured[2], captured[3], captured[4], captured[5]
end
return encode_json(out)
"""
        return json.loads(lua.execute(source))
    return _run


def test_dispatch_positional_order_is_the_wire_contract(dispatch_render):
    """path, start, end, tail, overwrite — in that order, matching what
    test_tools.py pins on the Python side."""
    out = dispatch_render('{"func":"RenderProject","args":["D:/out/mix.wav",2,5,1,true]}')
    assert out["ok"] is True and out["ret"] is True
    assert (out["a1"], out["a2"], out["a3"], out["a4"], out["a5"]) == \
        ("D:/out/mix.wav", 2, 5, 1, True)
    assert out["n"] == 5


def test_dispatch_json_false_reaches_the_handler_as_false(dispatch_render):
    """The server always sends overwrite explicitly; false must not decay to nil
    anywhere between JSON and the handler."""
    out = dispatch_render('{"func":"RenderProject","args":["D:/out/mix.wav",-1,-1,0,false]}')
    assert out["a5"] is False
    assert out["n"] == 5


def test_dispatch_missing_args_get_the_documented_defaults(dispatch_render):
    out = dispatch_render('{"func":"RenderProject","args":["D:/out/mix.wav"]}')
    assert (out["a2"], out["a3"], out["a4"]) == (-1, -1, 0)
    assert "a5" not in out
    assert out["n"] == 5


def test_dispatch_numeric_strings_are_coerced(dispatch_render):
    out = dispatch_render('{"func":"RenderProject","args":["D:/out/mix.wav","2","5","1"]}')
    assert (out["a2"], out["a3"], out["a4"]) == (2, 5, 1)


def test_dispatch_empty_path_is_rejected_without_calling_the_handler(dispatch_render):
    out = dispatch_render('{"func":"RenderProject","args":[""]}')
    assert out["ok"] is False
    assert out["error"] == "RenderProject requires output_path (string)"
    assert "n" not in out  # RenderProject was never called


def test_dispatch_non_string_path_is_rejected(dispatch_render):
    out = dispatch_render('{"func":"RenderProject","args":[42]}')
    assert out["ok"] is False
    assert out["error"] == "RenderProject requires output_path (string)"
    assert "n" not in out
