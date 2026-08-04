"""Guards on what the built distribution actually contains.

v1.6.1 shipped with the wheel containing the server and NOT `reaper_mcp_bridge.lua`,
which made step 1 of the documented install impossible to perform by the documented
install method: `uvx twelvetake-reaper-mcp` unpacks a wheel into a throwaway cache, so
there was no bridge script and no path to dig one out of.

These assert the declaration that produces the wheel, so they need no network, no build
backend and no isolated build. That is deliberate: a test that only passes when a build
toolchain happens to be present is a test that quietly stops running.
"""

import tomllib
from pathlib import Path

import reaper_mcp_server as srv

REPO = Path(__file__).resolve().parent.parent
BRIDGE_NAME = "reaper_mcp_bridge.lua"


def pyproject():
    with open(REPO / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_bridge_script_exists_in_the_repo():
    assert (REPO / BRIDGE_NAME).is_file()


def test_wheel_is_declared_to_include_the_bridge():
    """`only-include` alone ships just the server; the bridge needs force-include."""
    wheel = pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]
    forced = wheel.get("force-include", {})
    included = set(wheel.get("only-include", [])) | set(forced.keys()) | set(forced.values())
    assert BRIDGE_NAME in included, (
        f"{BRIDGE_NAME} is not declared for the wheel. Without it, `uvx twelvetake-reaper-mcp` "
        "installs a server with no bridge script and no way to obtain one."
    )


def test_sdist_also_includes_the_bridge():
    sdist = pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert BRIDGE_NAME in sdist.get("include", [])


def test_install_bridge_can_find_its_source_in_a_checkout():
    """--install-bridge resolves the script next to the module, which is where the
    wheel puts it. In a source checkout that is the repo root."""
    found = srv.bundled_bridge_script()
    assert found is not None, "bundled_bridge_script() found nothing to install"
    assert found.name == BRIDGE_NAME
    assert found.is_file()


def test_declared_python_matches_what_is_tested():
    """`requires-python` claimed >=3.8 while CI only ever tested 3.10+, so 3.8 users got
    a clean install and a broken runtime."""
    requires = pyproject()["project"]["requires-python"]
    assert requires == ">=3.10", requires
    classifiers = pyproject()["project"]["classifiers"]
    for stale in ("Programming Language :: Python :: 3.8", "Programming Language :: Python :: 3.9"):
        assert stale not in classifiers, f"{stale} claims support that is not tested"


def test_mcp_dependency_is_capped_below_2():
    """mcp 2.0 moved `mcp.server.fastmcp`, which this server imports at module scope.
    An unbounded constraint means a fresh install resolves to a version that cannot start,
    which is exactly what happened to 1.6.1."""
    deps = pyproject()["project"]["dependencies"]
    mcp_dep = next((d for d in deps if d.replace(" ", "").startswith("mcp")), None)
    assert mcp_dep is not None, "mcp dependency missing"
    assert "<2" in mcp_dep.replace(" ", ""), (
        f"mcp dependency {mcp_dep!r} has no upper bound; mcp 2.0 breaks the import"
    )
