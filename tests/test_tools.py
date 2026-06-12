"""Representative tool tests across domains, with REAPER mocked.

These verify the two things every glue tool must get right: the REAPER function name +
argument marshalling it sends, and that it returns the bridge response unchanged.
"""

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
    result = run(srv.render_region(0, "C:/tmp/r.wav"))
    assert result["ok"] is False
    assert "v1.9" in result["error"]
    assert reaper.calls == []  # never reaches the bridge


def test_fx_preset_tools_marshalling(reaper):
    run(srv.get_fx_presets(0, 1))
    assert reaper.last == ("TrackFX_GetPresetList", [0, 1])
    run(srv.save_fx_preset(0, 1, "My Preset"))
    assert reaper.last == ("TrackFX_SavePreset", [0, 1, "My Preset"])
