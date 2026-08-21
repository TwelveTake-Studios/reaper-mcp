"""The return_notes escape hatch on MIDI write tools."""
import asyncio
import inspect

import pytest

import reaper_mcp_server as srv

ECHO_TOOLS = [
    "transpose_midi_notes", "nudge_midi_notes", "set_midi_note",
    "ramp_midi_note_velocities", "scale_midi_note_velocities", "strum_midi_notes",
    "snap_midi_notes_to_scale", "quantize_midi_notes", "stretch_midi_notes",
    "legato_midi_notes", "humanize_midi_notes", "remove_overlapping_midi_notes",
]


def _fn(name):
    f = getattr(srv, name)
    return getattr(f, "fn", f)


@pytest.mark.parametrize("name", ECHO_TOOLS)
def test_every_echoing_tool_offers_the_opt_out(name):
    """A wrapped return without the parameter is a NameError at call time.

    That exact mismatch happened while building this: one tool got the parameter and a
    different one got the wrapper.
    """
    params = inspect.signature(_fn(name)).parameters
    assert "return_notes" in params, f"{name} echoes notes but cannot be told not to"
    assert params["return_notes"].default is True, (
        f"{name} defaults to dropping the echo, which changes the documented response"
    )


def test_shape_helper_drops_only_notes():
    res = {"ok": True, "notes_changed": 3, "notes": [1, 2, 3], "clamped": 0}
    out = srv._shape_notes(dict(res), False)
    assert "notes" not in out
    assert out == {"ok": True, "notes_changed": 3, "clamped": 0}


def test_shape_helper_keeps_notes_by_default():
    res = {"ok": True, "notes": [1, 2, 3]}
    assert srv._shape_notes(dict(res), True) == res


def test_shape_helper_survives_a_non_dict():
    assert srv._shape_notes(None, False) is None


def test_shape_helper_ignores_a_response_with_no_notes():
    """Error responses and non-note tools pass through untouched."""
    res = {"ok": False, "error": "nope"}
    assert srv._shape_notes(dict(res), False) == res


def test_fields_keeps_only_what_was_asked_for():
    res = {"ok": True, "notes": [{"index": 0, "pitch": 60, "velocity": 90,
                                  "start_time": 0.0, "start_beat": 0.0, "muted": False}]}
    out = srv._shape_notes(res, True, ["pitch", "start_beat"])
    assert out["notes"] == [{"pitch": 60, "start_beat": 0.0}]
    assert out["ok"] is True, "the envelope must survive the filter"


def test_unknown_field_is_reported_not_fatal():
    """These wrap WRITE tools. The edit has already happened by the time the filter runs,
    so a typo in an output filter must not be reported as a failed edit."""
    res = {"ok": True, "notes_changed": 1,
           "notes": [{"index": 0, "pitch": 60, "velocity": 90}]}
    out = srv._shape_notes(res, True, ["pitch", "looudness"])
    assert out["ok"] is True
    assert out["fields_ignored"] == ["looudness"]
    assert out["notes"] == [{"pitch": 60}], "the recognised field still applied"


def test_all_field_names_unknown_leaves_the_notes_alone():
    res = {"ok": True, "notes": [{"index": 0, "pitch": 60}]}
    out = srv._shape_notes(res, True, ["nonsense"])
    assert out["notes"] == [{"index": 0, "pitch": 60}]
    assert out["fields_ignored"] == ["nonsense"]


def test_no_fields_argument_returns_full_shape_h():
    res = {"ok": True, "notes": [{k: 0 for k in srv.NOTE_FIELDS}]}
    out = srv._shape_notes(dict(res), True, None)
    assert set(out["notes"][0]) == set(srv.NOTE_FIELDS)


@pytest.mark.parametrize("name", ECHO_TOOLS + ["get_midi_notes", "get_selected_midi_notes"])
def test_every_note_returning_tool_offers_fields(name):
    params = inspect.signature(_fn(name)).parameters
    assert "fields" in params, f"{name} returns notes but cannot be told which keys"
    assert params["fields"].default is None, (
        f"{name} defaults to filtering, which changes the documented response shape"
    )


def test_opt_out_actually_strips_the_notes(reaper):
    reaper.response = {"ok": True, "notes_changed": 2, "notes": [{"index": 0}, {"index": 1}]}
    kept = asyncio.run(srv.transpose_midi_notes(0, 0, 2))
    assert "notes" in kept
    reaper.response = {"ok": True, "notes_changed": 2, "notes": [{"index": 0}, {"index": 1}]}
    dropped = asyncio.run(srv.transpose_midi_notes(0, 0, 2, return_notes=False))
    assert "notes" not in dropped
    assert dropped["notes_changed"] == 2, "the rest of the response must survive"


def test_opt_out_is_not_sent_to_the_bridge(reaper):
    """It is a server-side response filter. The bridge has no idea it exists.

    Sending it would shift every later positional argument by one, which for these tools
    means a filter object landing where a number belongs.
    """
    asyncio.run(srv.transpose_midi_notes(0, 0, 2, return_notes=False))
    func, args = reaper.last
    assert func == "TransposeMIDINotes"
    with_flag = asyncio.run(srv.transpose_midi_notes(0, 0, 2, return_notes=True))
    assert with_flag is not None
    same_func, same_args = reaper.last
    assert args == same_args, (
        "the argument list sent to REAPER changed with return_notes; it must not reach "
        f"the bridge at all. {args} vs {same_args}"
    )
