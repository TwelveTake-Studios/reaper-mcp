"""Tests for the server/bridge contract: path resolution and the version handshake.

Both were unguarded before 1.6.1, and both failed silently rather than loudly:

* The bridge directory was hardcoded to a Windows ``%APPDATA%`` string. Off Windows it
  never expanded, became one relative directory name, and the server spent every call
  talking to a folder REAPER had never heard of.
* Nothing checked that the deployed Lua matched the server. REAPER runs the copy in its
  own Scripts folder, which is deployed by hand, so upgrading the package left the two
  halves silently mismatched.
"""

import sys
from pathlib import Path

import pytest

import reaper_mcp_server as srv


def run(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_version_cache():
    """The probe verdict is cached module-wide; each test needs a clean slate."""
    srv._bridge_check["done"] = False
    srv._bridge_check["error"] = None
    yield
    srv._bridge_check["done"] = False
    srv._bridge_check["error"] = None


# --- version parsing --------------------------------------------------------

def test_version_tuple_orders_correctly():
    assert srv.version_tuple("1.6.1") > srv.version_tuple("1.6.0")
    assert srv.version_tuple("1.10.0") > srv.version_tuple("1.9.9")
    assert srv.version_tuple("1.6.1") == srv.version_tuple("1.6.1")


def test_version_tuple_tolerates_suffixes():
    # A hand-edited bridge might carry "1.6.1-dave" and must not crash the probe.
    assert srv.version_tuple("1.6.1-dave") == (1, 6, 1)
    assert srv.version_tuple("") == (0,)


# --- bridge directory resolution -------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows path shape")
def test_windows_path_is_byte_identical_to_pre_161():
    """Existing Windows installs must resolve to EXACTLY the same directory.

    This is the one regression that would break working setups, so it is asserted
    against the literal pre-1.6.1 expression rather than a re-derivation.
    """
    import os
    legacy = Path(os.path.expandvars(r"%APPDATA%\REAPER\Scripts\mcp_bridge_data"))
    assert srv.default_bridge_dir() == legacy
    assert str(srv.default_bridge_dir()) == str(legacy)


def test_macos_path(monkeypatch, tmp_path):
    monkeypatch.setattr(srv.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert srv.default_bridge_dir() == (
        tmp_path / "Library" / "Application Support" / "REAPER" / "Scripts" / "mcp_bridge_data"
    )


def test_linux_path_prefers_xdg_config(monkeypatch, tmp_path):
    monkeypatch.setattr(srv.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert srv.default_bridge_dir() == (
        tmp_path / ".config" / "REAPER" / "Scripts" / "mcp_bridge_data"
    )


def test_linux_falls_back_to_legacy_dotreaper(monkeypatch, tmp_path):
    # Older and portable installs keep the resource dir at ~/.reaper.
    (tmp_path / ".reaper").mkdir()
    monkeypatch.setattr(srv.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert srv.default_bridge_dir() == (
        tmp_path / ".reaper" / "Scripts" / "mcp_bridge_data"
    )


def test_resolved_path_is_absolute_and_has_no_percent(monkeypatch, tmp_path):
    """The exact shape that broke macOS and Linux, asserted directly."""
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(srv.sys, "platform", platform)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        resolved = str(srv.default_bridge_dir())
        assert "%" not in resolved
        assert Path(resolved).is_absolute()


# --- the refuse-to-run guard ------------------------------------------------

def test_unexpanded_variable_is_rejected():
    problem = srv.bridge_dir_problem(Path(r"%APPDATA%\REAPER\Scripts\mcp_bridge_data"))
    assert problem is not None
    assert "REAPER_BRIDGE_DIR" in problem


def test_relative_path_is_rejected():
    assert srv.bridge_dir_problem(Path("mcp_bridge_data")) is not None


def test_good_path_is_accepted(tmp_path):
    assert srv.bridge_dir_problem(tmp_path) is None


def test_file_transport_refuses_a_broken_bridge_dir(monkeypatch):
    """It must refuse rather than mkdir a junk folder and time out against it forever."""
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", "bad bridge dir")
    result = run(srv.reaper_call_file("CountTracks", [0]))
    assert result == {"ok": False, "error": "bad bridge dir"}


# --- the version handshake --------------------------------------------------

def _fake_dispatch(response):
    async def _dispatch(func, args):
        _dispatch.calls.append((func, args))
        return response
    _dispatch.calls = []
    return _dispatch


def test_current_bridge_passes(monkeypatch):
    monkeypatch.setattr(srv, "dispatch", _fake_dispatch({"ok": True, "version": srv.MIN_BRIDGE_VERSION}))
    assert run(srv.ensure_bridge_current()) is None


def test_newer_bridge_passes(monkeypatch):
    monkeypatch.setattr(srv, "dispatch", _fake_dispatch({"ok": True, "version": "1.9.0"}))
    assert run(srv.ensure_bridge_current()) is None


def test_older_bridge_reporting_its_version_is_refused(monkeypatch):
    monkeypatch.setattr(srv, "dispatch", _fake_dispatch({"ok": True, "version": "1.6.0"}))
    verdict = run(srv.ensure_bridge_current())
    assert verdict["ok"] is False
    assert "out of date" in verdict["error"]
    assert "--install-bridge" in verdict["hint"]


def test_pre_handshake_bridge_is_refused(monkeypatch):
    """A bridge older than 1.6.1 has no GetBridgeVersion handler at all."""
    monkeypatch.setattr(srv, "dispatch", _fake_dispatch(
        {"ok": False, "error": "Unknown function: GetBridgeVersion"}
    ))
    verdict = run(srv.ensure_bridge_current())
    assert verdict["ok"] is False
    assert "out of date" in verdict["error"]


def test_timeout_is_not_a_version_verdict(monkeypatch):
    """REAPER being closed must not be misreported as a stale bridge.

    It also must not be cached, or one call made before REAPER started would poison
    the verdict for the rest of the session.
    """
    fake = _fake_dispatch({"ok": False, "error": "File request timed out after 5s"})
    monkeypatch.setattr(srv, "dispatch", fake)
    assert run(srv.ensure_bridge_current()) is None
    assert srv._bridge_check["done"] is False

    monkeypatch.setattr(srv, "dispatch", _fake_dispatch({"ok": True, "version": "1.6.1"}))
    assert run(srv.ensure_bridge_current()) is None


def test_probe_runs_once_then_caches(monkeypatch):
    fake = _fake_dispatch({"ok": True, "version": "1.6.1"})
    monkeypatch.setattr(srv, "dispatch", fake)
    run(srv.ensure_bridge_current())
    run(srv.ensure_bridge_current())
    run(srv.ensure_bridge_current())
    assert len(fake.calls) == 1


def test_stale_bridge_short_circuits_a_real_tool_call(monkeypatch):
    """The gate must actually stop the call, not just report alongside it."""
    fake = _fake_dispatch({"ok": False, "error": "Unknown function: GetBridgeVersion"})
    monkeypatch.setattr(srv, "dispatch", fake)
    result = run(srv.reaper_call("DeleteTrack", 0))
    assert result["ok"] is False
    assert "out of date" in result["error"]
    # Only the probe went out. The DeleteTrack never reached REAPER.
    assert [c[0] for c in fake.calls] == ["GetBridgeVersion"]


def test_version_probe_itself_is_not_gated(monkeypatch):
    """Guards against infinite recursion in the gate."""
    fake = _fake_dispatch({"ok": True, "version": "1.6.1"})
    monkeypatch.setattr(srv, "dispatch", fake)
    run(srv.reaper_call("GetBridgeVersion"))
    assert [c[0] for c in fake.calls] == ["GetBridgeVersion"]
