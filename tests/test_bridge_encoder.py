"""Headless regression tests for the bridge JSON encoder.

These run the *actual* Lua in ``reaper_mcp_bridge.lua`` via an embedded interpreter
(lupa) — no REAPER required — to lock in the empty-array serialization contract:
an empty list field must encode as ``[]``, not ``{}``. This guards the v1.5 fix
(array-marker metatable) against silent regression; the encoder had zero automated
coverage before, and an earlier draft of the fix was a no-op that nobody caught.

Skipped automatically where lupa is unavailable, so plain environments stay green.
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
    """The as_array + encode_json definitions, sliced out so they load without REAPER.

    The full bridge calls reaper.* at top level, so we can't execute it; this block
    is self-contained (plain Lua stdlib only).
    """
    m = re.search(r"local ARRAY_MARKER = \{\}.*?\n(?=-- Better JSON decoding)", bridge_src, re.S)
    assert m, "could not locate the as_array/encode_json block — did the encoder move or get renamed?"
    return m.group(0)


@pytest.fixture
def lua_run(encoder_block):
    """Run a Lua snippet with as_array/encode_json in scope; return its result to Python."""
    def _run(body):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        return lua.execute(encoder_block + "\n" + body)
    return _run


def test_full_bridge_compiles(bridge_src):
    """Whole bridge must parse — catches any syntax slip anywhere in the file."""
    lupa.LuaRuntime().compile(bridge_src)


def test_empty_marked_array_is_brackets(lua_run):
    assert lua_run("return encode_json(as_array({}))") == "[]"


def test_empty_unmarked_table_stays_object(lua_run):
    # Backwards-compat: only tables tagged via as_array() flip to []; bare {} is still {}.
    assert lua_run("return encode_json({})") == "{}"


def test_string_keyed_object_not_arrayified(lua_run):
    assert lua_run('return encode_json({a = 1})') == '{"a":1}'


def test_nonempty_arrays_unchanged(lua_run):
    assert lua_run("return encode_json(as_array({1, 2, 3}))") == "[1,2,3]"
    assert lua_run("return encode_json({10, 20})") == "[10,20]"  # unmarked non-empty still []


def test_empty_array_field_nested_in_object(lua_run):
    # The real response shape: a list field that happens to be empty.
    assert lua_run("return encode_json({markers = as_array({})})") == '{"markers":[]}'


def test_marker_survives_table_insert(lua_run):
    # Every real site marks at declaration, then fills with table.insert in a loop.
    out = lua_run("local t = as_array({}); table.insert(t, 7); table.insert(t, 8); return encode_json(t)")
    assert out == "[7,8]"


def test_marker_survives_length_append(lua_run):
    # fx/takes/notes/points sites populate with t[#t+1] = ... instead of table.insert.
    out = lua_run("local t = as_array({}); t[#t+1] = 5; t[#t+1] = 6; return encode_json(t)")
    assert out == "[5,6]"


def test_length_operator_intact_on_marked_empty(lua_run):
    # The marker must not break `#t` (used for the loop bounds and emptiness checks).
    assert lua_run("return #as_array({})") == 0


def test_array_of_empty_arrays(lua_run):
    # Marker recursion: encoder recurses into nested marked tables.
    assert lua_run("return encode_json(as_array({ as_array({}) }))") == "[[]]"


# --- decoder (v1.6.1) -------------------------------------------------------
#
# The decoder had no coverage at all. Two silent-corruption bugs lived here: a
# number pattern that rejected scientific notation, and an array scanner that was
# not string-aware. Both produced a SHORT argument list rather than an error, and a
# short argument list is how a bad value becomes a wrong REAPER call.


@pytest.fixture(scope="module")
def decoder_block(bridge_src):
    """The decode_json definition, sliced out so it loads without REAPER."""
    m = re.search(r"-- Better JSON decoding.*?\n(?=-- Read file contents)", bridge_src, re.S)
    assert m, "could not locate the decode_json block — did the decoder move or get renamed?"
    return m.group(0)


@pytest.fixture
def lua_decode(decoder_block):
    """Run a Lua snippet with decode_json in scope; return its result to Python."""
    def _run(body):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        return lua.execute(decoder_block + "\n" + body)
    return _run


def test_decodes_plain_numbers(lua_decode):
    assert lua_decode("return decode_json('42')") == 42
    assert lua_decode("return decode_json('-7')") == -7
    assert lua_decode("return decode_json('0.5')") == 0.5


def test_decodes_scientific_notation(lua_decode):
    # db_to_linear(-100) is 1e-05. Before the fix this whole branch returned nil.
    assert lua_decode("return decode_json('1.2e-05')") == pytest.approx(1.2e-05)
    assert lua_decode("return decode_json('1e5')") == pytest.approx(1e5)
    assert lua_decode("return decode_json('-3.4E+2')") == pytest.approx(-340.0)


def test_small_float_does_not_shorten_the_arg_list(lua_decode):
    """The headline bug: one exponent value used to collapse the whole array.

    A nil element punches a hole and Lua's `#` stops at the hole, so
    SetTrackSendUIVol(track, send, 1e-05, 0) arrived with the gain missing.
    """
    assert lua_decode("return #decode_json('[0.01,1.2e-05,0.03]')") == 3
    assert lua_decode("return decode_json('[0.01,1.2e-05,0.03]')[2]") == pytest.approx(1.2e-05)


def test_comma_inside_a_string_does_not_split_the_element(lua_decode):
    # A track named 'Gtr, DI' used to become two arguments and shift everything after it.
    assert lua_decode("""return #decode_json('["Gtr, DI"]')""") == 1
    assert lua_decode("""return decode_json('["Gtr, DI"]')[1]""") == "Gtr, DI"


def test_brackets_inside_a_string_do_not_confuse_depth(lua_decode):
    assert lua_decode("""return #decode_json('["a]b","c"]')""") == 2
    assert lua_decode("""return decode_json('["a]b","c"]')[1]""") == "a]b"


def test_escaped_quote_inside_a_string_element(lua_decode):
    assert lua_decode(r"""return #decode_json('["say \\"hi\\", ok"]')""") == 1


def test_malformed_element_fails_loudly_instead_of_shortening(lua_decode):
    # Unparseable element -> whole parse fails -> the caller gets a real error,
    # rather than a silently shorter argument list aimed at the wrong target.
    assert lua_decode("return decode_json('[1,@,3]')") is None


def test_literal_null_is_still_accepted(lua_decode):
    # `null` legitimately decodes to nil and must not be mistaken for malformed.
    assert lua_decode("return decode_json('[1,null,3]') ~= nil") is True


def test_nested_structures_still_parse(lua_decode):
    assert lua_decode("return #decode_json('[[1,2],[3]]')") == 2
    assert lua_decode("return decode_json('{\"a\":[1,2]}').a[2]") == 2


def test_windows_path_escape_preserved(lua_decode):
    # Guards the single-pass unescape fix: '\\r' in a path must not become a CR.
    assert lua_decode(r"""return decode_json('"C:\\\\Temp\\\\reaper"')""") == r"C:\Temp\reaper"


# --- GetTrackFXList (v1.6.1) ------------------------------------------------
#
# track_fx_get_list documented an `fx` array of {index, name, enabled} but called
# GetTrackInfo, whose payload has only `fx_names` (bare strings). Reported by
# @SNChicago in PR #9.
#
# The mocked suite cannot see this: it pins the Python-side function NAME, while the
# missing keys are produced in Lua. So the real handler runs here against a stub
# REAPER, which is the only place in public CI where the response shape is pinned.


@pytest.fixture(scope="module")
def fx_list_block(bridge_src):
    m = re.search(r"-- Get the FX chain on a track.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate GetTrackFXList — did it move or get renamed?"
    return m.group(0)


def stub_reaper(tracks_lua, master_lua="nil"):
    """A REAPER stand-in covering the five entry points GetTrackFXList touches.

    A track is a Lua list of FX tables: {name=, enabled=, offline=, named=}.
    `named=false` makes TrackFX_GetFXName return false, the case GetTrackInfo drops.
    """
    return f"""
local tracks = {{ {tracks_lua} }}
local master = {master_lua}
reaper = {{
    GetTrack = function(_, i) return tracks[i + 1] end,
    GetMasterTrack = function(_) return master end,
    TrackFX_GetCount = function(t) return #t end,
    TrackFX_GetFXName = function(t, i, _)
        local fx = t[i + 1]
        if fx.named == false then return false, "SHOULD BE IGNORED" end
        return true, fx.name
    end,
    TrackFX_GetEnabled = function(t, i) return t[i + 1].enabled end,
    TrackFX_GetOffline = function(t, i) return t[i + 1].offline end,
}}
"""


@pytest.fixture
def fx_list(encoder_block, fx_list_block):
    """Run GetTrackFXList against a stub REAPER; return the decoded JSON response."""
    def _run(setup_lua, call="GetTrackFXList(0)"):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        source = f"{encoder_block}\n{fx_list_block}\n{setup_lua}\nreturn encode_json({call})"
        return json.loads(lua.execute(source))
    return _run


TWO_FX = '{ {name="ReaEQ", enabled=true, offline=false}, {name="ReaComp", enabled=false, offline=false} }'


def test_returns_index_name_and_enabled_per_fx(fx_list):
    """The exact distinction the old GetTrackInfo path could not express."""
    out = fx_list(stub_reaper(TWO_FX))
    assert out["ok"] is True
    assert out["fx"] == [
        {"index": 0, "name": "ReaEQ", "enabled": True, "offline": False},
        {"index": 1, "name": "ReaComp", "enabled": False, "offline": False},
    ]
    assert out["fx_count"] == 2


def test_bypassed_fx_is_distinguishable(fx_list):
    out = fx_list(stub_reaper(TWO_FX))
    assert [row["enabled"] for row in out["fx"]] == [True, False]


def test_offline_is_reported_separately_from_bypass(fx_list):
    # An offline plugin is not the same as a bypassed one, and `enabled` alone
    # cannot tell them apart.
    chain = '{ {name="Massive", enabled=true, offline=true} }'
    out = fx_list(stub_reaper(chain))
    assert out["fx"][0] == {"index": 0, "name": "Massive", "enabled": True, "offline": True}


def test_empty_chain_reports_zero_fx(fx_list):
    out = fx_list(stub_reaper("{ }"))
    assert out["ok"] is True
    assert out["fx"] == []
    assert out["fx_count"] == 0


def test_empty_chain_serialises_as_brackets_not_braces(encoder_block, fx_list_block):
    """The whole v1.5.0 release exists because an empty list once regressed to {}.

    Asserted on the raw JSON text: json.loads maps both [] and {} to falsy
    containers, so decoding first would hide exactly the regression this guards.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    source = (
        f"{encoder_block}\n{fx_list_block}\n{stub_reaper('{ }')}\n"
        "return encode_json(GetTrackFXList(0).fx)"
    )
    assert lua.execute(source) == "[]"


def test_unnamed_fx_keeps_its_slot(fx_list):
    """GetTrackInfo SKIPPED these, silently shifting every later entry down one.

    Here the row survives with an empty name, so `index` still matches the real
    chain position and a caller addressing FX 2 addresses FX 2.
    """
    chain = (
        '{ {name="ReaEQ", enabled=true, offline=false},'
        '  {name="Broken", enabled=true, offline=false, named=false},'
        '  {name="ReaComp", enabled=true, offline=false} }'
    )
    out = fx_list(stub_reaper(chain))
    assert [row["index"] for row in out["fx"]] == [0, 1, 2]
    assert out["fx"][1]["name"] == ""
    assert out["fx"][2]["name"] == "ReaComp"


def test_missing_track_uses_the_house_error_shape(fx_list):
    out = fx_list(stub_reaper("{ }"), call="GetTrackFXList(99)")
    assert out == {"ok": False, "error": "Track not found"}


def test_master_track_resolves_via_minus_one(fx_list):
    """-1 is the master convention across this surface; the mocked suite cannot reach it."""
    master = '{ {name="ReaLimit", enabled=true, offline=false} }'
    out = fx_list(stub_reaper("{ }", master_lua=master), call="GetTrackFXList(-1)")
    assert out["ok"] is True
    assert out["fx"] == [{"index": 0, "name": "ReaLimit", "enabled": True, "offline": False}]


def test_index_below_minus_one_is_not_found(fx_list):
    out = fx_list(stub_reaper("{ }"), call="GetTrackFXList(-5)")
    assert out["ok"] is False


# --- InsertAudioFile (v1.6.1) -----------------------------------------------
#
# insert_audio_file called InsertMedia(file, mode), which takes two arguments, with four.
# track_index and position fell off the end and were never sent: the file landed on
# whichever track was selected at the edit cursor, and the tool reported success. The
# handler now aims both deliberately, which means it must also put the user's selection
# and cursor back.


@pytest.fixture(scope="module")
def insert_audio_block(bridge_src):
    m = re.search(r"-- Insert an audio file onto a specific track.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate InsertAudioFile — did it move or get renamed?"
    return m.group(0)


INSERT_STUB = """
-- Four tracks. Track 2 is the target; tracks 0 and 3 start SELECTED so we can prove
-- the original selection is restored rather than clobbered.
local tracks = {}
for i = 0, 3 do tracks[i] = {id = i, items = {}, selected = (i == 0 or i == 3)} end

log = {cursor_sets = {}, inserted = nil, ui_refresh = 0}
local cursor = 12.5

reaper = {
    GetTrack = function(_, i) return tracks[i] end,
    CountTracks = function(_) return 4 end,
    IsTrackSelected = function(t) return t.selected end,
    SetTrackSelected = function(t, v) t.selected = v end,
    GetCursorPosition = function() return cursor end,
    SetEditCurPos = function(p) cursor = p; log.cursor_sets[#log.cursor_sets + 1] = p end,
    PreventUIRefresh = function(n) log.ui_refresh = log.ui_refresh + n end,
    UpdateArrange = function() end,
    CountTrackMediaItems = function(t) return #t.items end,
    GetTrackMediaItem = function(t, i) return t.items[i + 1] end,
    GetMediaItemInfo_Value = function(item, _) return item.pos end,
    InsertMedia = function(file, mode)
        -- Mimic REAPER: the file lands on the SELECTED track at the CURRENT cursor.
        for i = 0, 3 do
            if tracks[i].selected then
                table.insert(tracks[i].items, {pos = cursor})
                log.inserted = {track = i, pos = cursor, file = file, mode = mode}
                return 1
            end
        end
        return 0
    end,
}
"""


@pytest.fixture
def insert_audio(encoder_block, insert_audio_block):
    def _run(call, tail="log"):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        source = (
            f"{encoder_block}\n{insert_audio_block}\n{INSERT_STUB}\n"
            f"local response = {call}\n"
            f"return encode_json(response), encode_json({{track = log.inserted and log.inserted.track,"
            f" pos = log.inserted and log.inserted.pos, cursor = reaper.GetCursorPosition(),"
            f" sel0 = reaper.GetTrack(0,0).selected, sel2 = reaper.GetTrack(0,2).selected,"
            f" sel3 = reaper.GetTrack(0,3).selected, ui = log.ui_refresh}})"
        )
        response, state = lua.execute(source)
        return json.loads(response), json.loads(state)
    return _run


def test_audio_lands_on_the_requested_track_and_position(insert_audio):
    response, state = insert_audio('InsertAudioFile(2, "kick.wav", 4.25)')
    assert response["ok"] is True
    assert state["track"] == 2, "file went to the wrong track"
    assert state["pos"] == 4.25, "file went to the wrong position"
    assert response["track_index"] == 2
    assert response["position"] == 4.25
    assert response["item_index"] == 0


def test_the_users_selection_is_restored(insert_audio):
    """Aiming the insert means touching the selection; it is not ours to keep."""
    _, state = insert_audio('InsertAudioFile(2, "kick.wav", 4.25)')
    assert state["sel0"] is True, "track 0 was selected before and must be again"
    assert state["sel3"] is True, "track 3 was selected before and must be again"
    assert state["sel2"] is False, "track 2 was NOT selected before and must not be now"


def test_the_edit_cursor_is_restored(insert_audio):
    _, state = insert_audio('InsertAudioFile(2, "kick.wav", 4.25)')
    assert state["cursor"] == 12.5


def test_ui_refresh_is_balanced(insert_audio):
    """An unbalanced PreventUIRefresh leaves REAPER's UI frozen."""
    _, state = insert_audio('InsertAudioFile(2, "kick.wav", 4.25)')
    assert state["ui"] == 0


def test_missing_track_is_rejected_before_touching_anything(insert_audio):
    response, state = insert_audio('InsertAudioFile(99, "kick.wav", 1.0)')
    assert response["ok"] is False
    assert response["error"] == "Track not found"
    # A nil Lua value has no key at all once encoded, so absent means "never inserted".
    assert state.get("track") is None, "nothing should have been inserted"
    assert state["cursor"] == 12.5, "the cursor should not have moved"


def test_empty_file_path_is_rejected(insert_audio):
    response, _ = insert_audio('InsertAudioFile(2, "", 1.0)')
    assert response["ok"] is False
    assert "file_path" in response["error"]


# --- GetTrackInfo volume/pan (v1.6.1) ---------------------------------------


@pytest.fixture(scope="module")
def track_info_block(bridge_src):
    m = re.search(r"local function GetTrackInfo\(track_index\).*?\nend\n", bridge_src, re.S)
    assert m, "could not locate GetTrackInfo"
    return m.group(0)


TRACK_INFO_STUB = """
local values = {D_VOL = 0.5, D_PAN = -0.25, B_MUTE = 0, I_SOLO = 0}
local track = {}
reaper = {
    GetTrack = function(_, i) if i == 0 then return track end return nil end,
    GetMasterTrack = function(_) return track end,
    GetTrackName = function(_) return true, "Drums" end,
    GetSetMediaTrackInfo_String = function(_, key) return true, key == "GUID" and "{GUID}" or "" end,
    CountTrackMediaItems = function(_) return 0 end,
    GetTrackMediaItem = function(_, _) return nil end,
    GetActiveTake = function(_) return nil end,
    TakeIsMIDI = function(_) return false end,
    TrackFX_GetCount = function(_) return 0 end,
    TrackFX_GetFXName = function(_, _, _) return true, "" end,
    GetMediaTrackInfo_Value = function(_, key) return values[key] end,
}
"""


def test_get_track_info_returns_volume_and_pan(encoder_block, track_info_block):
    """get_track documented volume_db and pan since 1.0 and returned neither."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    source = f"{encoder_block}\n{track_info_block}\n{TRACK_INFO_STUB}\nreturn encode_json(GetTrackInfo(0))"
    info = json.loads(lua.execute(source))["info"]
    assert info["volume"] == pytest.approx(0.5)
    # 0.5 linear is about -6.02 dB.
    assert info["volume_db"] == pytest.approx(-6.0206, abs=1e-3)
    assert info["pan"] == pytest.approx(-0.25)
    assert info["muted"] is False
    assert info["soloed"] is False


def test_silent_track_reports_a_floor_not_negative_infinity(encoder_block, track_info_block):
    """log(0) is -inf, which is not valid JSON and would break the response."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    stub = TRACK_INFO_STUB.replace("D_VOL = 0.5", "D_VOL = 0")
    source = f"{encoder_block}\n{track_info_block}\n{stub}\nreturn encode_json(GetTrackInfo(0))"
    raw = lua.execute(source)
    # Lua renders -math.huge as "-inf", which is not valid JSON. Match that exactly:
    # a bare "inf" also occurs inside the "info" key and would false-positive.
    assert "-inf" not in raw and "nan" not in raw, raw
    assert json.loads(raw)["info"]["volume_db"] == -150
