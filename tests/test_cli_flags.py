import sys

import pytest

import reaper_mcp_server as srv


def command_line(monkeypatch, *args):
    served = []
    monkeypatch.setattr(srv.mcp, "run", lambda: served.append(True))
    monkeypatch.setattr(sys, "argv", ["twelvetake-reaper-mcp", *args])
    return served


@pytest.mark.parametrize("flag", ["--instal-bridge", "--verison", "-x", "--", "-", "--autostart-bridge"])
def test_an_unknown_flag_prints_usage_and_exits_2_without_serving(monkeypatch, capsys, flag):
    served = command_line(monkeypatch, flag)
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 2
    assert served == []
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"error: unknown option: {flag}\n")
    assert srv.USAGE in err


def test_no_arguments_still_serves(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(srv, "BRIDGE_DIR_PROBLEM", None)
    served = command_line(monkeypatch)
    srv.main()
    assert served == [True]


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_the_version_flags_are_unchanged(monkeypatch, capsys, flag):
    served = command_line(monkeypatch, flag)
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 0
    assert capsys.readouterr().out == srv.__version__ + "\n"
    assert served == []


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_the_help_flags_are_unchanged(monkeypatch, capsys, flag):
    served = command_line(monkeypatch, flag)
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 0
    assert capsys.readouterr().out == srv.USAGE + "\n"
    assert served == []


@pytest.mark.parametrize("args, called", [
    (["--install-bridge"], ("install_bridge", None, False)),
    (["install-bridge", "DIR", "--autostart"], ("install_bridge", "DIR", True)),
    (["--autostart"], ("autostart_command", None)),
    (["--autostart", "PATH"], ("autostart_command", "PATH")),
    (["--remove-autostart", "DIR"], ("disable_autostart", "DIR")),
])
def test_the_bridge_flags_still_reach_their_commands(monkeypatch, args, called):
    seen = []
    monkeypatch.setattr(srv, "install_bridge",
                        lambda d=None, autostart=False: seen.append(("install_bridge", d and d.name, autostart)) or 0)
    monkeypatch.setattr(srv, "autostart_command", lambda p=None: seen.append(("autostart_command", p and p.name)) or 0)
    monkeypatch.setattr(srv, "disable_autostart", lambda d: seen.append(("disable_autostart", d.name)) or 0)
    served = command_line(monkeypatch, *args)
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 0
    assert seen == [called]
    assert served == []


def test_the_reload_flag_still_reaches_the_reload(monkeypatch):
    seen = []

    async def reload():
        seen.append("reload")
        return {"state": "not_running"}

    monkeypatch.setattr(srv, "reload_running_bridge", reload)
    monkeypatch.setattr(srv, "report_reload", lambda result, target, autostart: seen.append(result["state"]))
    served = command_line(monkeypatch, "--reload-bridge")
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 0
    assert seen == ["reload", "not_running"]
    assert served == []
