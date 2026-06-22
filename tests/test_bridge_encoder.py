"""Headless regression tests for the bridge JSON encoder.

These run the *actual* Lua in ``reaper_mcp_bridge.lua`` via an embedded interpreter
(lupa) — no REAPER required — to lock in the empty-array serialization contract:
an empty list field must encode as ``[]``, not ``{}``. This guards the v1.5 fix
(array-marker metatable) against silent regression; the encoder had zero automated
coverage before, and an earlier draft of the fix was a no-op that nobody caught.

Skipped automatically where lupa is unavailable, so plain environments stay green.
"""
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
