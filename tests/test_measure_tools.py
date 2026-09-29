import asyncio

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("tool, wire", [
    (srv.measure_loudness, "MeasureLoudness"),
    (srv.measure_spectrum, "MeasureSpectrum"),
])
def test_defaults_measure_the_whole_master(reaper, tool, wire):
    run(tool())
    assert reaper.last == (wire, [-1, -1, -1, -1])
    assert reaper.last_timeout == srv.RENDER_TIMEOUT


@pytest.mark.parametrize("tool, wire", [
    (srv.measure_loudness, "MeasureLoudness"),
    (srv.measure_spectrum, "MeasureSpectrum"),
])
def test_targets_and_range_reach_the_bridge(reaper, tool, wire):
    run(tool(track_index=3, item_index=0))
    assert reaper.last == (wire, [3, 0, -1, -1])
    run(tool(track_index=2, start_time=0.0, end_time=12.5))
    assert reaper.last == (wire, [2, -1, 0.0, 12.5])


def test_bridge_reply_passes_through(reaper):
    reaper.response = {"ok": True, "integrated_lufs": -14.2, "true_peak_dbtp": -1.1}
    assert run(srv.measure_loudness()) == {"ok": True, "integrated_lufs": -14.2, "true_peak_dbtp": -1.1}


def test_both_tools_are_read_only():
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("measure_loudness", "measure_spectrum"):
        assert tools[name].annotations.readOnlyHint is True
