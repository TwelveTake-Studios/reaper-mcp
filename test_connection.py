#!/usr/bin/env python3
"""
REAPER MCP Server - Connection Test (file bridge)

Verifies the file-based bridge round-trip: writes a request JSON into the bridge
directory and waits for the REAPER-side bridge (reaper_mcp_bridge.lua) to write a
response. This is the default, supported communication path and needs no extra setup
beyond running the bridge script inside REAPER.

Usage:
    python test_connection.py

The bridge directory defaults to %APPDATA%\\REAPER\\Scripts\\mcp_bridge_data and can be
overridden with the REAPER_BRIDGE_DIR environment variable (mirrors the MCP server).

Pure standard library — no third-party dependencies required.
"""

import os
import sys
import json
import time
from pathlib import Path

# Mirror the MCP server's bridge-directory resolution.
BRIDGE_DIR = Path(
    os.getenv("REAPER_BRIDGE_DIR")
    or os.path.expandvars(r"%APPDATA%\REAPER\Scripts\mcp_bridge_data")
)

TIMEOUT = 5.0
POLL_INTERVAL = 0.05
_counter = 0


def reaper_call(func: str, args: list, timeout: float = TIMEOUT) -> dict:
    """Send one request through the file bridge and return the decoded response."""
    global _counter
    _counter = (_counter % 999) + 1
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    request_file = BRIDGE_DIR / f"request_{_counter}.json"
    response_file = BRIDGE_DIR / f"response_{_counter}.json"

    try:
        response_file.unlink(missing_ok=True)
    except OSError:
        pass

    request_file.write_text(json.dumps({"func": func, "args": args}))

    start = time.time()
    while time.time() - start < timeout:
        if response_file.exists():
            text = response_file.read_text().strip()
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    time.sleep(POLL_INTERVAL)
                    continue
                request_file.unlink(missing_ok=True)
                response_file.unlink(missing_ok=True)
                return data
        time.sleep(POLL_INTERVAL)

    request_file.unlink(missing_ok=True)
    return {"ok": False, "error": "timeout"}


def main() -> int:
    print(f"Testing REAPER file bridge at:\n  {BRIDGE_DIR}")
    print("=" * 56)

    # Test 1: connectivity via track count
    print("\n1. Track count (CountTracks)...")
    result = reaper_call("CountTracks", [0])
    if not result.get("ok"):
        print(f"   [FAIL] No response ({result.get('error')}).")
        print("\n   Make sure:")
        print("   1. REAPER is running")
        print("   2. reaper_mcp_bridge.lua is loaded and running in REAPER")
        print('      (you should see "REAPER MCP Bridge (File-based, Full API) started" in the console)')
        return 1
    print(f"   [PASS] Project has {result.get('ret')} tracks")

    # Test 2: master track info
    print("\n2. Master track (GetTrackInfo -1)...")
    result = reaper_call("GetTrackInfo", [-1])
    info = result.get("info", {})
    if result.get("ok") and "name" in info:
        fx = ", ".join(info.get("fx_names", [])) or "none"
        print(f"   [PASS] Master: {info.get('name')} | FX: {fx}")
    else:
        print(f"   [FAIL] Unexpected response: {result}")

    # Test 3: tempo
    print("\n3. Project tempo (Master_GetTempo)...")
    result = reaper_call("Master_GetTempo", [])
    if result.get("ok"):
        print(f"   [PASS] Tempo: {result.get('ret')} BPM")
    else:
        print(f"   [FAIL] Unexpected response: {result}")

    print("\n" + "=" * 56)
    print("Connection test complete - the file bridge is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
