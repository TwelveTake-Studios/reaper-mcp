"""Guards on what the built distribution actually declares.

v1.6.1 shipped with the wheel containing the server and NOT `reaper_mcp_bridge.lua`,
which made step 1 of the documented install impossible to perform by the documented
install method: `uvx twelvetake-reaper-mcp` unpacks a wheel into a throwaway cache, so
there was no bridge script and no path to dig one out of.

These read `pyproject.toml` as text rather than parsing it. `tomllib` is 3.11+, and a
guard on packaging must not itself be the thing that breaks on the oldest supported
Python: the first version of this file did exactly that and reddened CI on 3.10.
Nothing here needs a network, a build backend or a TOML parser, so it cannot quietly
stop running.
"""

from pathlib import Path

import reaper_mcp_server as srv

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
BRIDGE_NAME = "reaper_mcp_bridge.lua"


def table(name: str) -> str:
    """The raw text of a [name] table from pyproject.toml, up to the next table header."""
    text = PYPROJECT.read_text(encoding="utf-8")
    marker = f"[{name}]"
    start = text.find(marker)
    assert start != -1, f"{marker} not found in pyproject.toml"
    rest = text[start + len(marker):]
    end = rest.find("\n[")
    return rest if end == -1 else rest[:end]


def test_bridge_script_exists_in_the_repo():
    assert (REPO / BRIDGE_NAME).is_file()


def test_wheel_is_declared_to_include_the_bridge():
    """`only-include` alone ships just the server; the bridge needs force-include."""
    declared = table("tool.hatch.build.targets.wheel") + table("tool.hatch.build.targets.wheel.force-include")
    assert BRIDGE_NAME in declared, (
        f"{BRIDGE_NAME} is not declared for the wheel. Without it, "
        "`uvx twelvetake-reaper-mcp` installs a server with no bridge script and no way "
        "to obtain one, which is what happened in 1.6.1."
    )


def test_sdist_also_includes_the_bridge():
    assert BRIDGE_NAME in table("tool.hatch.build.targets.sdist")


def test_install_bridge_can_find_its_source_in_a_checkout():
    """--install-bridge resolves the script next to the module, which is where the wheel
    puts it. In a source checkout that is the repo root."""
    found = srv.bundled_bridge_script()
    assert found is not None, "bundled_bridge_script() found nothing to install"
    assert found.name == BRIDGE_NAME
    assert found.is_file()


def test_declared_python_matches_what_is_tested():
    """`requires-python` claimed >=3.8 while CI only ever tested 3.10+, so a 3.8 user got
    a clean install and a broken runtime."""
    project = table("project")
    assert 'requires-python = ">=3.10"' in project, "requires-python does not match tested versions"
    for stale in ('"Programming Language :: Python :: 3.8"', '"Programming Language :: Python :: 3.9"'):
        assert stale not in project, f"{stale} claims support that is not tested"


def array(key: str, within: str) -> list:
    """The entries of a `key = [ ... ]` array, as raw text lines.

    Scoped to one array on purpose: `keywords` also contains the bare string "mcp", and
    searching the whole [project] table found that before the dependency pin.
    """
    body = table(within)
    start = body.find(f"{key} = [")
    assert start != -1, f"{key} not found in [{within}]"
    end = body.find("\n]", start)
    assert end != -1, f"{key} array in [{within}] is not closed"
    return [ln.strip() for ln in body[start:end].splitlines()[1:] if ln.strip()]


def test_mcp_dependency_is_capped_below_2():
    """mcp 2.0 moved `mcp.server.fastmcp`, which this server imports at module scope. An
    unbounded constraint means a fresh install resolves to a version that cannot start,
    which is exactly what happened to 1.6.1."""
    entries = [e for e in array("dependencies", "project") if not e.startswith("#")]
    pin = next((e for e in entries if e.strip('",').startswith("mcp")), None)
    assert pin is not None, f"mcp dependency not found among {entries}"
    assert "<2" in pin.replace(" ", ""), (
        f"mcp dependency has no upper bound ({pin}); mcp 2.0 breaks the import"
    )
