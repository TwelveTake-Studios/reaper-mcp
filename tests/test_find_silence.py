import asyncio
import math

import pytest

import reaper_mcp_server as srv


def run(coro):
    return asyncio.run(coro)


def test_find_silence_is_a_read():
    assert "find_silence" not in srv.UNDO_STEP_TOOLS
    assert srv.mcp._tool_manager.get_tool("find_silence").annotations.readOnlyHint is True


def test_defaults_scan_the_whole_track_at_minus_40_and_half_a_second(reaper):
    run(srv.find_silence(2))
    assert reaper.last == ("FindSilence", [2, -1, -40, 0.5])
    assert reaper.last_timeout == srv.RENDER_TIMEOUT


def test_an_item_and_both_settings_are_passed_through(reaper):
    run(srv.find_silence(2, 3, -50, 1.25))
    assert reaper.last == ("FindSilence", [2, 3, -50, 1.25])


def test_the_floor_itself_is_accepted(reaper):
    run(srv.find_silence(0, min_length_s=srv.SILENCE_MIN_LENGTH_S))
    assert reaper.last == ("FindSilence", [0, -1, -40, 0.05])


@pytest.mark.parametrize("args, kwargs, fragment", [
    ((-1,), {}, "track_index must be >= 0"),
    ((0, -1), {}, "item_index must be >= 0"),
    ((0,), {"threshold_db": math.nan}, "threshold_db must be a number"),
    ((0,), {"threshold_db": math.inf}, "threshold_db must be a number"),
    ((0,), {"min_length_s": 0.049}, "min_length_s must be at least 0.05"),
    ((0,), {"min_length_s": 0}, "min_length_s must be at least 0.05"),
    ((0,), {"min_length_s": -1}, "min_length_s must be at least 0.05"),
    ((0,), {"min_length_s": math.nan}, "min_length_s must be at least 0.05"),
])
def test_find_silence_refuses_before_reaching_reaper(reaper, args, kwargs, fragment):
    res = run(srv.find_silence(*args, **kwargs))
    assert res["ok"] is False
    assert fragment in res["error"]
    assert reaper.calls == []


def test_the_bridge_answer_passes_through_unchanged(reaper):
    reaper.response = {"ok": True, "items_scanned": 1, "skipped": [],
                       "silences": [{"item_index": 0, "start": 12.5, "end": 13.1, "length": 0.6,
                                     "at_item_start": False, "at_item_end": False, "beyond_source": False}],
                       "threshold_db": -40, "min_length_s": 0.5, "scan_ms": 3}
    assert run(srv.find_silence(0)) == {
        "ok": True, "items_scanned": 1, "skipped": [],
        "silences": [{"item_index": 0, "start": 12.5, "end": 13.1, "length": 0.6,
                      "at_item_start": False, "at_item_end": False, "beyond_source": False}],
        "threshold_db": -40, "min_length_s": 0.5, "scan_ms": 3}
