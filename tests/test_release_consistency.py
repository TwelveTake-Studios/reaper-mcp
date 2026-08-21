"""Version facts that must agree with each other before anything is tagged.

`__version__` sat at 1.6.5 while pyproject reached 1.6.7: the bump was missed at 1.6.6
and again at 1.6.7, so `--version`, the USAGE header and the startup banner all
under-reported by two releases (@SNChicago, issue #15). Nothing objected, twice, because
nothing was checking.

These are separate facts in four files and every one of them is hand-edited at release
time. This file is the thing that refuses.

Read as raw text on purpose, like `test_packaging.py`: `tomllib` is 3.11+ and a release
guard must not be the thing that breaks on the oldest supported Python.
"""

import re
from pathlib import Path

import reaper_mcp_server as srv

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
BRIDGE = REPO / "reaper_mcp_bridge.lua"
CHANGELOG = REPO / "CHANGELOG.md"

SEMVER = r"\d+\.\d+\.\d+"


def package_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    body = text[text.find("[project]"):]
    m = re.search(rf'^version\s*=\s*["\']({SEMVER})["\']', body, re.M)
    assert m, "no version in pyproject [project]"
    return m.group(1)


def bridge_version() -> str:
    m = re.search(rf'BRIDGE_VERSION\s*=\s*"({SEMVER})"', BRIDGE.read_text(encoding="utf-8"))
    assert m, "no BRIDGE_VERSION in reaper_mcp_bridge.lua"
    return m.group(1)


def changelog_top() -> str:
    """The newest RELEASED version heading.

    A section for work in progress carries an unreleased date and is skipped: the next
    version is written up as it is built, and the alternative is either an undocumented
    release or bumping every version fact to a number that does not exist yet just to
    keep this green. Only a dated entry counts as shipped.
    """
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        m = re.match(rf"##\s*\[({SEMVER})\]", stripped)
        if not m:
            continue
        if re.search(r"unreleased|tbd|in progress", stripped, re.I):
            continue
        return m.group(1)
    raise AssertionError("no released '## [x.y.z] - <date>' heading found in CHANGELOG.md")


def changelog_section(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.find(f"## [{version}]")
    assert start != -1, f"CHANGELOG has no section for {version}"
    nxt = text.find("## [", start + 4)
    return text[start:nxt if nxt != -1 else len(text)]


def test_dunder_version_matches_pyproject():
    """The one that actually broke. --version and the startup banner read __version__."""
    assert srv.__version__ == package_version(), (
        f"__version__ is {srv.__version__!r} but pyproject declares {package_version()!r}. "
        "Bump both in the same commit."
    )


def test_changelog_documents_this_version():
    """A release with no changelog entry ships a version nobody can look up."""
    assert changelog_top() == package_version(), (
        f"CHANGELOG's newest entry is {changelog_top()} but pyproject declares "
        f"{package_version()}. Write the entry before tagging."
    )


def test_bridge_is_never_ahead_of_the_package():
    """The bridge ships INSIDE the package, so it cannot be newer than its container.

    It is legitimately OLDER: 1.6.4 shipped with BRIDGE_VERSION 1.6.1 because the bridge
    did not change. Equality is not the rule; not-ahead is.
    """
    assert srv.version_tuple(bridge_version()) <= srv.version_tuple(package_version()), (
        f"BRIDGE_VERSION {bridge_version()} is ahead of package {package_version()}"
    )


def test_min_bridge_version_is_reachable():
    """Requiring a bridge newer than the one we ship refuses every correctly-installed user."""
    assert srv.version_tuple(srv.MIN_BRIDGE_VERSION) <= srv.version_tuple(bridge_version()), (
        f"MIN_BRIDGE_VERSION {srv.MIN_BRIDGE_VERSION} exceeds the bundled bridge "
        f"{bridge_version()}: ensure_bridge_current would refuse all 176 tools and cache "
        "the refusal for the process lifetime, turning an upgrade into a total outage."
    )


def test_slot_claim_version_is_reachable():
    """Same trap one level down: a gate above the bundled bridge never opens."""
    assert srv.version_tuple(srv.SLOT_CLAIM_BRIDGE_VERSION) <= srv.version_tuple(bridge_version()), (
        f"SLOT_CLAIM_BRIDGE_VERSION {srv.SLOT_CLAIM_BRIDGE_VERSION} exceeds the bundled "
        f"bridge {bridge_version()}: slot claiming could never switch on."
    )


def test_a_bridge_change_tells_users_to_redeploy():
    """REAPER runs the DEPLOYED copy, and no pip upgrade updates it.

    BRIDGE_VERSION equal to the package version means the bridge was bumped FOR this
    release, so the entry has to say so. Shipping a bridge fix without that line leaves
    users running the old script and reporting the bug as unfixed. When the bridge did
    not change (1.6.4: bridge 1.6.1, package 1.6.4) this does not apply.
    """
    if bridge_version() != package_version():
        return
    section = changelog_section(package_version()).lower()
    assert "redeploy" in section, (
        f"BRIDGE_VERSION was bumped to {bridge_version()} for this release, but the "
        f"CHANGELOG entry for {package_version()} never tells anyone to redeploy the "
        "bridge. REAPER keeps running the old deployed copy."
    )
