import importlib.util
import sys
from pathlib import Path

import pytest

import reaper_mcp_server as srv

SCRIPT = Path(__file__).resolve().parent.parent / "test_connection.py"


def load_script():
    spec = importlib.util.spec_from_file_location("connection_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("platform, parts", [
    ("darwin", ("Library", "Application Support", "REAPER", "Scripts", "mcp_bridge_data")),
    ("linux", (".config", "REAPER", "Scripts", "mcp_bridge_data")),
])
def test_the_connection_script_finds_the_bridge_off_windows(monkeypatch, tmp_path, platform, parts):
    monkeypatch.delenv("REAPER_BRIDGE_DIR", raising=False)
    monkeypatch.setattr(srv.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_script().BRIDGE_DIR == tmp_path.joinpath(*parts)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path shape")
def test_the_connection_script_finds_the_bridge_on_windows(monkeypatch):
    monkeypatch.delenv("REAPER_BRIDGE_DIR", raising=False)
    assert load_script().BRIDGE_DIR == srv.default_bridge_dir()


def test_the_connection_script_honors_reaper_bridge_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("REAPER_BRIDGE_DIR", str(tmp_path))
    assert load_script().BRIDGE_DIR == tmp_path
