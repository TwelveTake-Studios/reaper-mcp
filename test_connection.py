#!/usr/bin/env python3
"""
REAPER MCP Server - Connection Test

Tests the connection to the REAPER web server and verifies basic functionality.

Usage:
    python test_connection.py [host] [port]

Default: localhost:9000
"""

import sys
import json

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    sys.exit(1)


def test_connection(host: str = "localhost", port: int = 9000):
    """Test connection to REAPER web server"""
    base_url = f"http://{host}:{port}"
    client = httpx.Client(timeout=5.0)

    print(f"Testing REAPER Web Server at {base_url}...")
    print("=" * 50)

    # Test 1: Ping
    print("\n1. Testing /ping endpoint...")
    try:
        response = client.get(f"{base_url}/ping")
        data = response.json()
        if data.get("status") == "ok":
            print("   [PASS] Server is responding")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
            return False
    except httpx.ConnectError:
        print("   [FAIL] Cannot connect to server")
        print(f"\n   Make sure:")
        print(f"   1. REAPER is running")
        print(f"   2. reaper_web_server.py is loaded and running in REAPER")
        print(f"   3. Server is listening on {base_url}")
        return False
    except Exception as e:
        print(f"   [FAIL] Error: {e}")
        return False

    # Test 2: Track count
    print("\n2. Testing /tracks/count endpoint...")
    try:
        response = client.get(f"{base_url}/tracks/count")
        data = response.json()
        if "count" in data:
            print(f"   [PASS] Project has {data['count']} tracks")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 3: Master track
    print("\n3. Testing /master endpoint (master track info)...")
    try:
        response = client.get(f"{base_url}/master")
        data = response.json()
        if "name" in data:
            print(f"   [PASS] Master track: {data.get('name', 'MASTER')}")
            print(f"         Volume: {data.get('volume_db', 0):.1f} dB")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 4: Master track FX count
    print("\n4. Testing /tracks/-1/fx/count endpoint (master track FX)...")
    try:
        response = client.get(f"{base_url}/tracks/-1/fx/count")
        data = response.json()
        if "count" in data:
            print(f"   [PASS] Master track has {data['count']} FX plugins")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 5: Transport state
    print("\n5. Testing /transport endpoint...")
    try:
        response = client.get(f"{base_url}/transport")
        data = response.json()
        if "playing" in data:
            status = "playing" if data["playing"] else "stopped"
            print(f"   [PASS] Transport: {status}, cursor at {data.get('cursor_position', 0):.2f}s")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 6: Project info
    print("\n6. Testing /project endpoint...")
    try:
        response = client.get(f"{base_url}/project")
        data = response.json()
        if "tempo" in data:
            print(f"   [PASS] Project: {data.get('name', 'Untitled')}")
            print(f"         Tempo: {data.get('tempo', 120)} BPM")
        else:
            print(f"   [FAIL] Unexpected response: {data}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 7: Test first track if exists
    print("\n7. Testing track access...")
    try:
        count_resp = client.get(f"{base_url}/tracks/count")
        count = count_resp.json().get("count", 0)

        if count > 0:
            response = client.get(f"{base_url}/tracks/0")
            data = response.json()
            if "name" in data:
                print(f"   [PASS] Track 0: {data.get('name', 'Unnamed')}")
                print(f"         Volume: {data.get('volume_db', 0):.1f} dB, Pan: {data.get('pan', 0):.2f}")

                # Test FX on first track
                fx_resp = client.get(f"{base_url}/tracks/0/fx/count")
                fx_data = fx_resp.json()
                print(f"         FX count: {fx_data.get('count', 0)}")
            else:
                print(f"   [FAIL] Unexpected response: {data}")
        else:
            print("   [SKIP] No tracks in project")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    print("\n" + "=" * 50)
    print("Connection test complete!")
    print("\nIf all tests passed, the MCP server should work correctly.")
    print("Configure Claude Code with:")
    print(f"""
{{
  "mcpServers": {{
    "reaper": {{
      "command": "python",
      "args": ["{sys.path[0]}/reaper_mcp_server.py"],
      "env": {{
        "REAPER_HOST": "{host}",
        "REAPER_PORT": "{port}"
      }}
    }}
  }}
}}
""")
    return True


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000

    success = test_connection(host, port)
    sys.exit(0 if success else 1)
