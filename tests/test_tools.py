"""Representative tool tests across domains, with REAPER mocked.

These verify the two things every glue tool must get right: the REAPER function name +
argument marshalling it sends, and that it returns the bridge response unchanged.
"""

import re
import asyncio

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


# --- pure helper (no mock needed) ---

def test_db_to_linear():
    assert srv.db_to_linear(0) == pytest.approx(1.0)
    assert srv.db_to_linear(-6.0) == pytest.approx(0.50119, rel=1e-3)
    assert srv.db_to_linear(-200) == 0  # floored below -150 dB


# --- pass-through tools ---

def test_get_track_count(reaper):
    run(srv.get_track_count())
    assert reaper.last == ("CountTracks", [0])


def test_transport(reaper):
    run(srv.play())
    assert reaper.last == ("OnPlayButton", [])
    run(srv.stop())
    assert reaper.last == ("OnStopButton", [])


def test_get_tempo(reaper):
    run(srv.get_tempo())
    assert reaper.last == ("Master_GetTempo", [])


def test_set_tempo(reaper):
    run(srv.set_tempo(120.0))
    assert reaper.last == ("SetCurrentBPM", [0, 120.0, True])


# --- argument marshalling ---

def test_set_track_pan(reaper):
    run(srv.set_track_pan(1, 0.5))
    assert reaper.last == ("SetMediaTrackInfo_Value", [1, "D_PAN", 0.5])


def test_set_track_mute_bool_to_int(reaper):
    run(srv.set_track_mute(2, True))
    assert reaper.last == ("SetMediaTrackInfo_Value", [2, "B_MUTE", 1])
    run(srv.set_track_mute(2, False))
    assert reaper.last == ("SetMediaTrackInfo_Value", [2, "B_MUTE", 0])


def test_set_track_volume_db_conversion(reaper):
    run(srv.set_track_volume(0, -6.0))
    func, args = reaper.last
    assert func == "SetMediaTrackInfo_Value"
    assert args[0] == 0
    assert args[1] == "D_VOL"
    assert args[2] == pytest.approx(0.50119, rel=1e-3)  # dB -> linear


def test_add_marker(reaper):
    run(srv.add_marker(5.0, "Chorus"))
    assert reaper.last == ("AddProjectMarker2", [0, False, 5.0, 0, "Chorus", -1, 0])


# --- response propagation ---

def test_response_is_returned_unchanged(reaper):
    reaper.response = {"ok": True, "ret": 9}
    assert run(srv.get_track_count()) == {"ok": True, "ret": 9}


# --- Take FX (v1.3.0): addressing, marshalling, validation ---

def test_take_fx_get_count_marshalling(reaper):
    run(srv.take_fx_get_count(0, 1, 2))
    assert reaper.last == ("TakeFX_GetCount", [0, 1, 2])


def test_take_fx_add_by_name_marshalling(reaper):
    run(srv.take_fx_add_by_name(0, 1, 2, "ReaEQ"))
    assert reaper.last == ("TakeFX_AddByName", [0, 1, 2, "ReaEQ"])


def test_take_fx_get_param_marshalling(reaper):
    run(srv.take_fx_get_param(0, 1, 2, 3, 4))
    assert reaper.last == ("TakeFX_GetParam", [0, 1, 2, 3, 4])


def test_take_fx_set_param_marshalling(reaper):
    run(srv.take_fx_set_param(0, 1, 2, 3, 4, 0.5))
    assert reaper.last == ("TakeFX_SetParam", [0, 1, 2, 3, 4, 0.5])


def test_take_fx_set_enabled_passes_bool(reaper):
    run(srv.take_fx_set_enabled(0, 1, 2, 3, True))
    assert reaper.last == ("TakeFX_SetEnabled", [0, 1, 2, 3, True])


def test_take_fx_delete_marshalling(reaper):
    run(srv.take_fx_delete(0, 1, 2, 3))
    assert reaper.last == ("TakeFX_Delete", [0, 1, 2, 3])


def test_take_fx_negative_index_is_rejected_without_calling_reaper(reaper):
    result = run(srv.take_fx_get_count(0, -1, 2))
    assert result["ok"] is False
    assert "item_index" in result["error"]
    assert reaper.calls == []  # validation short-circuits before the bridge


def test_take_fx_negative_fx_index_is_rejected(reaper):
    result = run(srv.take_fx_get_param(0, 1, 2, -3, 4))
    assert result["ok"] is False
    assert "fx_index" in result["error"]
    assert reaper.calls == []


# --- Takes & comping (v1.3.0 Phase B) ---

def test_get_takes_marshalling(reaper):
    run(srv.get_takes(0, 1))
    assert reaper.last == ("GetTakes", [0, 1])


def test_get_active_take_marshalling(reaper):
    run(srv.get_active_take(0, 1))
    assert reaper.last == ("GetActiveTakeIndex", [0, 1])


def test_set_active_take_marshalling(reaper):
    run(srv.set_active_take(0, 1, 2))
    assert reaper.last == ("SetActiveTakeByIndex", [0, 1, 2])


def test_explode_takes_marshalling(reaper):
    run(srv.explode_takes(0, 1))
    assert reaper.last == ("ExplodeTakes", [0, 1])


def test_crop_to_active_take_marshalling(reaper):
    run(srv.crop_to_active_take(0, 1))
    assert reaper.last == ("CropToActiveTake", [0, 1])


def test_delete_take_marshalling(reaper):
    run(srv.delete_take(0, 1, 2))
    assert reaper.last == ("DeleteTakeByIndex", [0, 1, 2])


def test_select_comp_lane_marshalling(reaper):
    run(srv.select_comp_lane(3, 1))
    assert reaper.last == ("SelectCompLane", [3, 1])


def test_takes_negative_index_rejected_before_bridge(reaper):
    result = run(srv.delete_take(0, 1, -2))
    assert result["ok"] is False
    assert "take_index" in result["error"]
    assert reaper.calls == []

    result = run(srv.select_comp_lane(0, -1))
    assert result["ok"] is False
    assert "lane_index" in result["error"]
    assert reaper.calls == []


# --- v1.3.1: fixed call paths (PR #1, @nuxero) ---
# These pin tools to their explicit bridge handlers. The old raw-API names fell through
# to the generic bridge fallback, which cannot resolve pointers (the tools never worked).

def test_create_midi_item_uses_dsl_handler(reaper):
    run(srv.create_midi_item(0, 1.0, 4.0))
    assert reaper.last == ("CreateMIDIItem", [0, 1.0, 5.0])  # start, end = pos + length


def test_add_midi_note_beats_to_seconds(reaper):
    # Recorder returns ret=0 for Master_GetTempo -> falls back to 120 BPM (1 beat = 0.5s)
    run(srv.add_midi_note(0, 1, 60, 100, start_beat=2.0, length_beats=1.0))
    func, args = reaper.last
    assert func == "InsertMIDINote"
    assert args[:3] == [0, 1, 60]
    assert args[3] == pytest.approx(1.0)   # 2 beats @ 120 BPM
    assert args[4] == pytest.approx(0.5)   # 1 beat @ 120 BPM
    assert args[5:] == [100, 0]


def test_add_midi_notes_batch_beats(reaper):
    notes = [{"pitch": 36, "velocity": 110, "start_beat": 1.0, "length_beats": 0.5}]
    result = run(srv.add_midi_notes_batch(0, 0, notes))
    assert result["notes_added"] == 1
    func, args = reaper.last
    assert func == "InsertMIDINote"
    assert args[3] == pytest.approx(0.5)    # 1 beat @ 120 BPM
    assert args[4] == pytest.approx(0.25)   # 0.5 beat @ 120 BPM


def test_get_midi_notes_handler(reaper):
    run(srv.get_midi_notes(0, 1))
    assert reaper.last == ("GetMIDINotes", [0, 1])


def test_set_item_tools_use_item_info_handler(reaper):
    run(srv.set_item_position(0, 1, 2.5))
    assert reaper.last == ("SetMediaItemInfo_Value", [0, 1, "D_POSITION", 2.5])
    run(srv.set_item_mute(0, 1, True))
    assert reaper.last == ("SetMediaItemInfo_Value", [0, 1, "B_MUTE", 1])


def test_get_track_peak_handler(reaper):
    run(srv.get_track_peak(0, 1))
    assert reaper.last == ("Track_GetPeakInfo", [0, 1])


# --- v1.3.1: new tools (PR #1, @nuxero) ---

def test_track_fx_add_by_name_position(reaper):
    run(srv.track_fx_add_by_name(0, "ReaEQ"))
    assert reaper.last == ("TrackFX_AddByName", [0, "ReaEQ", False, -1])
    run(srv.track_fx_add_by_name(0, "ReaEQ", position=0))
    assert reaper.last == ("TrackFX_AddByName", [0, "ReaEQ", False, -1000])
    run(srv.track_fx_add_by_name(0, "ReaEQ", position=2))
    assert reaper.last == ("TrackFX_AddByName", [0, "ReaEQ", False, -1002])


def test_track_fx_move(reaper):
    run(srv.track_fx_move(0, 2, 0))
    assert reaper.last == ("TrackFX_CopyToTrack", [0, 2, 0, 0, True])


def test_peak_hold_and_clear(reaper):
    run(srv.get_track_peak_hold(3, 1))
    assert reaper.last == ("Track_GetPeakHoldDB", [3, 1])
    run(srv.clear_all_peak_indicators())
    assert reaper.last == ("ClearAllPeakIndicators", [])


def test_master_send(reaper):
    run(srv.get_track_master_send(2))
    assert reaper.last == ("GetMediaTrackInfo_Value", [2, "B_MAINSEND"])
    run(srv.set_track_master_send(2, False))
    assert reaper.last == ("SetMediaTrackInfo_Value", [2, "B_MAINSEND", 0])


# --- v1.3.2: explicit handlers for the remaining generic-fallback victims ---

def test_midi_item_tools_marshalling(reaper):
    run(srv.delete_midi_note(0, 1, 2))
    assert reaper.last == ("MIDI_DeleteNote", [0, 1, 2])
    run(srv.clear_midi_item(0, 1))
    assert reaper.last == ("ClearMIDIItem", [0, 1])
    run(srv.get_midi_item(0, 1))
    assert reaper.last == ("GetMIDIItemInfo", [0, 1])


def test_item_edit_tools_marshalling(reaper):
    run(srv.split_item(0, 1, 2.5))
    assert reaper.last == ("SplitMediaItem", [0, 1, 2.5])
    run(srv.duplicate_item(0, 1))
    assert reaper.last == ("DuplicateItem", [0, 1])


def test_envelope_tools_marshalling(reaper):
    run(srv.add_envelope_point(0, "Volume", 1.5, 0.7))
    assert reaper.last == ("InsertEnvelopePoint", [0, "Volume", 1.5, 0.7, 0, 0, False, False])
    run(srv.get_envelope_point_count(0, "Volume"))
    assert reaper.last == ("CountEnvelopePoints", [0, "Volume"])
    run(srv.get_envelope_points(0, "Volume"))
    assert reaper.last == ("GetEnvelopePoints", [0, "Volume"])
    run(srv.delete_envelope_point(0, "Volume", 3))
    assert reaper.last == ("DeleteEnvelopePoint", [0, "Volume", 3])
    run(srv.clear_envelope(0, "Pan"))
    assert reaper.last == ("ClearEnvelope", [0, "Pan"])
    run(srv.arm_track_envelope(0, "Volume", True))
    assert reaper.last == ("SetEnvelopeArm", [0, "Volume", True])


def test_undo_state_and_time_signature(reaper):
    run(srv.get_undo_state())
    assert reaper.last == ("GetUndoState", [])
    run(srv.set_time_signature(6, 8))
    assert reaper.last == ("SetTimeSignature", [6, 8])


def test_render_project_none_becomes_sentinels(reaper):
    run(srv.render_project("C:/tmp/out.wav"))
    assert reaper.last == ("RenderProject", ["C:/tmp/out.wav", -1, -1, 0, False])
    run(srv.render_project("C:/tmp/out.wav", 1.0, 3.0, 0.5, overwrite=True))
    assert reaper.last == ("RenderProject", ["C:/tmp/out.wav", 1.0, 3.0, 0.5, True])


def test_render_region_documented_error(reaper):
    """Fails usefully without reaching the bridge, and names no version.

    It used to promise the render suite "for v1.9". The roadmap said v1.9 in two places,
    the renumbering moved the render suite to a different minor, and this test pinned the
    promise rather than the behaviour, so the stale version shipped to users on every
    call with a green suite. A roadmap slot is not a contract; the workaround is.
    """
    result = run(srv.render_region(0, "C:/tmp/r.wav"))
    assert result["ok"] is False
    assert "not implemented" in result["error"].lower()
    assert "get_regions" in result["error"] and "render_project" in result["error"]
    assert not re.search(r"v?\d+\.\d+", result["error"]), (
        f"names a version that will drift: {result['error']}"
    )
    assert reaper.calls == []  # never reaches the bridge


def test_insert_audio_file_sends_track_and_position(reaper):
    """It used to call InsertMedia(file, mode), which takes TWO arguments.

    track_index and position fell off the end and were never sent, so the file landed
    on whatever track was selected, at the edit cursor, and the tool returned ok.
    """
    run(srv.insert_audio_file(2, "C:/audio/kick.wav", 1.5))
    assert reaper.last == ("InsertAudioFile", [2, "C:/audio/kick.wav", 1.5])


def test_insert_audio_file_rejects_a_negative_track(reaper):
    result = run(srv.insert_audio_file(-1, "C:/audio/kick.wav", 0.0))
    assert result["ok"] is False
    assert "track_index" in result["error"]


def test_track_fx_get_list_calls_the_dedicated_handler(reaper):
    """It used to call GetTrackInfo, whose payload has fx_names and no index/enabled.

    From @SNChicago's PR #9. This pins the Python side only; the response shape itself
    is pinned in tests/test_bridge_encoder.py, which runs the real Lua.
    """
    run(srv.track_fx_get_list(0))
    assert reaper.last == ("GetTrackFXList", [0])


def test_track_fx_get_list_passes_master_through_unmodified(reaper):
    """-1 must survive the Python layer; master resolution itself happens in Lua.

    Cheap guard against someone later adding _validate_indices here, which rejects
    negatives and would break the master case for every FX read.
    """
    run(srv.track_fx_get_list(-1))
    assert reaper.last == ("GetTrackFXList", [-1])


def test_create_project_takes_no_name(reaper):
    import inspect
    assert "name" not in inspect.signature(srv.create_project).parameters


def test_create_project_makes_exactly_one_call_and_never_saves(reaper):
    """The old body fired a stray Main_SaveProject, which is a plain Ctrl+S.

    Asserting the FULL call list is what makes this test able to fail: asserting only
    that Main_OnCommand was sent passes identically before and after the fix, because
    the old body sent that first too.
    """
    run(srv.create_project())
    assert reaper.calls == [("Main_OnCommand", [40023, 0])]


def test_create_bus_names_the_bus_with_correct_arity(reaper):
    """The bridge reads args[1] as the track, so a leading 0 shifted every argument.

    setnewvalue then received the NAME, which coerces to false, making the call a read:
    the bus was never named and the tool reported success anyway. `ret` is deliberately
    non-zero here so a correct call is distinguishable from the buggy one.
    """
    reaper.response = {"ok": True, "ret": 3}
    run(srv.create_bus("Drum Bus", [0, 1]))
    renames = [c for c in reaper.calls if c[0] == "GetSetMediaTrackInfo_String"]
    assert renames, "create_bus never attempted to name the bus"
    assert renames[0] == ("GetSetMediaTrackInfo_String", [3, "P_NAME", "Drum Bus", True])


def test_add_parallel_compression_names_the_bus_with_correct_arity(reaper):
    reaper.response = {"ok": True, "ret": 3}
    run(srv.add_parallel_compression(0))
    renames = [c for c in reaper.calls if c[0] == "GetSetMediaTrackInfo_String"]
    assert renames, "add_parallel_compression never attempted to name the bus"
    assert renames[0] == ("GetSetMediaTrackInfo_String", [3, "P_NAME", "Parallel Comp Bus", True])


def test_create_bus_reports_a_failed_rename_instead_of_claiming_success(monkeypatch):
    async def fake(func, *args):
        if func == "GetSetMediaTrackInfo_String":
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": 3}

    monkeypatch.setattr(srv, "reaper_call", fake)
    result = run(srv.create_bus("Drum Bus", [0]))
    assert result["ok"] is False
    assert "naming it failed" in result["error"]
    # The caller still learns which track was left behind.
    assert result["bus_track_index"] == 3


def test_add_parallel_compression_reports_a_failed_rename(monkeypatch):
    async def fake(func, *args):
        if func == "GetSetMediaTrackInfo_String":
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": 3}

    monkeypatch.setattr(srv, "reaper_call", fake)
    result = run(srv.add_parallel_compression(0))
    assert result["ok"] is False
    assert "naming it failed" in result["error"]
    assert result["bus_track_index"] == 3


def test_fx_preset_tools_marshalling(reaper):
    run(srv.get_fx_presets(0, 1))
    assert reaper.last == ("TrackFX_GetPresetList", [0, 1])
    run(srv.save_fx_preset(0, 1, "My Preset"))
    assert reaper.last == ("TrackFX_SavePreset", [0, 1, "My Preset"])
