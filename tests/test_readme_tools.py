import asyncio
import re
from pathlib import Path

import pytest

import reaper_mcp_server as srv

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
REFERENCE = README[README.index("## Tool Reference"):README.index("## Track Indexing")]
SECTIONS = [(m.group(1), int(m.group(2)), re.findall(r"^\| `([a-z_0-9]+)\(", m.group(3), re.M))
            for m in re.finditer(r"^### (.+?) \((\d+) tools\)\r?\n(.*?)(?=^### |\Z)", REFERENCE, re.M | re.S)]


@pytest.fixture(scope="module")
def tool_names():
    return [t.name for t in asyncio.run(srv.mcp.list_tools())]


def listed():
    return [name for _, _, rows in SECTIONS for name in rows]


def test_the_reference_lists_every_tool_once(tool_names):
    assert sorted(listed()) == sorted(tool_names)


@pytest.mark.parametrize("title, count, rows", SECTIONS, ids=[s[0] for s in SECTIONS])
def test_each_section_heading_counts_its_rows(title, count, rows):
    assert count == len(rows), f"'{title} ({count} tools)' lists {len(rows)}"


def test_the_badge_and_headline_carry_the_tool_count(tool_names):
    assert f"badge/tools-{len(tool_names)}-blue" in README
    assert f"### {len(tool_names)} Tools Covering" in README
