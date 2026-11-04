import asyncio
import math

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


WRITE_TOOLS = ["move_tracks", "set_track_display", "set_take_name", "rename_marker",
               "rename_region", "set_play_rate"]


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_each_edit_is_one_undo_step(name):
    assert name in srv.UNDO_STEP_TOOLS


def test_get_play_rate_is_a_read():
    assert "get_play_rate" not in srv.UNDO_STEP_TOOLS
    assert srv.mcp._tool_manager.get_tool("get_play_rate").annotations.readOnlyHint is True


# --- move_tracks ---

def test_move_tracks_sends_the_list_the_destination_and_the_folder_flag(reaper):
    run(srv.move_tracks([4, 2], 0))
    assert reaper.last == ("MoveTracks", [[4, 2], 0, False])
    run(srv.move_tracks([1], 3, into_folder=True))
    assert reaper.last == ("MoveTracks", [[1], 3, True])


@pytest.mark.parametrize("indices, before, fragment", [
    ([], 0, "at least one track"),
    ([-1], 0, "track_indices[0]"),
    ([0, -2], 0, "track_indices[1]"),
    ([0], -1, "before_index"),
])
def test_move_tracks_refuses_before_reaching_reaper(reaper, indices, before, fragment):
    res = run(srv.move_tracks(indices, before))
    assert res["ok"] is False
    assert fragment in res["error"]
    assert reaper.calls == []


def test_move_tracks_returns_the_bridge_answer(reaper):
    reaper.response = {"ok": True, "tracks": [{"from": 3, "to": 0}]}
    assert run(srv.move_tracks([3], 0)) == {"ok": True, "tracks": [{"from": 3, "to": 0}]}


# --- set_track_display ---

@pytest.mark.parametrize("kwargs, sent", [
    ({"show_in_arrange": False}, [0, -1, -1]),
    ({"show_in_arrange": True}, [1, -1, -1]),
    ({"show_in_mixer": False}, [-1, 0, -1]),
    ({"show_in_mixer": True, "height": 0}, [-1, 1, 0]),
    ({"height": 120}, [-1, -1, 120]),
    ({"show_in_arrange": False, "show_in_mixer": False, "height": 40}, [0, 0, 40]),
])
def test_set_track_display_sends_only_the_settings_given(reaper, kwargs, sent):
    run(srv.set_track_display([2, -1], **kwargs))
    assert reaper.last == ("SetTrackDisplay", [[2, -1], *sent])


@pytest.mark.parametrize("indices, kwargs, fragment", [
    ([0], {}, "Nothing to change"),
    ([], {"height": 10}, "at least one track"),
    ([0], {"height": -5}, "height must be >= 0"),
])
def test_set_track_display_refuses_before_reaching_reaper(reaper, indices, kwargs, fragment):
    res = run(srv.set_track_display(indices, **kwargs))
    assert res["ok"] is False
    assert fragment in res["error"]
    assert reaper.calls == []


# --- set_take_name ---

def test_set_take_name_names_the_active_take_when_no_take_is_given(reaper):
    run(srv.set_take_name(1, 2, "Lead vocal"))
    assert reaper.last == ("SetTakeName", [1, 2, -1, "Lead vocal"])


def test_set_take_name_passes_an_explicit_take(reaper):
    run(srv.set_take_name(1, 2, "Comp B", take_index=0))
    assert reaper.last == ("SetTakeName", [1, 2, 0, "Comp B"])


@pytest.mark.parametrize("args, kwargs, fragment", [
    ((-1, 0, "x"), {}, "track_index"),
    ((0, -1, "x"), {}, "item_index"),
    ((0, 0, "x"), {"take_index": -1}, "take_index"),
])
def test_set_take_name_refuses_negative_indices(reaper, args, kwargs, fragment):
    res = run(srv.set_take_name(*args, **kwargs))
    assert res["ok"] is False
    assert fragment in res["error"]
    assert reaper.calls == []


# --- rename_marker / rename_region ---

def test_rename_marker_and_region_name_their_kind(reaper):
    run(srv.rename_marker(3, "Chorus"))
    assert reaper.last == ("RenameMarker", [3, False, "Chorus"])
    run(srv.rename_region(3, ""))
    assert reaper.last == ("RenameMarker", [3, True, ""])


# --- play rate ---

def test_get_play_rate(reaper):
    run(srv.get_play_rate())
    assert reaper.last == ("GetPlayRate", [])


@pytest.mark.parametrize("rate", [0.25, 1.0, 1.5, 4])
def test_set_play_rate_passes_a_rate_in_range(reaper, rate):
    run(srv.set_play_rate(rate))
    assert reaper.last == ("SetPlayRate", [rate])


@pytest.mark.parametrize("rate", [0.2499, 4.0001, 0, -1, math.nan, math.inf])
def test_set_play_rate_refuses_a_rate_out_of_range(reaper, rate):
    res = run(srv.set_play_rate(rate))
    assert res["ok"] is False
    assert "between 0.25 and 4" in res["error"]
    assert reaper.calls == []
