#!/usr/bin/env python3
"""
TwelveTake REAPER MCP Server

Model Context Protocol server for controlling REAPER DAW.
Supports both HTTP and file-based communication with REAPER.

A TwelveTake Studios project - https://twelvetake.com

Author: TwelveTake Studios LLC
License: MIT
Version: 1.1.0
"""

__version__ = "1.1.0"
__name__ = "twelvetake-reaper-mcp"

import os
import asyncio
import json
import time
from pathlib import Path
from mcp.server.fastmcp import FastMCP

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def db_to_linear(db: float) -> float:
    """Convert decibels to linear amplitude."""
    return 10 ** (db / 20) if db > -150 else 0


# Configuration
REAPER_HOST = os.getenv("REAPER_HOST", "localhost")
REAPER_PORT = int(os.getenv("REAPER_PORT", "9000"))
REAPER_URL = f"http://{REAPER_HOST}:{REAPER_PORT}"

# File-based fallback configuration
BRIDGE_DIR = Path(os.getenv(
    "REAPER_BRIDGE_DIR",
    os.path.expandvars(r"%APPDATA%\REAPER\Scripts\mcp_bridge_data")
))
FILE_TIMEOUT = 5.0
FILE_POLL_INTERVAL = 0.02

# Communication mode: "file" (default), "http", or "auto" (http with file fallback)
COMM_MODE = os.getenv("REAPER_COMM_MODE", "file").lower()

# Create MCP server
mcp = FastMCP("twelvetake-reaper-mcp")

# Request counter for file-based fallback
request_counter = 0

# HTTP client (reused for connection pooling)
_http_client = None


def get_http_client():
    """Get or create HTTP client."""
    global _http_client
    if _http_client is None and HTTPX_AVAILABLE:
        _http_client = httpx.Client(timeout=5.0)
    return _http_client


# --- Communication Layer ---

async def reaper_call_http(func: str, args: list) -> dict:
    """Call a REAPER function via HTTP bridge."""
    if not HTTPX_AVAILABLE:
        return {"ok": False, "error": "httpx not installed", "fallback": True}

    client = get_http_client()
    if client is None:
        return {"ok": False, "error": "HTTP client not available", "fallback": True}

    try:
        response = client.post(
            f"{REAPER_URL}/call",
            json={"func": func, "args": args},
            timeout=5.0
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {"ok": False, "error": f"HTTP {response.status_code}", "fallback": True}
    except httpx.ConnectError:
        return {"ok": False, "error": "Cannot connect to REAPER HTTP bridge", "fallback": True}
    except httpx.TimeoutException:
        return {"ok": False, "error": "HTTP request timed out", "fallback": True}
    except Exception as e:
        return {"ok": False, "error": f"HTTP error: {str(e)}", "fallback": True}


async def reaper_call_file(func: str, args: list) -> dict:
    """Call a REAPER function via file-based bridge."""
    global request_counter
    request_counter = (request_counter % 999) + 1

    # Ensure bridge directory exists
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    request_file = BRIDGE_DIR / f"request_{request_counter}.json"
    response_file = BRIDGE_DIR / f"response_{request_counter}.json"

    request_data = {"func": func, "args": args}

    try:
        # Clean up old response file
        try:
            response_file.unlink(missing_ok=True)
        except:
            pass

        # Write request
        request_file.write_text(json.dumps(request_data))

        # Wait for response
        start_time = time.time()
        while time.time() - start_time < FILE_TIMEOUT:
            if response_file.exists():
                try:
                    response_text = response_file.read_text()
                    if response_text.strip():
                        response_data = json.loads(response_text)
                        # Clean up
                        try:
                            request_file.unlink(missing_ok=True)
                            response_file.unlink(missing_ok=True)
                        except:
                            pass
                        return response_data
                except json.JSONDecodeError:
                    pass
            await asyncio.sleep(FILE_POLL_INTERVAL)

        # Timeout
        try:
            request_file.unlink(missing_ok=True)
        except:
            pass

        return {
            "ok": False,
            "error": "File request timed out",
            "hint": "Make sure the REAPER bridge script is running"
        }
    except Exception as e:
        return {"ok": False, "error": f"File request failed: {str(e)}"}


async def reaper_call(func: str, *args) -> dict:
    """
    Call a REAPER function via bridge.

    Uses HTTP by default, falls back to file-based if HTTP unavailable.
    Set REAPER_COMM_MODE environment variable to force a mode:
    - "http": HTTP only
    - "file": File-based only
    - "auto": HTTP with file fallback (default)
    """
    args_list = list(args)

    if COMM_MODE == "file":
        return await reaper_call_file(func, args_list)
    elif COMM_MODE == "http":
        return await reaper_call_http(func, args_list)
    else:  # auto mode
        result = await reaper_call_http(func, args_list)
        if result.get("fallback"):
            # HTTP failed, try file-based
            return await reaper_call_file(func, args_list)
        return result


# --- TRACK OPERATIONS ---

@mcp.tool()
async def get_track_count() -> dict:
    """Get the total number of tracks in the current REAPER project (excluding master track)."""
    return await reaper_call("CountTracks", 0)


@mcp.tool()
async def get_track(track_index: int) -> dict:
    """
    Get information about a track.

    Args:
        track_index: Track index (0-based). Use -1 for the master track.

    Returns:
        Track info including name, volume_db, pan, mute, solo status.
    """
    return await reaper_call("GetTrackInfo", track_index)


@mcp.tool()
async def get_all_tracks() -> dict:
    """Get information about all tracks in the project."""
    return await reaper_call("GetAllTracksInfo")


@mcp.tool()
async def get_master_track() -> dict:
    """Get information about the master track."""
    return await reaper_call("GetTrackInfo", -1)


@mcp.tool()
async def insert_track(index: int = None, name: str = None) -> dict:
    """
    Insert a new track at the specified index.

    Args:
        index: Position to insert track (0-based). If not specified, adds at end.
        name: Optional name for the new track.

    Returns:
        Info about the created track.
    """
    # Get current count if no index specified
    if index is None:
        count_result = await reaper_call("CountTracks", 0)
        index = count_result.get("ret", 0)

    result = await reaper_call("InsertTrackAtIndex", index, True)

    # Set name if provided
    if name and result.get("ok"):
        await reaper_call("GetSetMediaTrackInfo_String", 0, index, "P_NAME", name, True)

    return result


@mcp.tool()
async def delete_track(track_index: int) -> dict:
    """
    Delete a track.

    Args:
        track_index: Track index to delete (0-based). Cannot delete master track (-1).
    """
    if track_index == -1:
        return {"ok": False, "error": "Cannot delete master track"}
    return await reaper_call("DeleteTrack", 0, track_index)


@mcp.tool()
async def set_track_name(track_index: int, name: str) -> dict:
    """
    Set the name of a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        name: New name for the track.
    """
    return await reaper_call("GetSetMediaTrackInfo_String", track_index, "P_NAME", name, True)


@mcp.tool()
async def set_track_volume(track_index: int, volume_db: float) -> dict:
    """
    Set the volume of a track in decibels.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        volume_db: Volume in dB (0 = unity gain, -inf to +12 typical range).
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "D_VOL", db_to_linear(volume_db))


@mcp.tool()
async def set_track_pan(track_index: int, pan: float) -> dict:
    """
    Set the pan position of a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        pan: Pan position from -1.0 (full left) to 1.0 (full right). 0 = center.
    """
    pan = max(-1.0, min(1.0, pan))
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "D_PAN", pan)


@mcp.tool()
async def set_track_mute(track_index: int, mute: bool) -> dict:
    """
    Set the mute state of a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        mute: True to mute, False to unmute.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "B_MUTE", 1 if mute else 0)


@mcp.tool()
async def set_track_solo(track_index: int, solo: bool) -> dict:
    """
    Set the solo state of a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        solo: True to solo, False to unsolo.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_SOLO", 1 if solo else 0)


# --- FX OPERATIONS ---

@mcp.tool()
async def track_fx_get_count(track_index: int) -> dict:
    """
    Get the number of FX plugins on a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.

    Returns:
        Object with 'ret' field containing count.
    """
    return await reaper_call("TrackFX_GetCount", track_index)


@mcp.tool()
async def track_fx_get_list(track_index: int) -> dict:
    """
    Get list of all FX plugins on a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.

    Returns:
        Object with 'fx' array containing each FX's index, name, and enabled state.
    """
    # Use the DSL function which returns detailed info
    return await reaper_call("GetTrackInfo", track_index)


@mcp.tool()
async def track_fx_add_by_name(track_index: int, fx_name: str) -> dict:
    """
    Add an FX plugin to a track by name.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_name: Name of the FX plugin to add (e.g., "ReaEQ", "ReaComp", "ReaLimit").
                 Use the exact plugin name as it appears in REAPER's FX browser.

    Returns:
        Info about the added FX including its index.
    """
    # TrackFX_AddByName(track, fxname, recFX, instantiate)
    # -1 for instantiate means add to end of chain
    return await reaper_call("TrackFX_AddByName", track_index, fx_name, False, -1)


@mcp.tool()
async def track_fx_delete(track_index: int, fx_index: int) -> dict:
    """
    Remove an FX plugin from a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
    """
    return await reaper_call("TrackFX_Delete", track_index, fx_index)


@mcp.tool()
async def track_fx_get_name(track_index: int, fx_index: int) -> dict:
    """
    Get the name of an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
    """
    return await reaper_call("TrackFX_GetFXName", track_index, fx_index, "")


@mcp.tool()
async def track_fx_get_enabled(track_index: int, fx_index: int) -> dict:
    """
    Get the enabled state of an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.

    Returns:
        Object with 'ret' field (boolean).
    """
    return await reaper_call("TrackFX_GetEnabled", track_index, fx_index)


@mcp.tool()
async def track_fx_set_enabled(track_index: int, fx_index: int, enabled: bool) -> dict:
    """
    Enable or disable an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
        enabled: True to enable, False to bypass.
    """
    return await reaper_call("TrackFX_SetEnabled", track_index, fx_index, enabled)


@mcp.tool()
async def track_fx_get_num_params(track_index: int, fx_index: int) -> dict:
    """
    Get the number of parameters for an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
    """
    return await reaper_call("TrackFX_GetNumParams", track_index, fx_index)


@mcp.tool()
async def track_fx_get_param_name(track_index: int, fx_index: int, param_index: int) -> dict:
    """
    Get the name of an FX parameter.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
        param_index: Parameter index (0-based).
    """
    return await reaper_call("TrackFX_GetParamName", track_index, fx_index, param_index, "")


@mcp.tool()
async def track_fx_get_param(track_index: int, fx_index: int, param_index: int) -> dict:
    """
    Get a specific parameter value of an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
        param_index: Parameter index (0-based).

    Returns:
        Object with value, min, max for the parameter.
    """
    return await reaper_call("TrackFX_GetParam", track_index, fx_index, param_index)


@mcp.tool()
async def track_fx_set_param(track_index: int, fx_index: int, param_index: int, value: float) -> dict:
    """
    Set a parameter value on an FX plugin.

    Args:
        track_index: Track index (0-based) or -1 for master track.
        fx_index: FX index (0-based) in the FX chain.
        param_index: Parameter index (0-based).
        value: New value for the parameter (typically normalized 0-1, check min/max).
    """
    return await reaper_call("TrackFX_SetParam", track_index, fx_index, param_index, value)


# --- ROUTING OPERATIONS ---

@mcp.tool()
async def create_send(src_track: int, dest_track: int) -> dict:
    """
    Create a send from one track to another.

    Args:
        src_track: Source track index (0-based).
        dest_track: Destination track index (0-based).

    Returns:
        Object with send_index.
    """
    return await reaper_call("CreateTrackSend", src_track, dest_track)


@mcp.tool()
async def delete_send(track_index: int, send_index: int) -> dict:
    """
    Delete a send from a track.

    Args:
        track_index: Source track index (0-based).
        send_index: Send index (0-based) to delete.
    """
    # RemoveTrackSend(track, category, sendidx) - category 0 = sends
    return await reaper_call("RemoveTrackSend", track_index, 0, send_index)


@mcp.tool()
async def set_send_volume(track_index: int, send_index: int, volume_db: float) -> dict:
    """
    Set the volume of a track send.

    Args:
        track_index: Source track index (0-based).
        send_index: Send index (0-based).
        volume_db: Send volume in dB.
    """
    return await reaper_call("SetTrackSendUIVol", track_index, send_index, db_to_linear(volume_db), 0)


@mcp.tool()
async def get_track_num_sends(track_index: int) -> dict:
    """
    Get the number of sends from a track.

    Args:
        track_index: Track index (0-based).
    """
    # GetTrackNumSends(track, category) - category 0 = sends
    return await reaper_call("GetTrackNumSends", track_index, 0)


@mcp.tool()
async def set_send_dest_channels(track_index: int, send_index: int, dest_chan: int) -> dict:
    """
    Set the destination channels for a send (used for sidechain routing).

    Args:
        track_index: Source track index (0-based).
        send_index: Send index (0-based).
        dest_chan: Destination channel pair (0=1-2 main, 2=3-4 sidechain, 4=5-6, etc.).
                   For sidechain compression, use 2 to route to channels 3-4.

    Returns:
        Object with success status.
    """
    # SetTrackSendInfo_Value(track, category, send_idx, param_name, value)
    # category 0 = sends, I_DSTCHAN sets destination channels
    return await reaper_call("SetTrackSendInfo_Value", track_index, 0, send_index, "I_DSTCHAN", dest_chan)


@mcp.tool()
async def set_send_source_channels(track_index: int, send_index: int, src_chan: int) -> dict:
    """
    Set the source channels for a send.

    Args:
        track_index: Source track index (0-based).
        send_index: Send index (0-based).
        src_chan: Source channel (-1=none, 0=stereo 1-2, 1024+n=mono from channel n).

    Returns:
        Object with success status.
    """
    return await reaper_call("SetTrackSendInfo_Value", track_index, 0, send_index, "I_SRCCHAN", src_chan)


@mcp.tool()
async def setup_sidechain_send(src_track: int, dest_track: int, volume_db: float = 0.0) -> dict:
    """
    Create a sidechain send from one track to another track's FX sidechain input.

    This creates a send routed to channels 3-4 of the destination track,
    which is the standard sidechain input for compressors like ReaComp.

    Args:
        src_track: Source/trigger track index (e.g., kick drum).
        dest_track: Destination track index (e.g., bass with compressor).
        volume_db: Send volume in dB (default 0dB = unity).

    Returns:
        Object with send_index and routing info.
    """
    # Create the send
    send_result = await reaper_call("CreateTrackSend", src_track, dest_track)
    send_index = send_result.get("ret", 0)

    if not send_result.get("ok", False):
        return send_result

    # Route to channels 3-4 (sidechain input)
    # I_DSTCHAN: 0=1-2, 2=3-4 (sidechain), 4=5-6, etc.
    await reaper_call("SetTrackSendInfo_Value", src_track, 0, send_index, "I_DSTCHAN", 2)

    await reaper_call("SetTrackSendUIVol", src_track, send_index, db_to_linear(volume_db), 0)

    return {
        "ok": True,
        "src_track": src_track,
        "dest_track": dest_track,
        "send_index": send_index,
        "dest_channels": "3-4 (sidechain)",
        "volume_db": volume_db,
        "note": "Send created to sidechain input. Configure compressor to use aux/sidechain input."
    }


@mcp.tool()
async def configure_reacomp_sidechain(track_index: int, fx_index: int, use_sidechain: bool = True) -> dict:
    """
    Configure ReaComp to use sidechain input for detection.

    Args:
        track_index: Track index (0-based) where ReaComp is located.
        fx_index: FX index (0-based) of ReaComp in the FX chain.
        use_sidechain: True to use auxiliary input (channels 3-4), False for main input.

    Returns:
        Object with configuration status.
    """
    # ReaComp parameter 8 (SignIn) controls detector input
    # 0 = main input, 1 = auxiliary/sidechain input
    value = 1.0 if use_sidechain else 0.0
    result = await reaper_call("TrackFX_SetParam", track_index, fx_index, 8, value)

    return {
        "ok": result.get("ok", False),
        "track_index": track_index,
        "fx_index": fx_index,
        "detector_input": "auxiliary (sidechain)" if use_sidechain else "main input",
        "note": "ReaComp now listening to " + ("sidechain input (channels 3-4)" if use_sidechain else "main input")
    }


@mcp.tool()
async def setup_sidechain_compression(
    trigger_track: int,
    target_track: int,
    compressor_fx_index: int,
    send_volume_db: float = 0.0
) -> dict:
    """
    Complete sidechain compression setup: creates send and configures compressor.

    This is the all-in-one function for setting up sidechain compression.
    It creates a send from the trigger track to the target track's sidechain input
    and configures ReaComp to listen to that sidechain.

    Args:
        trigger_track: Track that triggers compression (e.g., kick drum = track 0).
        target_track: Track to be compressed (e.g., bass = track 1).
        compressor_fx_index: Index of ReaComp in target track's FX chain.
        send_volume_db: Sidechain send volume in dB (default 0dB).

    Returns:
        Object with complete setup info.

    Example:
        For kick-triggered bass compression where:
        - Drums are on track 0
        - Bass is on track 1 with ReaComp at FX index 2
        Call: setup_sidechain_compression(0, 1, 2)
    """
    # Step 1: Create sidechain send
    send_result = await reaper_call("CreateTrackSend", trigger_track, target_track)
    if not send_result.get("ok", False):
        return {"ok": False, "error": "Failed to create send", "details": send_result}

    send_index = send_result.get("ret", 0)

    # Step 2: Route send to channels 3-4 (sidechain input)
    await reaper_call("SetTrackSendInfo_Value", trigger_track, 0, send_index, "I_DSTCHAN", 2)

    await reaper_call("SetTrackSendUIVol", trigger_track, send_index, db_to_linear(send_volume_db), 0)

    # Step 4: Configure ReaComp to use sidechain input
    await reaper_call("TrackFX_SetParam", target_track, compressor_fx_index, 8, 1.0)

    return {
        "ok": True,
        "trigger_track": trigger_track,
        "target_track": target_track,
        "send_index": send_index,
        "compressor_fx_index": compressor_fx_index,
        "send_volume_db": send_volume_db,
        "routing": "Trigger -> Target channels 3-4 (sidechain)",
        "compressor": "ReaComp detector set to auxiliary input",
        "note": "Sidechain compression fully configured. Adjust compressor threshold/ratio as needed."
    }


# --- TRANSPORT OPERATIONS ---

@mcp.tool()
async def play() -> dict:
    """Start playback in REAPER."""
    return await reaper_call("OnPlayButton")


@mcp.tool()
async def stop() -> dict:
    """Stop playback in REAPER."""
    return await reaper_call("OnStopButton")


@mcp.tool()
async def get_play_state() -> dict:
    """
    Get the current playback state.

    Returns:
        Object with play state info.
    """
    return await reaper_call("GetPlayState")


@mcp.tool()
async def get_cursor_position() -> dict:
    """
    Get the edit cursor position.

    Returns:
        Object with cursor position in seconds.
    """
    return await reaper_call("GetCursorPosition")


@mcp.tool()
async def set_cursor_position(position: float) -> dict:
    """
    Set the edit cursor position.

    Args:
        position: Position in seconds from project start.
    """
    # SetEditCurPos(time, moveview, seekplay)
    return await reaper_call("SetEditCurPos", position, True, False)


# --- PROJECT OPERATIONS ---

@mcp.tool()
async def save_project() -> dict:
    """Save the current REAPER project."""
    return await reaper_call("Main_SaveProject", 0, False)


@mcp.tool()
async def get_project_path() -> dict:
    """Get the project path."""
    return await reaper_call("GetProjectPath", "")


@mcp.tool()
async def get_project_name() -> dict:
    """Get the project name."""
    return await reaper_call("GetProjectName", 0, "")


@mcp.tool()
async def get_tempo() -> dict:
    """Get the project tempo."""
    return await reaper_call("Master_GetTempo")


@mcp.tool()
async def get_time_signature() -> dict:
    """Get the project time signature."""
    return await reaper_call("GetTimeSignature")


# --- MIXING/MASTERING HELPERS ---

@mcp.tool()
async def add_mastering_chain() -> dict:
    """
    Add a standard mastering chain to the master track.

    Adds the following plugins in order:
    1. ReaEQ (corrective EQ)
    2. ReaComp (glue compression)
    3. ReaEQ (tonal shaping)
    4. ReaLimit (brickwall limiter)

    Returns:
        Object with list of added FX indices.
    """
    results = []
    fx_chain = ["ReaEQ", "ReaComp", "ReaEQ", "ReaLimit"]

    for fx_name in fx_chain:
        result = await reaper_call("TrackFX_AddByName", -1, fx_name, False, -1)
        results.append(result)

    return {
        "ok": True,
        "track": "master",
        "added_fx": results,
        "chain": fx_chain,
        "note": "Adjust parameters as needed. ReaLimit ceiling should be set to -0.3dB for streaming."
    }


@mcp.tool()
async def add_parallel_compression(track_index: int, blend_db: float = -6.0) -> dict:
    """
    Set up New York style parallel compression for a track.

    Creates a new bus track with heavy compression, fed by a send from the source track.

    Args:
        track_index: Source track index (0-based).
        blend_db: Send level in dB for the compressed signal (default -6dB).

    Returns:
        Object with bus_track_index, send_index, and compressor_fx_index.
    """
    # Get current track count
    count_result = await reaper_call("CountTracks", 0)
    new_track_index = count_result.get("ret", 0)

    # Create parallel compression bus
    await reaper_call("InsertTrackAtIndex", new_track_index, True)
    await reaper_call("GetSetMediaTrackInfo_String", 0, new_track_index, "P_NAME", "Parallel Comp Bus", True)

    # Create send from source to bus
    send_result = await reaper_call("CreateTrackSend", track_index, new_track_index)

    await reaper_call("SetTrackSendUIVol", track_index, send_result.get("ret", 0), db_to_linear(blend_db), 0)

    # Add compressor
    comp_result = await reaper_call("TrackFX_AddByName", new_track_index, "ReaComp", False, -1)

    return {
        "ok": True,
        "source_track": track_index,
        "bus_track_index": new_track_index,
        "send_index": send_result.get("ret"),
        "compressor_fx_index": comp_result.get("ret"),
        "blend_db": blend_db,
        "note": "Configure compressor for heavy compression. Adjust send level to taste."
    }


@mcp.tool()
async def create_bus(name: str, source_track_indices: list[int]) -> dict:
    """
    Create a submix/stem bus and route specified tracks to it.

    Args:
        name: Name for the bus track.
        source_track_indices: List of track indices to route to this bus.

    Returns:
        Object with bus_track_index and routing info.
    """
    # Get track count
    count_result = await reaper_call("CountTracks", 0)
    new_track_index = count_result.get("ret", 0)

    # Create bus track
    await reaper_call("InsertTrackAtIndex", new_track_index, True)
    await reaper_call("GetSetMediaTrackInfo_String", 0, new_track_index, "P_NAME", name, True)

    # Create sends from each source track
    sends_created = []
    for src_idx in source_track_indices:
        send_result = await reaper_call("CreateTrackSend", src_idx, new_track_index)
        sends_created.append({
            "source_track": src_idx,
            "send_index": send_result.get("ret")
        })

    return {
        "ok": True,
        "bus_track_index": new_track_index,
        "bus_name": name,
        "sends": sends_created,
        "note": f"Created bus '{name}' with {len(sends_created)} sends."
    }


@mcp.tool()
async def add_eq(track_index: int) -> dict:
    """
    Add ReaEQ to a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.

    Returns:
        Object with fx_index.
    """
    return await reaper_call("TrackFX_AddByName", track_index, "ReaEQ", False, -1)


@mcp.tool()
async def add_compressor(track_index: int) -> dict:
    """
    Add ReaComp to a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.

    Returns:
        Object with fx_index.
    """
    return await reaper_call("TrackFX_AddByName", track_index, "ReaComp", False, -1)


@mcp.tool()
async def add_limiter(track_index: int) -> dict:
    """
    Add ReaLimit (brickwall limiter) to a track.

    Args:
        track_index: Track index (0-based) or -1 for master track.

    Returns:
        Object with fx_index.
    """
    return await reaper_call("TrackFX_AddByName", track_index, "ReaLimit", False, -1)


# --- MIDI OPERATIONS ---

@mcp.tool()
async def create_midi_item(track_index: int, position: float, length: float) -> dict:
    """
    Create an empty MIDI item on a track.

    Args:
        track_index: Track index (0-based).
        position: Start position in seconds.
        length: Length in seconds.

    Returns:
        Object with item info.
    """
    return await reaper_call("CreateNewMIDIItemInProj", track_index, position, position + length, False)


@mcp.tool()
async def get_midi_item(track_index: int, item_index: int) -> dict:
    """
    Get information about a MIDI item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based) on the track.

    Returns:
        Object with item info including position, length, note count.
    """
    return await reaper_call("GetMIDIItemInfo", track_index, item_index)


@mcp.tool()
async def add_midi_note(
    track_index: int,
    item_index: int,
    pitch: int,
    velocity: int,
    start_ppq: float,
    end_ppq: float,
    channel: int = 0
) -> dict:
    """
    Add a MIDI note to an item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based) on the track.
        pitch: MIDI note number (0-127, 60 = middle C).
        velocity: Note velocity (1-127).
        start_ppq: Start position in PPQ (pulses per quarter note).
        end_ppq: End position in PPQ.
        channel: MIDI channel (0-15, default 0).

    Returns:
        Object with note index.
    """
    return await reaper_call("MIDI_InsertNote", track_index, item_index, False, False, start_ppq, end_ppq, channel, pitch, velocity, False)


@mcp.tool()
async def add_midi_notes_batch(
    track_index: int,
    item_index: int,
    notes: list
) -> dict:
    """
    Add multiple MIDI notes to an item in one call.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        notes: List of note dicts with keys: pitch, velocity, start_ppq, end_ppq, channel (optional).

    Returns:
        Object with count of notes added.
    """
    results = []
    for note in notes:
        result = await reaper_call(
            "MIDI_InsertNote",
            track_index,
            item_index,
            False,
            False,
            note.get("start_ppq", 0),
            note.get("end_ppq", 480),
            note.get("channel", 0),
            note.get("pitch", 60),
            note.get("velocity", 100),
            False
        )
        results.append(result)
    return {"ok": True, "notes_added": len(results), "results": results}


@mcp.tool()
async def get_midi_notes(track_index: int, item_index: int) -> dict:
    """
    Get all MIDI notes from an item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).

    Returns:
        Object with list of notes.
    """
    return await reaper_call("GetMIDINotes", track_index, item_index)


@mcp.tool()
async def delete_midi_note(track_index: int, item_index: int, note_index: int) -> dict:
    """
    Delete a MIDI note from an item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        note_index: Note index (0-based).

    Returns:
        Object with success status.
    """
    return await reaper_call("MIDI_DeleteNote", track_index, item_index, note_index)


@mcp.tool()
async def clear_midi_item(track_index: int, item_index: int) -> dict:
    """
    Delete all MIDI notes from an item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).

    Returns:
        Object with count of notes deleted.
    """
    return await reaper_call("ClearMIDIItem", track_index, item_index)


@mcp.tool()
async def set_midi_note_velocity(
    track_index: int,
    item_index: int,
    note_index: int,
    velocity: int
) -> dict:
    """
    Set the velocity of a MIDI note.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        note_index: Note index (0-based).
        velocity: New velocity (1-127).

    Returns:
        Object with success status.
    """
    return await reaper_call("MIDI_SetNote", track_index, item_index, note_index, None, None, None, None, None, velocity, False)


# --- AUDIO ITEM OPERATIONS ---

@mcp.tool()
async def insert_audio_file(track_index: int, file_path: str, position: float) -> dict:
    """
    Insert an audio file onto a track.

    Args:
        track_index: Track index (0-based).
        file_path: Full path to the audio file.
        position: Position in seconds.

    Returns:
        Object with item info.
    """
    return await reaper_call("InsertMedia", file_path, 0, track_index, position)


@mcp.tool()
async def get_track_items(track_index: int) -> dict:
    """
    Get all media items on a track.

    Args:
        track_index: Track index (0-based).

    Returns:
        Object with list of items.
    """
    return await reaper_call("GetTrackItems", track_index)


@mcp.tool()
async def get_item_info(track_index: int, item_index: int) -> dict:
    """
    Get information about a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).

    Returns:
        Object with item properties (position, length, take info, etc.).
    """
    return await reaper_call("GetItemInfo", track_index, item_index)


@mcp.tool()
async def set_item_position(track_index: int, item_index: int, position: float) -> dict:
    """
    Set the position of a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        position: New position in seconds.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "D_POSITION", position)


@mcp.tool()
async def set_item_length(track_index: int, item_index: int, length: float) -> dict:
    """
    Set the length of a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        length: New length in seconds.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "D_LENGTH", length)


@mcp.tool()
async def delete_item(track_index: int, item_index: int) -> dict:
    """
    Delete a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).

    Returns:
        Object with success status.
    """
    return await reaper_call("DeleteTrackMediaItem", track_index, item_index)


@mcp.tool()
async def duplicate_item(track_index: int, item_index: int) -> dict:
    """
    Duplicate a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).

    Returns:
        Object with new item info.
    """
    return await reaper_call("DuplicateItem", track_index, item_index)


@mcp.tool()
async def split_item(track_index: int, item_index: int, position: float) -> dict:
    """
    Split a media item at a position.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        position: Split position in seconds (absolute project time).

    Returns:
        Object with info about both resulting items.
    """
    return await reaper_call("SplitMediaItem", track_index, item_index, position)


@mcp.tool()
async def set_item_mute(track_index: int, item_index: int, mute: bool) -> dict:
    """
    Mute or unmute a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        mute: True to mute, False to unmute.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "B_MUTE", 1 if mute else 0)


@mcp.tool()
async def set_item_volume(track_index: int, item_index: int, volume_db: float) -> dict:
    """
    Set the volume of a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        volume_db: Volume in dB.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "D_VOL", db_to_linear(volume_db))


@mcp.tool()
async def set_item_fade_in(track_index: int, item_index: int, length: float) -> dict:
    """
    Set the fade-in length of a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        length: Fade-in length in seconds.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "D_FADEINLEN", length)


@mcp.tool()
async def set_item_fade_out(track_index: int, item_index: int, length: float) -> dict:
    """
    Set the fade-out length of a media item.

    Args:
        track_index: Track index (0-based).
        item_index: Item index (0-based).
        length: Fade-out length in seconds.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaItemInfo_Value", track_index, item_index, "D_FADEOUTLEN", length)


# --- PROJECT OPERATIONS (Extended) ---

@mcp.tool()
async def set_tempo(bpm: float) -> dict:
    """
    Set the project tempo.

    Args:
        bpm: Tempo in beats per minute.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetCurrentBPM", 0, bpm, True)


@mcp.tool()
async def set_time_signature(numerator: int, denominator: int) -> dict:
    """
    Set the project time signature.

    Args:
        numerator: Beats per measure (e.g., 4 for 4/4).
        denominator: Beat unit (e.g., 4 for quarter note).

    Returns:
        Object with success status.
    """
    return await reaper_call("SetTimeSignature", numerator, denominator)


@mcp.tool()
async def create_project(name: str = None) -> dict:
    """
    Create a new REAPER project.

    Args:
        name: Optional project name.

    Returns:
        Object with success status.
    """
    result = await reaper_call("Main_OnCommand", 40023, 0)  # File: New project
    if name:
        await reaper_call("Main_SaveProject", 0, False)
    return result


@mcp.tool()
async def open_project(path: str) -> dict:
    """
    Open a REAPER project file.

    Args:
        path: Full path to the .rpp file.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_openProject", path)


@mcp.tool()
async def render_project(
    output_path: str,
    start_time: float = None,
    end_time: float = None,
    tail_seconds: float = 0
) -> dict:
    """
    Render the project to an audio file.

    Args:
        output_path: Full path for output file (extension determines format).
        start_time: Start time in seconds (None = project start).
        end_time: End time in seconds (None = project end).
        tail_seconds: Extra seconds to render at end for reverb tails.

    Returns:
        Object with render status.
    """
    return await reaper_call("RenderProject", output_path, start_time, end_time, tail_seconds)


@mcp.tool()
async def render_region(region_index: int, output_path: str) -> dict:
    """
    Render a specific region to an audio file.

    Args:
        region_index: Region index (0-based).
        output_path: Full path for output file.

    Returns:
        Object with render status.
    """
    return await reaper_call("RenderRegion", region_index, output_path)


# --- MARKERS AND REGIONS ---

@mcp.tool()
async def add_marker(position: float, name: str = "", color: int = 0) -> dict:
    """
    Add a marker at a position.

    Args:
        position: Position in seconds.
        name: Marker name.
        color: Marker color (0 = default).

    Returns:
        Object with marker index.
    """
    return await reaper_call("AddProjectMarker2", 0, False, position, 0, name, -1, color)


@mcp.tool()
async def add_region(start: float, end: float, name: str = "", color: int = 0) -> dict:
    """
    Add a region.

    Args:
        start: Start position in seconds.
        end: End position in seconds.
        name: Region name.
        color: Region color (0 = default).

    Returns:
        Object with region index.
    """
    return await reaper_call("AddProjectMarker2", 0, True, start, end, name, -1, color)


@mcp.tool()
async def get_markers() -> dict:
    """
    Get all markers in the project.

    Returns:
        Object with list of markers (position, name, index).
    """
    return await reaper_call("GetProjectMarkers")


@mcp.tool()
async def get_regions() -> dict:
    """
    Get all regions in the project.

    Returns:
        Object with list of regions (start, end, name, index).
    """
    return await reaper_call("GetProjectRegions")


@mcp.tool()
async def delete_marker(marker_index: int) -> dict:
    """
    Delete a marker by index.

    Args:
        marker_index: Marker index.

    Returns:
        Object with success status.
    """
    return await reaper_call("DeleteProjectMarker", 0, marker_index, False)


@mcp.tool()
async def delete_region(region_index: int) -> dict:
    """
    Delete a region by index.

    Args:
        region_index: Region index.

    Returns:
        Object with success status.
    """
    return await reaper_call("DeleteProjectMarker", 0, region_index, True)


@mcp.tool()
async def go_to_marker(marker_index: int) -> dict:
    """
    Move the edit cursor to a marker.

    Args:
        marker_index: Marker index.

    Returns:
        Object with success status.
    """
    return await reaper_call("GoToMarker", 0, marker_index, False)


@mcp.tool()
async def go_to_region(region_index: int) -> dict:
    """
    Move the edit cursor to a region start.

    Args:
        region_index: Region index.

    Returns:
        Object with success status.
    """
    return await reaper_call("GoToRegion", 0, region_index, False)


# --- AUTOMATION ---

@mcp.tool()
async def get_track_envelope(track_index: int, envelope_name: str) -> dict:
    """
    Get a track envelope by name.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name (e.g., "Volume", "Pan", "Mute").

    Returns:
        Object with envelope info.
    """
    return await reaper_call("GetTrackEnvelopeByName", track_index, envelope_name)


@mcp.tool()
async def get_envelope_point_count(track_index: int, envelope_name: str) -> dict:
    """
    Get the number of points in an envelope.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.

    Returns:
        Object with point count.
    """
    return await reaper_call("CountEnvelopePoints", track_index, envelope_name)


@mcp.tool()
async def add_envelope_point(
    track_index: int,
    envelope_name: str,
    time: float,
    value: float,
    shape: int = 0
) -> dict:
    """
    Add a point to an envelope.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.
        time: Time position in seconds.
        value: Envelope value (0.0-1.0 for most envelopes).
        shape: Point shape (0=linear, 1=square, 2=slow start/end, 3=fast start, 4=fast end, 5=bezier).

    Returns:
        Object with point index.
    """
    return await reaper_call("InsertEnvelopePoint", track_index, envelope_name, time, value, shape, 0, False, False)


@mcp.tool()
async def get_envelope_points(track_index: int, envelope_name: str) -> dict:
    """
    Get all points from an envelope.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.

    Returns:
        Object with list of points (time, value, shape).
    """
    return await reaper_call("GetEnvelopePoints", track_index, envelope_name)


@mcp.tool()
async def delete_envelope_point(track_index: int, envelope_name: str, point_index: int) -> dict:
    """
    Delete an envelope point.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.
        point_index: Point index (0-based).

    Returns:
        Object with success status.
    """
    return await reaper_call("DeleteEnvelopePoint", track_index, envelope_name, point_index)


@mcp.tool()
async def clear_envelope(track_index: int, envelope_name: str) -> dict:
    """
    Delete all points from an envelope.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.

    Returns:
        Object with success status.
    """
    return await reaper_call("ClearEnvelope", track_index, envelope_name)


@mcp.tool()
async def set_track_automation_mode(track_index: int, mode: int) -> dict:
    """
    Set the automation mode for a track.

    Args:
        track_index: Track index (0-based) or -1 for master.
        mode: 0=trim/read, 1=read, 2=touch, 3=write, 4=latch.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_AUTOMODE", mode)


@mcp.tool()
async def arm_track_envelope(track_index: int, envelope_name: str, arm: bool = True) -> dict:
    """
    Arm or disarm an envelope for recording.

    Args:
        track_index: Track index (0-based) or -1 for master.
        envelope_name: Envelope name.
        arm: True to arm, False to disarm.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetEnvelopeArm", track_index, envelope_name, arm)


# --- SELECTION AND EDITING ---

@mcp.tool()
async def undo() -> dict:
    """
    Undo the last action in REAPER.

    Returns:
        Object with undo description.
    """
    return await reaper_call("Undo_DoUndo2", 0)


@mcp.tool()
async def redo() -> dict:
    """
    Redo the last undone action in REAPER.

    Returns:
        Object with redo description.
    """
    return await reaper_call("Undo_DoRedo2", 0)


@mcp.tool()
async def get_undo_state() -> dict:
    """
    Get the current undo/redo state.

    Returns:
        Object with undo and redo descriptions.
    """
    return await reaper_call("GetUndoState")


@mcp.tool()
async def select_track(track_index: int, exclusive: bool = True) -> dict:
    """
    Select a track.

    Args:
        track_index: Track index (0-based).
        exclusive: If True, deselect other tracks first.

    Returns:
        Object with success status.
    """
    if exclusive:
        await reaper_call("Main_OnCommand", 40297, 0)  # Unselect all tracks
    return await reaper_call("SetTrackSelected", track_index, True)


@mcp.tool()
async def select_all_tracks() -> dict:
    """
    Select all tracks.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40296, 0)  # Select all tracks


@mcp.tool()
async def unselect_all_tracks() -> dict:
    """
    Unselect all tracks.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40297, 0)  # Unselect all tracks


@mcp.tool()
async def get_selected_tracks() -> dict:
    """
    Get indices of all selected tracks.

    Returns:
        Object with list of selected track indices.
    """
    return await reaper_call("GetSelectedTracks")


@mcp.tool()
async def select_all_items() -> dict:
    """
    Select all media items.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40182, 0)  # Select all items


@mcp.tool()
async def unselect_all_items() -> dict:
    """
    Unselect all media items.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40289, 0)  # Unselect all items


@mcp.tool()
async def get_selected_items() -> dict:
    """
    Get all selected media items.

    Returns:
        Object with list of selected items.
    """
    return await reaper_call("GetSelectedItems")


@mcp.tool()
async def copy_selected_items() -> dict:
    """
    Copy selected items to clipboard.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40057, 0)  # Copy items


@mcp.tool()
async def cut_selected_items() -> dict:
    """
    Cut selected items to clipboard.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40059, 0)  # Cut items


@mcp.tool()
async def paste_items() -> dict:
    """
    Paste items from clipboard at edit cursor.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40058, 0)  # Paste items


@mcp.tool()
async def delete_selected_items() -> dict:
    """
    Delete all selected items.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40006, 0)  # Remove items


@mcp.tool()
async def set_time_selection(start: float, end: float) -> dict:
    """
    Set the time selection.

    Args:
        start: Start time in seconds.
        end: End time in seconds.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetTimeSelection", start, end)


@mcp.tool()
async def get_time_selection() -> dict:
    """
    Get the current time selection.

    Returns:
        Object with start and end times.
    """
    return await reaper_call("GetSet_LoopTimeRange", False, False, 0, 0, False)


@mcp.tool()
async def clear_time_selection() -> dict:
    """
    Clear the time selection.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40635, 0)  # Remove time selection


# --- MIXER ENHANCEMENTS ---

@mcp.tool()
async def set_track_phase(track_index: int, invert: bool) -> dict:
    """
    Set the phase inversion of a track.

    Args:
        track_index: Track index (0-based) or -1 for master.
        invert: True to invert phase, False for normal.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "B_PHASE", 1 if invert else 0)


@mcp.tool()
async def set_track_width(track_index: int, width: float) -> dict:
    """
    Set the stereo width of a track.

    Args:
        track_index: Track index (0-based) or -1 for master.
        width: Width value (0=mono, 1=stereo, 2=200% width).

    Returns:
        Object with success status.
    """
    width = max(0.0, min(2.0, width))
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "D_WIDTH", width)


@mcp.tool()
async def set_track_as_folder(track_index: int, folder_depth: int) -> dict:
    """
    Set a track as a folder parent or child.

    Args:
        track_index: Track index (0-based).
        folder_depth: 0=normal, 1=folder parent, -1=end of folder.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_FOLDERDEPTH", folder_depth)


@mcp.tool()
async def arm_track(track_index: int, arm: bool = True) -> dict:
    """
    Arm or disarm a track for recording.

    Args:
        track_index: Track index (0-based).
        arm: True to arm, False to disarm.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_RECARM", 1 if arm else 0)


@mcp.tool()
async def set_track_input(track_index: int, input_index: int) -> dict:
    """
    Set the record input for a track.

    Args:
        track_index: Track index (0-based).
        input_index: Input index (-1=no input, 0+=hardware inputs, 4096+=virtual MIDI).

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_RECINPUT", input_index)


@mcp.tool()
async def set_track_monitor(track_index: int, monitor: int) -> dict:
    """
    Set the monitor mode for a track.

    Args:
        track_index: Track index (0-based).
        monitor: 0=off, 1=normal, 2=not when playing.

    Returns:
        Object with success status.
    """
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_RECMON", monitor)


@mcp.tool()
async def set_track_color(track_index: int, r: int, g: int, b: int) -> dict:
    """
    Set the color of a track.

    Args:
        track_index: Track index (0-based).
        r: Red component (0-255).
        g: Green component (0-255).
        b: Blue component (0-255).

    Returns:
        Object with success status.
    """
    # REAPER uses native OS color format
    color = (r | (g << 8) | (b << 16)) | 0x1000000
    return await reaper_call("SetMediaTrackInfo_Value", track_index, "I_CUSTOMCOLOR", color)


@mcp.tool()
async def get_track_peak(track_index: int, channel: int = 0) -> dict:
    """
    Get the current peak level of a track.

    Args:
        track_index: Track index (0-based) or -1 for master.
        channel: Channel (0=left, 1=right).

    Returns:
        Object with peak value in dB.
    """
    return await reaper_call("Track_GetPeakInfo", track_index, channel)


# --- ADVANCED FEATURES ---

@mcp.tool()
async def run_action(action_id: int) -> dict:
    """
    Run a REAPER action by command ID.

    Args:
        action_id: REAPER action/command ID number.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", action_id, 0)


@mcp.tool()
async def run_action_by_name(action_name: str) -> dict:
    """
    Run a REAPER action by name.

    Args:
        action_name: Action name or command ID string (e.g., "_RS12345").

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommandEx", action_name, 0, 0)


@mcp.tool()
async def get_fx_presets(track_index: int, fx_index: int) -> dict:
    """
    Get list of presets available for an FX.

    Args:
        track_index: Track index (0-based) or -1 for master.
        fx_index: FX index (0-based).

    Returns:
        Object with list of preset names.
    """
    return await reaper_call("TrackFX_GetPresetList", track_index, fx_index)


@mcp.tool()
async def get_fx_preset(track_index: int, fx_index: int) -> dict:
    """
    Get the current preset name of an FX.

    Args:
        track_index: Track index (0-based) or -1 for master.
        fx_index: FX index (0-based).

    Returns:
        Object with current preset name.
    """
    return await reaper_call("TrackFX_GetPreset", track_index, fx_index, "")


@mcp.tool()
async def set_fx_preset(track_index: int, fx_index: int, preset_name: str) -> dict:
    """
    Set the preset of an FX.

    Args:
        track_index: Track index (0-based) or -1 for master.
        fx_index: FX index (0-based).
        preset_name: Preset name.

    Returns:
        Object with success status.
    """
    return await reaper_call("TrackFX_SetPreset", track_index, fx_index, preset_name)


@mcp.tool()
async def save_fx_preset(track_index: int, fx_index: int, preset_name: str) -> dict:
    """
    Save the current FX settings as a preset.

    Args:
        track_index: Track index (0-based) or -1 for master.
        fx_index: FX index (0-based).
        preset_name: Name for the new preset.

    Returns:
        Object with success status.
    """
    return await reaper_call("TrackFX_SavePreset", track_index, fx_index, preset_name)


@mcp.tool()
async def get_track_fx_chunk(track_index: int, fx_index: int) -> dict:
    """
    Get the raw state chunk from an FX plugin (includes preset/state data).

    Useful for reading VSTi state data like Toontrack EZkeys chord progressions.
    The chunk contains the full serialized state of the plugin.

    Args:
        track_index: Track index (0-based) or -1 for master.
        fx_index: FX index (0-based) in the FX chain.

    Returns:
        Object with 'chunk' containing the FX state data string.
    """
    return await reaper_call("GetFXChunk", track_index, fx_index)


@mcp.tool()
async def get_project_length() -> dict:
    """
    Get the length of the project (end of last item).

    Returns:
        Object with project length in seconds.
    """
    return await reaper_call("GetProjectLength", 0)


@mcp.tool()
async def get_project_summary() -> dict:
    """
    Get a comprehensive summary of the current REAPER project.

    Returns everything needed to understand the project state and give
    useful mixing/production advice in a single call.

    Returns:
        Object with:
        - project_name: Name of the project file
        - project_path: Full path to the project
        - tempo: Project tempo in BPM
        - time_signature: {numerator, denominator}
        - project_length: Length in seconds
        - track_count: Total number of tracks
        - tracks: List of track info objects, each containing:
            - index: Track index (0-based)
            - name: Track name
            - volume_db: Volume in decibels
            - pan: Pan position (-1 to 1)
            - mute: Boolean mute state
            - solo: Boolean solo state
            - fx_count: Number of FX plugins
            - fx_names: List of FX plugin names
        - master: Master track info {volume_db, fx_count, fx_names}
        - markers: List of {index, position, name}
        - regions: List of {index, start, end, name}
    """
    return await reaper_call("GetProjectSummary")


@mcp.tool()
async def get_play_position() -> dict:
    """
    Get the current playback position.

    Returns:
        Object with play position in seconds.
    """
    return await reaper_call("GetPlayPosition")


@mcp.tool()
async def record() -> dict:
    """
    Start recording in REAPER.

    Returns:
        Object with success status.
    """
    return await reaper_call("OnRecordButton")


@mcp.tool()
async def pause() -> dict:
    """
    Pause playback in REAPER.

    Returns:
        Object with success status.
    """
    return await reaper_call("OnPauseButton")


@mcp.tool()
async def toggle_repeat() -> dict:
    """
    Toggle repeat/loop mode.

    Returns:
        Object with new repeat state.
    """
    return await reaper_call("Main_OnCommand", 1068, 0)  # Toggle repeat


@mcp.tool()
async def get_repeat_state() -> dict:
    """
    Get the current repeat state.

    Returns:
        Object with repeat state (true/false).
    """
    return await reaper_call("GetSetRepeat", -1)


@mcp.tool()
async def zoom_to_selection() -> dict:
    """
    Zoom the arrange view to the time selection.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40031, 0)  # Zoom to time selection


@mcp.tool()
async def zoom_to_project() -> dict:
    """
    Zoom the arrange view to show the entire project.

    Returns:
        Object with success status.
    """
    return await reaper_call("Main_OnCommand", 40295, 0)  # Zoom to project


# --- MAIN ---

def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
