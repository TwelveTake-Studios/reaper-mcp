"""
REAPER Web Server - ReaScript HTTP API

This script runs inside REAPER and exposes an HTTP API for controlling REAPER.
Zero external dependencies - uses only Python stdlib and REAPER's RPR_* functions.

Usage:
1. Load this script in REAPER (Actions -> Show action list -> Load ReaScript)
2. Run the script
3. Server starts on localhost:9000
4. Use HTTP requests to control REAPER

Author: TwelveTake Studios LLC
License: MIT
Website: https://twelvetake.com
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import socket
import re
import math
from urllib.parse import urlparse, parse_qs

# Configuration
HOST = 'localhost'
PORT = 9000

# Global server instance
server = None


def db_to_linear(db):
    """Convert dB to linear volume (0-1 scale for REAPER)"""
    if db <= -150:
        return 0.0
    return 10 ** (db / 20)


def linear_to_db(linear):
    """Convert linear volume to dB"""
    if linear <= 0:
        return -150.0
    return 20 * math.log10(linear)


def get_track(track_index):
    """
    Get MediaTrack pointer - handles master track correctly.

    Args:
        track_index: Track index (0-based) or -1 for master track

    Returns:
        MediaTrack pointer or None if not found
    """
    if track_index == -1:
        return RPR_GetMasterTrack(0)

    track_count = RPR_CountTracks(0)
    if 0 <= track_index < track_count:
        return RPR_GetTrack(0, track_index)

    return None


def get_track_info(track):
    """Get comprehensive track information"""
    if track is None:
        return None

    # Get track name
    retval, track, name, buf_sz = RPR_GetTrackName(track, "", 256)

    # Get volume (linear) and convert to dB
    volume_linear = RPR_GetMediaTrackInfo_Value(track, "D_VOL")
    volume_db = linear_to_db(volume_linear)

    # Get pan (-1 to 1)
    pan = RPR_GetMediaTrackInfo_Value(track, "D_PAN")

    # Get mute state
    mute = bool(RPR_GetMediaTrackInfo_Value(track, "B_MUTE"))

    # Get solo state
    solo = bool(RPR_GetMediaTrackInfo_Value(track, "I_SOLO"))

    # Get track index
    track_idx = RPR_GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER")
    # Master track returns 0, regular tracks return 1-based index
    if track_idx == 0:
        track_idx = -1  # Master track
    else:
        track_idx = int(track_idx) - 1  # Convert to 0-based

    return {
        "index": track_idx,
        "name": name,
        "volume_db": round(volume_db, 2),
        "pan": round(pan, 2),
        "mute": mute,
        "solo": solo
    }


def get_fx_info(track, fx_index):
    """Get FX information"""
    if track is None:
        return None

    fx_count = RPR_TrackFX_GetCount(track)
    if fx_index < 0 or fx_index >= fx_count:
        return None

    # Get FX name
    retval, track, fx_index, buf, buf_sz = RPR_TrackFX_GetFXName(track, fx_index, "", 256)

    # Get enabled state
    enabled = bool(RPR_TrackFX_GetEnabled(track, fx_index))

    return {
        "index": fx_index,
        "name": buf,
        "enabled": enabled
    }


def get_fx_params(track, fx_index):
    """Get all FX parameters"""
    if track is None:
        return None

    fx_count = RPR_TrackFX_GetCount(track)
    if fx_index < 0 or fx_index >= fx_count:
        return None

    param_count = RPR_TrackFX_GetNumParams(track, fx_index)
    params = []

    for i in range(param_count):
        # Get param name
        retval, track, fx_index, param_idx, buf, buf_sz = RPR_TrackFX_GetParamName(
            track, fx_index, i, "", 256
        )

        # Get param value and range
        retval, track, fx_index, param_idx, minval, maxval = RPR_TrackFX_GetParam(
            track, fx_index, i, 0.0, 0.0
        )

        params.append({
            "index": i,
            "name": buf,
            "value": round(retval, 4),
            "min": round(minval, 4),
            "max": round(maxval, 4)
        })

    return params


def handle_function_call(func_name, args):
    """Handle function call from MCP server via /call endpoint."""

    # Track Operations
    if func_name == "CountTracks":
        return {"ok": True, "ret": RPR_CountTracks(0)}

    elif func_name == "GetTrackInfo":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": get_track_info(track)}

    elif func_name == "GetAllTracksInfo":
        count = RPR_CountTracks(0)
        tracks = []
        for i in range(count):
            track = RPR_GetTrack(0, i)
            tracks.append(get_track_info(track))
        return {"ok": True, "tracks": tracks}

    elif func_name == "InsertTrackAtIndex":
        RPR_InsertTrackAtIndex(args[0], args[1])
        return {"ok": True}

    elif func_name == "DeleteTrack":
        track = get_track(args[1] if len(args) > 1 else args[0])
        if track:
            RPR_DeleteTrack(track)
            return {"ok": True}
        return {"ok": False, "error": "Track not found"}

    elif func_name == "GetSetMediaTrackInfo_String":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        retval, track, value, buf_sz = RPR_GetSetMediaTrackInfo_String(track, args[1], args[2], args[3])
        return {"ok": True, "ret": retval, "value": value}

    elif func_name == "SetMediaTrackInfo_Value":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        ret = RPR_SetMediaTrackInfo_Value(track, args[1], args[2])
        return {"ok": True, "ret": ret}

    # FX Operations
    elif func_name == "TrackFX_GetCount":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": RPR_TrackFX_GetCount(track)}

    elif func_name == "TrackFX_AddByName":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        fx_idx = RPR_TrackFX_AddByName(track, args[1], args[2], args[3])
        return {"ok": True, "ret": fx_idx}

    elif func_name == "TrackFX_Delete":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        RPR_TrackFX_Delete(track, args[1])
        return {"ok": True}

    elif func_name == "TrackFX_GetFXName":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        retval, track, fx_idx, name, buf_sz = RPR_TrackFX_GetFXName(track, args[1], "", 256)
        return {"ok": True, "ret": retval, "name": name}

    elif func_name == "TrackFX_GetEnabled":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": RPR_TrackFX_GetEnabled(track, args[1])}

    elif func_name == "TrackFX_SetEnabled":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        RPR_TrackFX_SetEnabled(track, args[1], args[2])
        return {"ok": True}

    elif func_name == "TrackFX_GetNumParams":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": RPR_TrackFX_GetNumParams(track, args[1])}

    elif func_name == "TrackFX_GetParamName":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        retval, track, fx_idx, param_idx, name, buf_sz = RPR_TrackFX_GetParamName(track, args[1], args[2], "", 256)
        return {"ok": True, "ret": retval, "name": name}

    elif func_name == "TrackFX_GetParam":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        val, track, fx_idx, param_idx, minval, maxval = RPR_TrackFX_GetParam(track, args[1], args[2], 0.0, 0.0)
        return {"ok": True, "value": round(val, 4), "min": round(minval, 4), "max": round(maxval, 4)}

    elif func_name == "TrackFX_SetParam":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        ret = RPR_TrackFX_SetParam(track, args[1], args[2], args[3])
        return {"ok": True, "ret": ret}

    # Routing Operations
    elif func_name == "CreateTrackSend":
        src = get_track(args[0])
        dest = get_track(args[1])
        if not src:
            return {"ok": False, "error": "Source track not found"}
        if not dest:
            return {"ok": False, "error": "Destination track not found"}
        idx = RPR_CreateTrackSend(src, dest)
        return {"ok": True, "ret": idx}

    elif func_name == "RemoveTrackSend":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        RPR_RemoveTrackSend(track, args[1], args[2])
        return {"ok": True}

    elif func_name == "GetTrackNumSends":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        return {"ok": True, "ret": RPR_GetTrackNumSends(track, args[1])}

    elif func_name == "SetTrackSendInfo_Value":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        ret = RPR_SetTrackSendInfo_Value(track, args[1], args[2], args[3], args[4])
        return {"ok": True, "ret": ret}

    # Transport Operations
    elif func_name == "OnPlayButton":
        RPR_OnPlayButton()
        return {"ok": True}

    elif func_name == "OnStopButton":
        RPR_OnStopButton()
        return {"ok": True}

    elif func_name == "OnPauseButton":
        RPR_OnPauseButton()
        return {"ok": True}

    elif func_name == "GetPlayState":
        state = RPR_GetPlayState()
        return {"ok": True, "ret": state, "playing": bool(state & 1), "paused": bool(state & 2), "recording": bool(state & 4)}

    elif func_name == "GetCursorPosition":
        return {"ok": True, "ret": RPR_GetCursorPosition()}

    elif func_name == "SetEditCurPos":
        RPR_SetEditCurPos(args[0], args[1], args[2])
        return {"ok": True}

    elif func_name == "GetPlayPosition":
        return {"ok": True, "ret": RPR_GetPlayPosition()}

    elif func_name == "GetSetRepeat":
        return {"ok": True, "ret": RPR_GetSetRepeat(args[0])}

    # Project Operations
    elif func_name == "Main_SaveProject":
        RPR_Main_SaveProject(args[0], args[1])
        return {"ok": True}

    elif func_name == "GetProjectPath":
        retval, path, buf_sz = RPR_GetProjectPath("", 256)
        return {"ok": True, "ret": path}

    elif func_name == "GetProjectName":
        retval, proj, name, buf_sz = RPR_GetProjectName(0, "", 256)
        return {"ok": True, "ret": name}

    elif func_name == "Master_GetTempo":
        return {"ok": True, "ret": RPR_Master_GetTempo()}

    elif func_name == "SetCurrentBPM":
        RPR_SetCurrentBPM(args[0], args[1], args[2])
        return {"ok": True}

    elif func_name == "GetProjectLength":
        return {"ok": True, "ret": RPR_GetProjectLength(0)}

    elif func_name == "GetTimeSignature":
        retval, proj, bpm, bpi = RPR_GetProjectTimeSignature2(0, 0.0, 0.0)
        return {"ok": True, "bpm": bpm, "bpi": int(bpi)}

    # Markers and Regions
    elif func_name == "AddProjectMarker2":
        idx = RPR_AddProjectMarker2(args[0], args[1], args[2], args[3], args[4], args[5], args[6])
        return {"ok": True, "ret": idx}

    elif func_name == "DeleteProjectMarker":
        RPR_DeleteProjectMarker(args[0], args[1], args[2])
        return {"ok": True}

    elif func_name == "GetProjectMarkers":
        markers = []
        num_markers, num_regions = RPR_CountProjectMarkers(0)
        for i in range(num_markers + num_regions):
            retval, isrgn, pos, rgnend, name, markrgnindexnumber = RPR_EnumProjectMarkers(i)
            if not isrgn:
                markers.append({"index": markrgnindexnumber, "position": pos, "name": name})
        return {"ok": True, "markers": markers}

    elif func_name == "GetProjectRegions":
        regions = []
        num_markers, num_regions = RPR_CountProjectMarkers(0)
        for i in range(num_markers + num_regions):
            retval, isrgn, pos, rgnend, name, markrgnindexnumber = RPR_EnumProjectMarkers(i)
            if isrgn:
                regions.append({"index": markrgnindexnumber, "start": pos, "end": rgnend, "name": name})
        return {"ok": True, "regions": regions}

    elif func_name == "GoToMarker":
        RPR_GoToMarker(args[0], args[1], args[2])
        return {"ok": True}

    elif func_name == "GoToRegion":
        RPR_GoToRegion(args[0], args[1], args[2])
        return {"ok": True}

    # Selection Operations
    elif func_name == "Main_OnCommand":
        RPR_Main_OnCommand(args[0], args[1])
        return {"ok": True}

    elif func_name == "SetTrackSelected":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        RPR_SetTrackSelected(track, args[1])
        return {"ok": True}

    elif func_name == "GetSelectedTracks":
        selected = []
        count = RPR_CountTracks(0)
        for i in range(count):
            track = RPR_GetTrack(0, i)
            if RPR_IsTrackSelected(track):
                selected.append(i)
        return {"ok": True, "tracks": selected}

    elif func_name == "GetSelectedItems":
        items = []
        count = RPR_CountSelectedMediaItems(0)
        for i in range(count):
            item = RPR_GetSelectedMediaItem(0, i)
            track = RPR_GetMediaItem_Track(item)
            track_idx = int(RPR_GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER")) - 1
            pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
            length = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
            items.append({"track": track_idx, "position": pos, "length": length})
        return {"ok": True, "items": items}

    # Undo Operations
    elif func_name == "Undo_DoUndo2":
        ret = RPR_Undo_DoUndo2(args[0])
        return {"ok": True, "ret": ret}

    elif func_name == "Undo_DoRedo2":
        ret = RPR_Undo_DoRedo2(args[0])
        return {"ok": True, "ret": ret}

    elif func_name == "GetUndoState":
        can_undo = RPR_Undo_CanUndo2(0) or ""
        can_redo = RPR_Undo_CanRedo2(0) or ""
        return {"ok": True, "can_undo": can_undo, "can_redo": can_redo}

    # Media Items
    elif func_name == "GetTrackItems":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        items = []
        count = RPR_CountTrackMediaItems(track)
        for i in range(count):
            item = RPR_GetTrackMediaItem(track, i)
            pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
            length = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
            mute = bool(RPR_GetMediaItemInfo_Value(item, "B_MUTE"))
            items.append({"index": i, "position": pos, "length": length, "mute": mute})
        return {"ok": True, "items": items}

    elif func_name == "SetMediaItemInfo_Value":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        item = RPR_GetTrackMediaItem(track, args[1])
        if not item:
            return {"ok": False, "error": "Item not found"}
        RPR_SetMediaItemInfo_Value(item, args[2], args[3])
        return {"ok": True}

    elif func_name == "CreateNewMIDIItemInProj":
        track = get_track(args[0])
        if not track:
            return {"ok": False, "error": "Track not found"}
        item = RPR_CreateNewMIDIItemInProj(track, args[1], args[2], args[3] if len(args) > 3 else False)
        return {"ok": True, "ret": item is not None}

    # Time Selection
    elif func_name == "GetSet_LoopTimeRange":
        start_time, end_time = RPR_GetSet_LoopTimeRange(args[0], args[1], 0, 0, args[4] if len(args) > 4 else False)
        return {"ok": True, "start_time": start_time, "end_time": end_time}

    # Unknown function
    else:
        return {"ok": False, "error": f"Unknown function: {func_name}"}


class ReaperRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for REAPER API"""

    # Disable logging to console (too noisy)
    def log_message(self, format, *args):
        pass

    def send_json_response(self, data, status=200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_error_response(self, message, status=400, **extra):
        """Send error response"""
        data = {"error": message, **extra}
        self.send_json_response(data, status)

    def parse_path(self):
        """Parse URL path and return components"""
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def read_json_body(self):
        """Read and parse JSON request body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        return json.loads(body.decode('utf-8'))

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests"""
        path, query = self.parse_path()

        # Health check
        if path == '/ping':
            self.send_json_response({"status": "ok", "reaper": "connected"})
            return

        # Track count
        if path == '/tracks/count':
            count = RPR_CountTracks(0)
            self.send_json_response({"count": count})
            return

        # Master track info
        if path == '/master':
            track = get_track(-1)
            info = get_track_info(track)
            if info:
                self.send_json_response(info)
            else:
                self.send_error_response("Master track not found", 404)
            return

        # Track info: /tracks/{index}
        match = re.match(r'^/tracks/(-?\d+)$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(
                    f"Track {track_index} not found",
                    404,
                    track_count=RPR_CountTracks(0),
                    hint="Use -1 for master track, 0 to track_count-1 for regular tracks"
                )
                return
            info = get_track_info(track)
            self.send_json_response(info)
            return

        # FX list: /tracks/{index}/fx
        match = re.match(r'^/tracks/(-?\d+)/fx$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            fx_count = RPR_TrackFX_GetCount(track)
            fx_list = []
            for i in range(fx_count):
                fx_info = get_fx_info(track, i)
                if fx_info:
                    fx_list.append(fx_info)

            self.send_json_response({"track_index": track_index, "fx": fx_list})
            return

        # FX count: /tracks/{index}/fx/count
        match = re.match(r'^/tracks/(-?\d+)/fx/count$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            count = RPR_TrackFX_GetCount(track)
            self.send_json_response({"track_index": track_index, "count": count})
            return

        # FX info: /tracks/{index}/fx/{fx_index}
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            fx_info = get_fx_info(track, fx_index)
            if fx_info is None:
                self.send_error_response(
                    f"FX {fx_index} not found on track {track_index}",
                    404,
                    fx_count=RPR_TrackFX_GetCount(track)
                )
                return

            self.send_json_response(fx_info)
            return

        # FX params: /tracks/{index}/fx/{fx_index}/params
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)/params$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            params = get_fx_params(track, fx_index)
            if params is None:
                self.send_error_response(f"FX {fx_index} not found", 404)
                return

            self.send_json_response({
                "track_index": track_index,
                "fx_index": fx_index,
                "params": params
            })
            return

        # Single FX param: /tracks/{index}/fx/{fx_index}/params/{param_index}
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)/params/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            param_index = int(match.group(3))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            # Get param info
            retval, track, fx_idx, param_idx, buf, buf_sz = RPR_TrackFX_GetParamName(
                track, fx_index, param_index, "", 256
            )
            retval2, track, fx_idx, param_idx, minval, maxval = RPR_TrackFX_GetParam(
                track, fx_index, param_index, 0.0, 0.0
            )

            self.send_json_response({
                "track_index": track_index,
                "fx_index": fx_index,
                "param_index": param_index,
                "name": buf,
                "value": round(retval2, 4),
                "min": round(minval, 4),
                "max": round(maxval, 4)
            })
            return

        # Transport state
        if path == '/transport':
            play_state = RPR_GetPlayState()
            cursor_pos = RPR_GetCursorPosition()
            self.send_json_response({
                "playing": bool(play_state & 1),
                "paused": bool(play_state & 2),
                "recording": bool(play_state & 4),
                "cursor_position": round(cursor_pos, 3)
            })
            return

        # Project info
        if path == '/project':
            retval, buf, buf_sz = RPR_GetProjectPath("", 256)
            retval2, proj, buf2, buf_sz2 = RPR_GetProjectName(0, "", 256)
            tempo = RPR_Master_GetTempo()
            retval3, proj, bpm, bpi = RPR_GetProjectTimeSignature2(0, 0.0, 0.0)

            self.send_json_response({
                "path": buf,
                "name": buf2,
                "tempo": round(tempo, 2),
                "time_signature": {
                    "beats_per_measure": int(bpi),
                    "note_value": 4  # Assuming quarter note
                }
            })
            return

        # Sends info: /tracks/{index}/sends
        match = re.match(r'^/tracks/(-?\d+)/sends$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            num_sends = RPR_GetTrackNumSends(track, 0)  # 0 = sends
            sends = []
            for i in range(num_sends):
                dest_track = RPR_GetTrackSendInfo_Value(track, 0, i, "P_DESTTRACK")
                vol = RPR_GetTrackSendInfo_Value(track, 0, i, "D_VOL")
                mute = RPR_GetTrackSendInfo_Value(track, 0, i, "B_MUTE")
                sends.append({
                    "index": i,
                    "volume_db": round(linear_to_db(vol), 2),
                    "mute": bool(mute)
                })

            self.send_json_response({"track_index": track_index, "sends": sends})
            return

        self.send_error_response(f"Unknown endpoint: {path}", 404)

    def do_POST(self):
        """Handle POST requests"""
        path, query = self.parse_path()

        # Function call endpoint (for MCP server)
        if path == '/call':
            body = self.read_json_body()
            func_name = body.get('func')
            args = body.get('args', [])
            if not func_name:
                self.send_error_response("Missing 'func' in request body")
                return
            result = handle_function_call(func_name, args)
            self.send_json_response(result)
            return

        # Insert track: POST /tracks
        if path == '/tracks':
            body = self.read_json_body()
            index = body.get('index', RPR_CountTracks(0))  # Default to end
            RPR_InsertTrackAtIndex(index, True)

            # Optionally set name
            if 'name' in body:
                track = RPR_GetTrack(0, index)
                if track:
                    RPR_GetSetMediaTrackInfo_String(track, "P_NAME", body['name'], True)

            track = RPR_GetTrack(0, index)
            info = get_track_info(track)
            self.send_json_response(info, 201)
            return

        # Add FX: POST /tracks/{index}/fx
        match = re.match(r'^/tracks/(-?\d+)/fx$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            body = self.read_json_body()
            fx_name = body.get('name')
            if not fx_name:
                self.send_error_response("Missing 'name' in request body")
                return

            # Add FX (-1 = add to end)
            fx_index = RPR_TrackFX_AddByName(track, fx_name, False, -1)

            if fx_index < 0:
                self.send_error_response(
                    f"Failed to add FX '{fx_name}'. Plugin may not be installed.",
                    400
                )
                return

            fx_info = get_fx_info(track, fx_index)
            self.send_json_response(fx_info, 201)
            return

        # Transport play: POST /transport/play
        if path == '/transport/play':
            RPR_OnPlayButton()
            self.send_json_response({"status": "playing"})
            return

        # Transport stop: POST /transport/stop
        if path == '/transport/stop':
            RPR_OnStopButton()
            self.send_json_response({"status": "stopped"})
            return

        # Create send: POST /sends
        if path == '/sends':
            body = self.read_json_body()
            src_index = body.get('src_track')
            dest_index = body.get('dest_track')

            if src_index is None or dest_index is None:
                self.send_error_response("Missing 'src_track' or 'dest_track'")
                return

            src_track = get_track(src_index)
            dest_track = get_track(dest_index)

            if src_track is None:
                self.send_error_response(f"Source track {src_index} not found", 404)
                return
            if dest_track is None:
                self.send_error_response(f"Destination track {dest_index} not found", 404)
                return

            send_index = RPR_CreateTrackSend(src_track, dest_track)
            self.send_json_response({
                "src_track": src_index,
                "dest_track": dest_index,
                "send_index": send_index
            }, 201)
            return

        # Save project: POST /project/save
        if path == '/project/save':
            RPR_Main_SaveProject(0, False)
            self.send_json_response({"status": "saved"})
            return

        self.send_error_response(f"Unknown endpoint: {path}", 404)

    def do_PUT(self):
        """Handle PUT requests"""
        path, query = self.parse_path()

        # Update track: PUT /tracks/{index}
        match = re.match(r'^/tracks/(-?\d+)$', path)
        if match:
            track_index = int(match.group(1))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            body = self.read_json_body()

            if 'name' in body:
                RPR_GetSetMediaTrackInfo_String(track, "P_NAME", body['name'], True)

            if 'volume_db' in body:
                vol_linear = db_to_linear(body['volume_db'])
                RPR_SetMediaTrackInfo_Value(track, "D_VOL", vol_linear)

            if 'pan' in body:
                pan = max(-1.0, min(1.0, body['pan']))
                RPR_SetMediaTrackInfo_Value(track, "D_PAN", pan)

            if 'mute' in body:
                RPR_SetMediaTrackInfo_Value(track, "B_MUTE", 1 if body['mute'] else 0)

            if 'solo' in body:
                RPR_SetMediaTrackInfo_Value(track, "I_SOLO", 1 if body['solo'] else 0)

            info = get_track_info(track)
            self.send_json_response(info)
            return

        # Update FX: PUT /tracks/{index}/fx/{fx_index}
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            body = self.read_json_body()

            if 'enabled' in body:
                RPR_TrackFX_SetEnabled(track, fx_index, body['enabled'])

            fx_info = get_fx_info(track, fx_index)
            if fx_info is None:
                self.send_error_response(f"FX {fx_index} not found", 404)
                return

            self.send_json_response(fx_info)
            return

        # Set FX param: PUT /tracks/{index}/fx/{fx_index}/params/{param_index}
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)/params/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            param_index = int(match.group(3))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            body = self.read_json_body()
            value = body.get('value')
            if value is None:
                self.send_error_response("Missing 'value' in request body")
                return

            success = RPR_TrackFX_SetParam(track, fx_index, param_index, value)

            # Get updated param info
            retval, track, fx_idx, param_idx, buf, buf_sz = RPR_TrackFX_GetParamName(
                track, fx_index, param_index, "", 256
            )
            retval2, track, fx_idx, param_idx, minval, maxval = RPR_TrackFX_GetParam(
                track, fx_index, param_index, 0.0, 0.0
            )

            self.send_json_response({
                "track_index": track_index,
                "fx_index": fx_index,
                "param_index": param_index,
                "name": buf,
                "value": round(retval2, 4),
                "min": round(minval, 4),
                "max": round(maxval, 4)
            })
            return

        # Set cursor position: PUT /transport/cursor
        if path == '/transport/cursor':
            body = self.read_json_body()
            position = body.get('position', 0)
            RPR_SetEditCurPos(position, True, False)
            self.send_json_response({"cursor_position": position})
            return

        # Update send: PUT /tracks/{index}/sends/{send_index}
        match = re.match(r'^/tracks/(-?\d+)/sends/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            send_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            body = self.read_json_body()

            if 'volume_db' in body:
                vol_linear = db_to_linear(body['volume_db'])
                RPR_SetTrackSendInfo_Value(track, 0, send_index, "D_VOL", vol_linear)

            if 'mute' in body:
                RPR_SetTrackSendInfo_Value(track, 0, send_index, "B_MUTE", 1 if body['mute'] else 0)

            # Get updated send info
            vol = RPR_GetTrackSendInfo_Value(track, 0, send_index, "D_VOL")
            mute = RPR_GetTrackSendInfo_Value(track, 0, send_index, "B_MUTE")

            self.send_json_response({
                "track_index": track_index,
                "send_index": send_index,
                "volume_db": round(linear_to_db(vol), 2),
                "mute": bool(mute)
            })
            return

        self.send_error_response(f"Unknown endpoint: {path}", 404)

    def do_DELETE(self):
        """Handle DELETE requests"""
        path, query = self.parse_path()

        # Delete track: DELETE /tracks/{index}
        match = re.match(r'^/tracks/(-?\d+)$', path)
        if match:
            track_index = int(match.group(1))
            if track_index == -1:
                self.send_error_response("Cannot delete master track", 400)
                return

            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            RPR_DeleteTrack(track)
            self.send_json_response({"deleted": track_index})
            return

        # Delete FX: DELETE /tracks/{index}/fx/{fx_index}
        match = re.match(r'^/tracks/(-?\d+)/fx/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            fx_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            fx_count = RPR_TrackFX_GetCount(track)
            if fx_index < 0 or fx_index >= fx_count:
                self.send_error_response(f"FX {fx_index} not found", 404)
                return

            RPR_TrackFX_Delete(track, fx_index)
            self.send_json_response({
                "track_index": track_index,
                "deleted_fx_index": fx_index
            })
            return

        # Delete send: DELETE /tracks/{index}/sends/{send_index}
        match = re.match(r'^/tracks/(-?\d+)/sends/(\d+)$', path)
        if match:
            track_index = int(match.group(1))
            send_index = int(match.group(2))
            track = get_track(track_index)
            if track is None:
                self.send_error_response(f"Track {track_index} not found", 404)
                return

            # 0 = sends category
            RPR_RemoveTrackSend(track, 0, send_index)
            self.send_json_response({
                "track_index": track_index,
                "deleted_send_index": send_index
            })
            return

        self.send_error_response(f"Unknown endpoint: {path}", 404)


def process_requests():
    """Process pending HTTP requests - called via RPR_defer()"""
    global server

    if server is None:
        return

    try:
        # Handle up to 5 requests per cycle to improve responsiveness
        for _ in range(5):
            server._handle_request_noblock()
    except socket.error:
        pass  # No pending requests
    except Exception as e:
        RPR_ShowConsoleMsg(f"Server error: {str(e)}\n")

    # Schedule next check
    RPR_defer("process_requests()")


def start_server():
    """Start the HTTP server"""
    global server

    try:
        server = HTTPServer((HOST, PORT), ReaperRequestHandler)
        server.socket.setblocking(False)

        RPR_ShowConsoleMsg(f"REAPER Web Server started on http://{HOST}:{PORT}\n")
        RPR_ShowConsoleMsg("Endpoints:\n")
        RPR_ShowConsoleMsg("  GET  /ping - Health check\n")
        RPR_ShowConsoleMsg("  GET  /tracks/count - Track count\n")
        RPR_ShowConsoleMsg("  GET  /tracks/{index} - Track info\n")
        RPR_ShowConsoleMsg("  POST /tracks/{index}/fx - Add FX\n")
        RPR_ShowConsoleMsg("  GET  /tracks/{index}/fx - List FX\n")
        RPR_ShowConsoleMsg("  ... and more\n")
        RPR_ShowConsoleMsg("\nUse track_index=-1 for master track\n")

        # Start processing loop
        RPR_defer("process_requests()")

    except Exception as e:
        RPR_ShowConsoleMsg(f"Failed to start server: {str(e)}\n")
        RPR_ShowConsoleMsg(f"Port {PORT} may be in use. Try restarting REAPER.\n")


# Start the server when script runs
start_server()
