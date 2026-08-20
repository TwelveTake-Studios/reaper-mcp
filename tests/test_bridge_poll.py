"""Tests for the bridge's mailbox scan (#13), the abandoned-response reaper, and the
file_exists helper.

The poll loop used to probe request_1 through request_1000 with io.open on every
defer tick — measured at 26.8% of a core while REAPER sat completely idle. It now
collects the pending slots with one directory enumeration. That exact change was
reverted once (``331d12f``) because nothing bounded the directory it enumerates; two
bounds hold it down now: the server-side startup sweep (``test_orphan_sweep.py``) and
the bridge-side reaper tested here, which keeps the mailbox small even against a
pre-1.7.0 server that never sweeps.

These slice the real Lua out of ``reaper_mcp_bridge.lua`` and run it under lupa.
"""
import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

BRIDGE = Path(__file__).resolve().parent.parent / "reaper_mcp_bridge.lua"


@pytest.fixture(scope="module")
def bridge_src():
    return BRIDGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def mid_claim_guard(bridge_src):
    """The real guard line that skips a request the server is still writing.

    The server claims its slot with ``O_CREAT|O_EXCL``, so ``request_N.json`` is
    visible to the enumeration poll at zero bytes while the payload is still being
    written. Answering that window hands the caller "Malformed request JSON" for a
    request that was perfectly valid a microsecond later.
    """
    m = re.search(
        r'^\s*(if request_data and request_data:match\(.*?\) then request_data = nil end)\s*$',
        bridge_src,
        re.M,
    )
    assert m, "the mid-claim guard is gone from process_request"
    return m.group(1)


def run_guard(guard, content):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    literal = "nil" if content is None else "[==[" + content + "]==]"
    return lua.execute(f"local request_data = {literal}\n{guard}\nreturn request_data")


@pytest.mark.parametrize("content", ["", " ", "\n", "  \r\n\t "])
def test_empty_request_is_skipped_not_answered(mid_claim_guard, content):
    """A zero-byte or all-whitespace request is the claim window, never a request."""
    assert run_guard(mid_claim_guard, content) is None


@pytest.mark.parametrize(
    "content",
    ['{"func":"CountTracks","args":[0]}', '  {"func":"GetCursorPosition","args":[]}  ', "garbage"],
)
def test_non_empty_request_still_reaches_the_decoder(mid_claim_guard, content):
    """The guard must not swallow anything with content, including a genuinely
    malformed request, which still has to be answered rather than left to time out."""
    assert run_guard(mid_claim_guard, content) == content


@pytest.fixture
def lua_tmp(tmp_path):
    """tmp_path, but only when Lua's io.open can actually address it.

    lupa hands Lua the chunk as UTF-8 bytes while Lua's io.open is C fopen, which on
    Windows decodes filenames in the ANSI code page; the two agree only on ASCII. A
    non-ASCII username makes every tmp_path non-ASCII, which would fail these tests
    against perfectly correct production code.
    """
    if not str(tmp_path).isascii():
        pytest.skip("Lua io.open decodes filenames in the ANSI code page; needs an ASCII path")
    return tmp_path


# --- scan_mailbox ------------------------------------------------------------


@pytest.fixture(scope="module")
def scan_block(bridge_src):
    m = re.search(r"-- Scan the mailbox.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate scan_mailbox — did it move or get renamed?"
    return m.group(0)


@pytest.fixture
def scan(scan_block):
    """Run scan_mailbox over a fake directory listing.

    Returns ("2,7"-style slots, "a.json,b.json"-style responses, "dir|dir"-style
    record of every directory EnumerateFiles was pointed at).
    """
    def _run(*names):
        listing = ", ".join(f'"{n}"' for n in names)
        setup = f"""
bridge_dir = "/tmp/mailbox/"
local files = {{ {listing} }}
seen_dirs = {{}}
reaper = {{
    EnumerateFiles = function(dir, i)
        seen_dirs[#seen_dirs + 1] = dir
        return files[i + 1]
    end,
}}
"""
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        return lua.execute(
            f"{setup}\n{scan_block}\n"
            "local pending, responses = scan_mailbox()\n"
            # pending holds {order, label, name} per entry since the slot-name fix.
            # The LABEL is joined, not the order, so padding survives into assertions.
            "local labels = {}\n"
            "for i, r in ipairs(pending) do labels[i] = r.label end\n"
            "return table.concat(labels, \",\"), table.concat(responses, \",\"),"
            " table.concat(seen_dirs, \"|\")"
        )
    return _run


def test_finds_request_slots_in_ascending_order(scan):
    """Sorted ascending regardless of filesystem enumeration order, so multi-request
    ticks stay deterministic."""
    slots, _, _ = scan("request_7.json", "request_2.json", "request_11.json")
    assert slots == "2,7,11"


def test_zero_padded_slot_keeps_its_name(scan):
    """The slot TEXT survives the scan, so the request can be opened under the name that
    was actually enumerated.

    Running the slot through `tonumber` and rebuilding the path dropped the padding:
    request_007.json matched here, was looked for as request_7.json, and was never
    found -- so it was re-enumerated every tick forever, never answered and never
    deleted. Nothing removes such an entry (both cleanup paths only touch responses)
    and the poll's cost is linear in directory entries, so one stranded name is a
    permanent tax. Confirmed against real REAPER 2026-08-20: it survived 40s+, well
    past the 30s response TTL, while the bridge served other calls normally.
    """
    slots, _, _ = scan("request_007.json")
    assert slots == "007", (
        "the padded slot was normalised to a number; the bridge will look for "
        "request_7.json, never find it, and strand the entry forever"
    )


def test_padded_and_bare_slots_order_deterministically(scan):
    """Same numeric slot, two spellings: the tie must break the same way every tick."""
    a, _, _ = scan("request_007.json", "request_7.json")
    b, _, _ = scan("request_7.json", "request_007.json")
    assert a == b == "007,7"


def test_responses_and_junk_are_not_requests(scan):
    slots, _, _ = scan(
        "response_3.json",       # the other half of the mailbox
        "request_.json",         # no slot number
        "request_2x.json",       # trailing garbage in the slot
        "xrequest_3.json",       # prefix mismatch
        "request_4.json.bak",    # backup copy
        "REQUEST_5.json",        # wrong case: the server writes lowercase
        "notes.txt",
    )
    assert slots == ""


def test_empty_directory_yields_no_slots(scan):
    slots, responses, _ = scan()
    assert slots == ""
    assert responses == ""


def test_no_slot_ceiling(scan):
    """The old loop scanned 1..1000 and could never see beyond it. Enumeration has
    no ceiling, so a foreign client using higher slots is still served."""
    slots, _, _ = scan("request_1001.json")
    assert slots == "1001"


def test_enumerates_the_bridge_directory(scan):
    """EVERY enumeration call must aim at bridge_dir, not just the last one."""
    _, _, seen_dirs = scan("request_1.json")
    assert seen_dirs, "EnumerateFiles was never called"
    assert set(seen_dirs.split("|")) == {"/tmp/mailbox/"}


def test_collects_response_files_for_the_reaper(scan):
    """Both naming schemes: today's response_<n> and WS4's response_<pid>_<n>."""
    _, responses, _ = scan("response_3.json", "request_2.json", "response_123_45.json")
    assert sorted(responses.split(",")) == ["response_123_45.json", "response_3.json"]


def test_response_lookalikes_are_not_collected(scan):
    """The reaper deletes what this list contains, so it must be exact."""
    _, responses, _ = scan(
        "response_.json", "response_a.json", "response_7.json.bak",
        "xresponse_1.json", "response_1_2_3.json",
    )
    assert responses == ""


# --- reap_abandoned_responses -------------------------------------------------


@pytest.fixture(scope="module")
def reap_block(bridge_src):
    m = re.search(r"-- Reap abandoned responses.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate reap_abandoned_responses — did it move or get renamed?"
    return m.group(0)


@pytest.fixture
def reaper_dir(reap_block, lua_tmp):
    """A real directory plus a driver: reap(now, names) runs one tick at time `now`."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(
        f'bridge_dir = "{lua_tmp.as_posix()}/"\n'
        "fake_now = 0\n"
        "os.time = function() return fake_now end\n"
        f"{reap_block}\n"
        "function reap(now, names)\n"
        "    fake_now = now\n"
        "    local list = {}\n"
        "    for name in names:gmatch('[^,]+') do list[#list + 1] = name end\n"
        "    reap_abandoned_responses(list)\n"
        "end\n"
    )
    def _tick(now, *names):
        lua.globals().reap(now, ",".join(names))
    return lua_tmp, _tick


def test_first_sighting_is_never_reaped(reaper_dir):
    d, tick = reaper_dir
    (d / "response_9.json").write_text("{}")
    tick(1000, "response_9.json")
    assert (d / "response_9.json").exists()


def test_reaped_after_ttl_expires(reaper_dir):
    """Continuously present past the TTL means no live reader: every server gives
    up at FILE_TIMEOUT=5s, and 30s is far beyond that."""
    d, tick = reaper_dir
    (d / "response_9.json").write_text("{}")
    tick(1000, "response_9.json")
    tick(1031, "response_9.json")
    assert not (d / "response_9.json").exists()


def test_survives_exactly_at_the_ttl_boundary(reaper_dir):
    d, tick = reaper_dir
    (d / "response_9.json").write_text("{}")
    tick(1000, "response_9.json")
    tick(1030, "response_9.json")  # 30s elapsed is not YET "longer than" the TTL
    assert (d / "response_9.json").exists()


def test_claimed_responses_are_forgotten(reaper_dir):
    """A response that vanished (claimed by its reader) must not inherit its old
    first-seen time when the same slot is reused later."""
    d, tick = reaper_dir
    (d / "response_9.json").write_text("{}")
    tick(1000, "response_9.json")
    tick(1015)  # claimed: gone from the listing this tick
    (d / "response_9.json").write_text("{}")  # slot reused, brand-new response
    tick(1031, "response_9.json")
    assert (d / "response_9.json").exists(), "fresh response reaped on a stale timestamp"


# --- file_exists -------------------------------------------------------------


@pytest.fixture(scope="module")
def file_exists_block(bridge_src):
    m = re.search(r"-- Check if file exists.*?\nend\n", bridge_src, re.S)
    assert m, "could not locate file_exists — did it move or get renamed?"
    return m.group(0)


def run_file_exists(file_exists_block, reaper_lua, call):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(f"reaper = {reaper_lua}\n{file_exists_block}\nreturn {call}")


def test_native_reaper_file_exists_is_preferred(file_exists_block):
    """#13: the native call is ~1.26x cheaper than an io.open probe."""
    reaper_lua = """{
        file_exists = function(p) probed = p return true end,
    }"""
    out = run_file_exists(file_exists_block, reaper_lua, 'file_exists("q.json"), probed')
    assert out == (True, "q.json")


def test_native_false_is_passed_through(file_exists_block):
    reaper_lua = '{ file_exists = function(_) return false end }'
    assert run_file_exists(file_exists_block, reaper_lua, 'file_exists("q.json")') is False


def test_io_open_fallback_without_native(file_exists_block, lua_tmp):
    """A REAPER without reaper.file_exists must fall back, not throw: some callers
    sit outside any pcall, so a throw here stops the bridge permanently."""
    real = lua_tmp / "real.json"
    real.write_text("{}")
    assert run_file_exists(
        file_exists_block, "{}", f'file_exists("{real.as_posix()}")'
    ) is True
    assert run_file_exists(
        file_exists_block, "{}", f'file_exists("{(lua_tmp / "ghost.json").as_posix()}")'
    ) is False
