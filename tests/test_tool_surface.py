"""A ceiling on the tools/list payload, and a guard on the schema slimming.

Every client pays for this payload on every turn of every session. v1.6.0 added roughly
28,000 bytes in one release and nothing flagged it, which is the whole reason this file
exists: the slimming work is only durable if something fails when it is undone.

Raising CEILING_BYTES is a deliberate act. If a change genuinely needs more room, raise
it in the same commit and say why in the message. Do not raise it to make CI green.
"""

import json

import reaper_mcp_server as srv

# Measured at 1.6.1: 176 tools, 95,602 bytes (~25,800 tokens), titles already stripped.
# The headroom is deliberately modest. It absorbs ordinary docstring edits and a handful
# of new tools; it does not absorb another 28,000-byte release going unnoticed.
CEILING_BYTES = 100_000


def tools_list_payload():
    """The tool list as a client receives it, in the shape tools/list serialises."""
    return [
        {"name": t.name, "description": t.description or "", "inputSchema": t.parameters}
        for t in srv.mcp._tool_manager.list_tools()
    ]


def test_payload_stays_under_ceiling():
    size = len(json.dumps(tools_list_payload()))
    assert size < CEILING_BYTES, (
        f"tools/list payload is {size:,} bytes, over the {CEILING_BYTES:,} byte ceiling.\n"
        "Trim descriptions, or raise CEILING_BYTES deliberately and explain why in the commit."
    )


def test_schema_titles_stay_stripped():
    """Guards the ~16KB title strip.

    Pydantic emits a title for every parameter ('Track Index' beside track_index) plus a
    root title per tool. They are annotation-only. If a future MCP SDK bump reorders
    registration so slim_tool_schemas() runs too early, this catches it.
    """
    blob = json.dumps([t["inputSchema"] for t in tools_list_payload()])
    assert '"title"' not in blob


def test_slimming_is_idempotent():
    """Safe to call more than once: a second pass must find nothing left to remove."""
    assert srv.slim_tool_schemas() == 0


def test_every_tool_has_a_description():
    """A tool with no description is unusable by a model and free to fix."""
    missing = [t["name"] for t in tools_list_payload() if not t["description"].strip()]
    assert not missing, f"tools with no description: {missing}"
