import asyncio
import sys

import pytest

import reaper_mcp_server as srv

lupa = pytest.importorskip("lupa")


@pytest.fixture(autouse=True)
def reset_version_cache():
    srv._bridge_check["done"] = False
    srv._bridge_check["error"] = None
    yield
    srv._bridge_check["done"] = False
    srv._bridge_check["error"] = None


def _target(folder):
    return folder / srv.BRIDGE_SCRIPT_NAME


def _startup(folder):
    return folder / "__startup.lua"


def test_enable_creates_startup_with_one_block(tmp_path):
    srv.enable_autostart(tmp_path, _target(tmp_path))
    text = _startup(tmp_path).read_text(encoding="utf-8")
    assert text.count(srv.AUTOSTART_BEGIN) == 1
    assert text.count(srv.AUTOSTART_END) == 1
    assert 'reaper.GetResourcePath() .. "/Scripts/reaper_mcp_bridge.lua"' in text
    assert "pcall(dofile" in text


def test_enable_keeps_the_users_own_lines_and_backs_up(tmp_path):
    _startup(tmp_path).write_text('reaper.ShowConsoleMsg("mine")\n', encoding="utf-8")
    srv.enable_autostart(tmp_path, _target(tmp_path))
    text = _startup(tmp_path).read_text(encoding="utf-8")
    assert text.startswith('reaper.ShowConsoleMsg("mine")\n')
    assert srv.AUTOSTART_BEGIN in text
    assert list(tmp_path.glob("__startup.lua.bak-*"))


def test_enable_twice_leaves_one_block(tmp_path):
    srv.enable_autostart(tmp_path, _target(tmp_path))
    first = _startup(tmp_path).read_text(encoding="utf-8")
    srv.enable_autostart(tmp_path, _target(tmp_path))
    assert _startup(tmp_path).read_text(encoding="utf-8") == first


def test_remove_takes_out_only_our_block(tmp_path):
    _startup(tmp_path).write_text("before()\n", encoding="utf-8")
    srv.enable_autostart(tmp_path, _target(tmp_path))
    with open(_startup(tmp_path), "a", encoding="utf-8", newline="\n") as f:
        f.write("after()\n")
    assert srv.disable_autostart(tmp_path) == 0
    text = _startup(tmp_path).read_text(encoding="utf-8")
    assert srv.AUTOSTART_BEGIN not in text and srv.AUTOSTART_END not in text
    assert "before()" in text and "after()" in text
    assert not srv.autostart_enabled(tmp_path)


def test_remove_when_absent_touches_nothing(tmp_path):
    _startup(tmp_path).write_text("mine()\n", encoding="utf-8")
    assert srv.disable_autostart(tmp_path) == 0
    assert _startup(tmp_path).read_text(encoding="utf-8") == "mine()\n"
    assert not list(tmp_path.glob("__startup.lua.bak-*"))


def test_explicit_folder_uses_the_absolute_path(tmp_path):
    srv.enable_autostart(tmp_path, _target(tmp_path), explicit_dir=True)
    text = _startup(tmp_path).read_text(encoding="utf-8")
    expected = str(_target(tmp_path).resolve()).replace("\\", "/")
    assert f'pcall(dofile, "{expected}")' in text


def _run_startup(tmp_path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().RESOURCE = str(tmp_path.parent).replace("\\", "/")
    lua.execute("console = {}\nreaper = {GetResourcePath = function() return RESOURCE end,"
                " ShowConsoleMsg = function(m) console[#console + 1] = m end}")
    lua.execute(_startup(tmp_path).read_text(encoding="utf-8"))
    console = lua.globals().console
    return lua, [console[i] for i in range(1, len(console) + 1)]


def test_startup_block_survives_a_missing_bridge(tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    srv.enable_autostart(scripts, _target(scripts))
    _, console = _run_startup(scripts)
    assert len(console) == 1 and "did not start" in console[0]


def test_startup_block_runs_the_bridge(tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    _target(scripts).write_text("bridge_ran = true\n", encoding="utf-8")
    srv.enable_autostart(scripts, _target(scripts))
    lua, console = _run_startup(scripts)
    assert lua.globals().bridge_ran is True
    assert console == []


def test_install_bridge_command_passes_folder_and_autostart(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(srv, "install_bridge", lambda d=None, autostart=False: seen.update(d=d, a=autostart) or 0)
    monkeypatch.setattr(sys, "argv", ["twelvetake-reaper-mcp", "--install-bridge", str(tmp_path), "--autostart"])
    with pytest.raises(SystemExit):
        srv.main()
    assert seen == {"d": tmp_path, "a": True}


def _install_offline(monkeypatch, tmp_path):
    async def not_running():
        return {"state": "not_running"}
    monkeypatch.setattr(srv, "reload_running_bridge", not_running)
    source = srv.bundled_bridge_script()
    return source, _target(tmp_path)


def test_installing_the_same_bridge_again_makes_no_backup(monkeypatch, tmp_path, capsys):
    source, target = _install_offline(monkeypatch, tmp_path)
    assert srv.install_bridge(tmp_path) == 0
    assert srv.install_bridge(tmp_path) == 0
    assert target.read_bytes() == source.read_bytes()
    assert not list(tmp_path.glob(f"{srv.BRIDGE_SCRIPT_NAME}.bak-*"))
    assert "already this version" in capsys.readouterr().out


def test_installing_over_a_different_bridge_backs_it_up(monkeypatch, tmp_path):
    source, target = _install_offline(monkeypatch, tmp_path)
    target.write_text("-- an older or edited bridge\n", encoding="utf-8")
    assert srv.install_bridge(tmp_path) == 0
    assert target.read_bytes() == source.read_bytes()
    backups = list(tmp_path.glob(f"{srv.BRIDGE_SCRIPT_NAME}.bak-*"))
    assert [b.read_text(encoding="utf-8") for b in backups] == ["-- an older or edited bridge\n"]


def _dispatch_script(replies):
    calls = []

    async def fake(func, args, timeout=None):
        calls.append(func)
        return replies[func].pop(0) if isinstance(replies[func], list) else replies[func]
    return fake, calls


def test_reload_reports_not_running(monkeypatch):
    fake, _ = _dispatch_script({"GetBridgeVersion": {"ok": False, "error": "timeout"}})
    monkeypatch.setattr(srv, "dispatch", fake)
    assert asyncio.run(srv.reload_running_bridge())["state"] == "not_running"


def test_reload_reports_a_bridge_that_cannot_reload(monkeypatch):
    fake, calls = _dispatch_script({"GetBridgeVersion": {"ok": True, "version": "1.7.6"}})
    monkeypatch.setattr(srv, "dispatch", fake)
    result = asyncio.run(srv.reload_running_bridge())
    assert result == {"state": "cannot_reload", "version": "1.7.6"}
    assert "ReloadBridge" not in calls


def test_reload_reports_the_new_version(monkeypatch):
    fake, _ = _dispatch_script({
        "GetBridgeVersion": [{"ok": True, "version": "1.7.8", "can_reload": True},
                             {"ok": True, "version": "1.7.9", "can_reload": True}],
        "ReloadBridge": {"ok": True, "reloading": True, "path": "/x/reaper_mcp_bridge.lua"},
    })
    monkeypatch.setattr(srv, "dispatch", fake)
    result = asyncio.run(srv.reload_running_bridge(settle_seconds=2))
    assert result["state"] == "reloaded"
    assert (result["previous"], result["version"]) == ("1.7.8", "1.7.9")


def test_stale_bridge_is_reloaded_before_it_is_refused(monkeypatch):
    fake, _ = _dispatch_script({"GetBridgeVersion": {"ok": True, "version": "1.7.7", "can_reload": True}})
    monkeypatch.setattr(srv, "dispatch", fake)

    async def reloaded():
        return {"state": "reloaded", "version": srv.MIN_BRIDGE_VERSION, "previous": "1.7.7"}
    monkeypatch.setattr(srv, "reload_running_bridge", reloaded)
    assert asyncio.run(srv.ensure_bridge_current()) is None


def test_stale_bridge_is_refused_when_reloading_changes_nothing(monkeypatch):
    fake, _ = _dispatch_script({"GetBridgeVersion": {"ok": True, "version": "1.7.7", "can_reload": True}})
    monkeypatch.setattr(srv, "dispatch", fake)

    async def unchanged():
        return {"state": "unchanged", "version": "1.7.7", "previous": "1.7.7"}
    monkeypatch.setattr(srv, "reload_running_bridge", unchanged)
    verdict = asyncio.run(srv.ensure_bridge_current())
    assert verdict and verdict["ok"] is False and "out of date" in verdict["error"]


def test_stale_bridge_without_reload_is_not_asked_to_reload(monkeypatch):
    fake, _ = _dispatch_script({"GetBridgeVersion": {"ok": True, "version": "1.7.6"}})
    monkeypatch.setattr(srv, "dispatch", fake)

    async def must_not_run():
        raise AssertionError("reload attempted on a bridge that cannot reload")
    monkeypatch.setattr(srv, "reload_running_bridge", must_not_run)
    verdict = asyncio.run(srv.ensure_bridge_current())
    assert verdict and verdict["ok"] is False


def test_a_same_version_reload_is_reported_as_a_reload(capsys, tmp_path):
    target = _target(tmp_path)
    srv.report_reload({"state": "unchanged", "version": "1.7.8", "previous": "1.7.8", "path": str(target)},
                      target, autostart=False)
    out = capsys.readouterr().out
    assert "reloaded its script" in out and "1.7.8" in out


def test_a_reload_from_another_file_says_so(capsys, tmp_path):
    target = _target(tmp_path)
    srv.report_reload({"state": "unchanged", "version": "1.7.8", "previous": "1.7.8",
                       "path": str(tmp_path / "elsewhere" / "reaper_mcp_bridge.lua")}, target, autostart=False)
    out = capsys.readouterr().out
    assert "elsewhere" in out and "still 1.7.8" in out


def _reapack_copy(scripts):
    copy = scripts / "TwelveTake REAPER MCP" / "TwelveTake" / srv.BRIDGE_SCRIPT_NAME
    copy.parent.mkdir(parents=True)
    copy.write_text("-- reapack copy\n", encoding="utf-8")
    return copy


def test_autostart_prefers_the_reapack_copy(tmp_path):
    _target(tmp_path).write_text("-- default copy\n", encoding="utf-8")
    copy = _reapack_copy(tmp_path)
    assert srv.autostart_command(scripts_dir=tmp_path) == 0
    text = _startup(tmp_path).read_text(encoding="utf-8")
    assert str(copy.resolve()).replace("\\", "/") in text


def test_autostart_falls_back_to_the_default_copy(tmp_path):
    _target(tmp_path).write_text("-- default copy\n", encoding="utf-8")
    assert srv.autostart_command(scripts_dir=tmp_path) == 0
    assert 'reaper.GetResourcePath() .. "/Scripts/reaper_mcp_bridge.lua"' in _startup(tmp_path).read_text(encoding="utf-8")


def test_autostart_without_any_copy_refuses(tmp_path, capsys):
    assert srv.autostart_command(scripts_dir=tmp_path) == 1
    assert not _startup(tmp_path).exists()
    assert "--install-bridge" in capsys.readouterr().err


def test_autostart_with_a_missing_path_refuses(tmp_path):
    assert srv.autostart_command(path=tmp_path / "nope.lua", scripts_dir=tmp_path) == 1
    assert not _startup(tmp_path).exists()
