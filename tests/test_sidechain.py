"""The sidechain tools must produce a sidechain that actually reaches the detector."""
import asyncio

import pytest

import reaper_mcp_server as srv

AUX = 2 / 1084


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def project(monkeypatch, batch_through):
    state = {"nchan": 2, "sends": 0}
    calls = []

    async def call(func, *args, timeout=None):
        calls.append((func, list(args)))
        if func == "GetTrackNumSends":
            return {"ok": True, "ret": state["sends"]}
        if func == "GetMediaTrackInfo_Value":
            return {"ok": True, "ret": state["nchan"]}
        if func == "CreateTrackSend":
            return {"ok": True, "ret": state["sends"]}
        return {"ok": True}

    monkeypatch.setattr(srv, "reaper_call", call)
    monkeypatch.setattr(srv, "reaper_batch", batch_through(call))
    state["calls"] = calls
    return state


def sent(project, func):
    return [args for f, args in project["calls"] if f == func]


def test_send_widens_a_stereo_destination_before_routing_to_3_4(project):
    assert run(srv.setup_sidechain_send(0, 1))["ok"] is True
    funcs = [f for f, _ in project["calls"]]
    assert sent(project, "SetMediaTrackInfo_Value") == [[1, "I_NCHAN", 4]]
    assert funcs.index("SetMediaTrackInfo_Value") < funcs.index("CreateTrackSend")
    assert sent(project, "SetTrackSendInfo_Value") == [[0, 0, 0, "I_DSTCHAN", 2]]


def test_send_leaves_a_wider_destination_alone(project):
    project["nchan"] = 6
    assert run(srv.setup_sidechain_send(0, 1))["ok"] is True
    assert sent(project, "SetMediaTrackInfo_Value") == []


def test_send_reports_the_index_it_created_when_widening(project):
    project["sends"] = 3
    result = run(srv.setup_sidechain_send(0, 1))
    assert result["ok"] is True
    assert result["send_index"] == 3


def test_missing_destination_is_refused_before_anything_is_created(project, monkeypatch):
    inner = srv.reaper_call

    async def call(func, *args, timeout=None):
        if func == "GetMediaTrackInfo_Value":
            return {"ok": False, "error": "Track not found at index 9"}
        return await inner(func, *args)

    monkeypatch.setattr(srv, "reaper_call", call)
    result = run(srv.setup_sidechain_send(0, 9))
    assert result["ok"] is False
    assert "Track not found" in result["error"]
    assert sent(project, "CreateTrackSend") == []


def test_compression_setup_selects_aux_on_the_detector(project):
    assert run(srv.setup_sidechain_compression(0, 1, 2))["ok"] is True
    assert sent(project, "SetMediaTrackInfo_Value") == [[1, "I_NCHAN", 4]]
    assert sent(project, "TrackFX_SetParam") == [[1, 2, 8, pytest.approx(AUX)]]


def test_configure_reacomp_selects_aux_not_the_top_of_the_range(project):
    run(srv.configure_reacomp_sidechain(1, 2))
    assert sent(project, "TrackFX_SetParam") == [[1, 2, 8, pytest.approx(AUX)]]


def test_configure_reacomp_main_input_is_zero(project):
    run(srv.configure_reacomp_sidechain(1, 2, use_sidechain=False))
    assert sent(project, "TrackFX_SetParam") == [[1, 2, 8, 0.0]]
