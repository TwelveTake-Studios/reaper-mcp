"""A ceiling on the tools/list payload, and a guard on the schema slimming.

Every client pays for this payload on every turn of every session. v1.6.0 added roughly
28,000 bytes in one release and nothing flagged it, which is the whole reason this file
exists: the slimming work is only durable if something fails when it is undone.

Raising CEILING_BYTES is a deliberate act. If a change genuinely needs more room, raise
it in the same commit and say why in the message. Do not raise it to make CI green.
"""

import json

import reaper_mcp_server as srv

# Re-measured for the 1.7.0 optimization pass: 176 tools, 78,588 bytes (~21,200 tokens),
# down from 95,258. The cut came from hoisting conventions into the server `instructions`
# block and then deleting the repetition: 51 no-op "Object with success status" Returns
# blocks, 201 tautological "<x>_index: <X> index (0-based)." Args lines, and the twelve
# oversized MIDI docstrings. Headroom here is ~3,400 bytes, deliberately tight: it absorbs
# ordinary docstring edits and a few new tools, not another release quietly adding 28,000.
#
# Historical, for context: measured at 1.6.3: 176 tools, 95,922 bytes, titles stripped and
# descriptions dedented, which makes this number identical on every supported Python.
# Before the dedent it was 101,286 on 3.10-3.12 and 95,922 on 3.13, so this test passed
# and failed depending on the interpreter.
#
# The headroom is deliberately modest. It absorbs ordinary docstring edits and a handful
# of new tools; it does not absorb another 28,000-byte release going unnoticed.
CEILING_BYTES = 82_000

# Descriptions are ours; schema bytes belong to Pydantic and move when it does. Measured
# 52,319. This is the ceiling that actually guards against docstring bloat.
DESCRIPTION_CEILING_BYTES = 38_000


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


def test_descriptions_carry_no_leading_indentation():
    """Python strips docstring indentation at compile time only from 3.13 onward.

    On 3.10 through 3.12 every tool would otherwise ship its own indentation to the
    model on every turn: 5,364 bytes across this surface, carrying no information.
    It also made the payload size differ by interpreter, which is how it was found.
    """
    offenders = [
        t["name"] for t in tools_list_payload()
        if any(line[:1] in (" ", "\t") for line in t["description"].splitlines()[1:2])
    ]
    assert not offenders, f"descriptions still indented (run on <3.13 to see it): {offenders}"


def test_description_normalisation_is_idempotent():
    assert srv.normalize_tool_descriptions() == 0


def test_description_bytes_stay_under_ceiling():
    """The half of the payload this project actually controls.

    Schema bytes come from Pydantic and move when it does. Descriptions come from our
    own docstrings, so this is the number that catches a v1.6.0-style release adding
    28,000 bytes without anyone noticing.
    """
    total = sum(len(t["description"]) for t in tools_list_payload())
    assert total < DESCRIPTION_CEILING_BYTES, (
        f"tool descriptions total {total:,} bytes, over the "
        f"{DESCRIPTION_CEILING_BYTES:,} byte ceiling. Trim docstrings, or raise the "
        "ceiling deliberately and explain why in the commit."
    )


def test_every_tool_has_a_description():
    """A tool with no description is unusable by a model and free to fix."""
    missing = [t["name"] for t in tools_list_payload() if not t["description"].strip()]
    assert not missing, f"tools with no description: {missing}"
