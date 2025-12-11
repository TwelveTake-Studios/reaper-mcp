-- REAPER Web Server - ReaScript HTTP API (Lua version)
--
-- This script runs inside REAPER and exposes an HTTP API for controlling REAPER.
-- Works with REAPER's built-in Lua support - no additional configuration needed.
--
-- Usage:
-- 1. Load this script in REAPER (Actions -> Show action list -> Load ReaScript)
-- 2. Run the script
-- 3. Server starts on localhost:9000
--
-- Author: TwelveTake Studios LLC
-- License: MIT
-- Website: https://twelvetake.com

local HOST = "127.0.0.1"
local PORT = 9000

local socket = nil
local client = nil
local server_running = false

-- Try to load LuaSocket
local status, socket_lib = pcall(require, "socket")
if not status then
  reaper.ShowConsoleMsg("ERROR: LuaSocket not found.\n")
  reaper.ShowConsoleMsg("\nTo install LuaSocket:\n")
  reaper.ShowConsoleMsg("1. Download from: https://lunarmodules.github.io/luasocket/\n")
  reaper.ShowConsoleMsg("2. Or use ReaPack to install 'sockmonkey' which includes LuaSocket\n")
  reaper.ShowConsoleMsg("\nAlternatively, install Python support in REAPER and use reaper_web_server.py\n")
  return
end

socket = socket_lib

-- ============================================================================
-- Utility Functions
-- ============================================================================

local function db_to_linear(db)
  if db <= -150 then return 0 end
  return 10 ^ (db / 20)
end

local function linear_to_db(linear)
  if linear <= 0 then return -150 end
  return 20 * math.log10(linear)
end

local function round(num, decimals)
  local mult = 10 ^ (decimals or 0)
  return math.floor(num * mult + 0.5) / mult
end

local function json_encode(obj)
  -- Simple JSON encoder for our use case
  if obj == nil then
    return "null"
  elseif type(obj) == "boolean" then
    return obj and "true" or "false"
  elseif type(obj) == "number" then
    if obj ~= obj then return "null" end -- NaN
    if obj == math.huge or obj == -math.huge then return "null" end
    return tostring(obj)
  elseif type(obj) == "string" then
    -- Escape special characters
    local escaped = obj:gsub('\\', '\\\\')
                       :gsub('"', '\\"')
                       :gsub('\n', '\\n')
                       :gsub('\r', '\\r')
                       :gsub('\t', '\\t')
    return '"' .. escaped .. '"'
  elseif type(obj) == "table" then
    -- Check if array or object
    local is_array = true
    local max_index = 0
    for k, v in pairs(obj) do
      if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then
        is_array = false
        break
      end
      if k > max_index then max_index = k end
    end
    if is_array and max_index > 0 then
      -- Array
      local parts = {}
      for i = 1, max_index do
        parts[i] = json_encode(obj[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      -- Object
      local parts = {}
      for k, v in pairs(obj) do
        table.insert(parts, json_encode(tostring(k)) .. ":" .. json_encode(v))
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
  return "null"
end

local function json_decode(str)
  -- Simple JSON decoder
  if str == nil or str == "" then return nil end

  -- Use Lua's load for simple cases (security note: only use with trusted input)
  str = str:gsub('"([^"]-)":', '["%1"]=')
           :gsub('null', 'nil')
           :gsub('true', 'true')
           :gsub('false', 'false')

  local func = load("return " .. str)
  if func then
    local ok, result = pcall(func)
    if ok then return result end
  end
  return nil
end

local function parse_request(request_text)
  local lines = {}
  for line in request_text:gmatch("[^\r\n]+") do
    table.insert(lines, line)
  end

  if #lines == 0 then return nil end

  -- Parse request line
  local method, path = lines[1]:match("^(%w+)%s+([^%s]+)")
  if not method then return nil end

  -- Parse headers
  local headers = {}
  local body_start = nil
  for i = 2, #lines do
    if lines[i] == "" then
      body_start = i + 1
      break
    end
    local key, value = lines[i]:match("^([^:]+):%s*(.+)$")
    if key then
      headers[key:lower()] = value
    end
  end

  -- Get body
  local body = ""
  if body_start then
    for i = body_start, #lines do
      body = body .. lines[i]
    end
  end

  return {
    method = method,
    path = path,
    headers = headers,
    body = body
  }
end

local function send_response(client_socket, status_code, status_text, body)
  local response = string.format(
    "HTTP/1.1 %d %s\r\n" ..
    "Content-Type: application/json\r\n" ..
    "Access-Control-Allow-Origin: *\r\n" ..
    "Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r\n" ..
    "Access-Control-Allow-Headers: Content-Type\r\n" ..
    "Content-Length: %d\r\n" ..
    "Connection: close\r\n" ..
    "\r\n%s",
    status_code, status_text, #body, body
  )
  client_socket:send(response)
end

local function send_json(client_socket, data, status_code)
  status_code = status_code or 200
  local status_text = status_code == 200 and "OK" or
                      status_code == 201 and "Created" or
                      status_code == 400 and "Bad Request" or
                      status_code == 404 and "Not Found" or "Error"
  send_response(client_socket, status_code, status_text, json_encode(data))
end

local function send_error(client_socket, message, status_code, extra)
  status_code = status_code or 400
  local data = {error = message}
  if extra then
    for k, v in pairs(extra) do
      data[k] = v
    end
  end
  send_json(client_socket, data, status_code)
end

-- ============================================================================
-- Track Functions
-- ============================================================================

local function get_track(track_index)
  if track_index == -1 then
    return reaper.GetMasterTrack(0)
  end
  local track_count = reaper.CountTracks(0)
  if track_index >= 0 and track_index < track_count then
    return reaper.GetTrack(0, track_index)
  end
  return nil
end

local function get_track_info(track)
  if not track then return nil end

  local _, name = reaper.GetTrackName(track)
  local volume = reaper.GetMediaTrackInfo_Value(track, "D_VOL")
  local pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN")
  local mute = reaper.GetMediaTrackInfo_Value(track, "B_MUTE")
  local solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO")
  local track_num = reaper.GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER")

  local track_index
  if track_num == 0 then
    track_index = -1  -- Master track
  else
    track_index = math.floor(track_num) - 1  -- Convert to 0-based
  end

  return {
    index = track_index,
    name = name,
    volume_db = round(linear_to_db(volume), 2),
    pan = round(pan, 2),
    mute = mute == 1,
    solo = solo > 0
  }
end

local function get_fx_info(track, fx_index)
  if not track then return nil end

  local fx_count = reaper.TrackFX_GetCount(track)
  if fx_index < 0 or fx_index >= fx_count then return nil end

  local _, fx_name = reaper.TrackFX_GetFXName(track, fx_index, "")
  local enabled = reaper.TrackFX_GetEnabled(track, fx_index)

  return {
    index = fx_index,
    name = fx_name,
    enabled = enabled
  }
end

local function get_fx_params(track, fx_index)
  if not track then return nil end

  local fx_count = reaper.TrackFX_GetCount(track)
  if fx_index < 0 or fx_index >= fx_count then return nil end

  local param_count = reaper.TrackFX_GetNumParams(track, fx_index)
  local params = {}

  for i = 0, param_count - 1 do
    local _, param_name = reaper.TrackFX_GetParamName(track, fx_index, i, "")
    local value, minval, maxval = reaper.TrackFX_GetParam(track, fx_index, i)

    table.insert(params, {
      index = i,
      name = param_name,
      value = round(value, 4),
      min = round(minval, 4),
      max = round(maxval, 4)
    })
  end

  return params
end

-- ============================================================================
-- Request Handlers
-- ============================================================================

local function handle_get(path, client_socket)
  -- Health check
  if path == "/ping" then
    send_json(client_socket, {status = "ok", reaper = "connected"})
    return
  end

  -- Track count
  if path == "/tracks/count" then
    send_json(client_socket, {count = reaper.CountTracks(0)})
    return
  end

  -- Master track
  if path == "/master" then
    local track = get_track(-1)
    local info = get_track_info(track)
    if info then
      send_json(client_socket, info)
    else
      send_error(client_socket, "Master track not found", 404)
    end
    return
  end

  -- Track info: /tracks/{index}
  local track_index = path:match("^/tracks/(%-?%d+)$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404, {
        track_count = reaper.CountTracks(0),
        hint = "Use -1 for master track, 0 to track_count-1 for regular tracks"
      })
      return
    end
    send_json(client_socket, get_track_info(track))
    return
  end

  -- FX list: /tracks/{index}/fx
  local track_index = path:match("^/tracks/(%-?%d+)/fx$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local fx_count = reaper.TrackFX_GetCount(track)
    local fx_list = {}
    for i = 0, fx_count - 1 do
      table.insert(fx_list, get_fx_info(track, i))
    end

    send_json(client_socket, {track_index = track_index, fx = fx_list})
    return
  end

  -- FX count: /tracks/{index}/fx/count
  local track_index = path:match("^/tracks/(%-?%d+)/fx/count$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    send_json(client_socket, {track_index = track_index, count = reaper.TrackFX_GetCount(track)})
    return
  end

  -- FX info: /tracks/{index}/fx/{fx_index}
  local track_index, fx_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)$")
  if track_index and fx_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local fx_info = get_fx_info(track, fx_index)
    if not fx_info then
      send_error(client_socket, "FX " .. fx_index .. " not found", 404, {
        fx_count = reaper.TrackFX_GetCount(track)
      })
      return
    end

    send_json(client_socket, fx_info)
    return
  end

  -- FX params: /tracks/{index}/fx/{fx_index}/params
  local track_index, fx_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)/params$")
  if track_index and fx_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local params = get_fx_params(track, fx_index)
    if not params then
      send_error(client_socket, "FX " .. fx_index .. " not found", 404)
      return
    end

    send_json(client_socket, {track_index = track_index, fx_index = fx_index, params = params})
    return
  end

  -- Single FX param: /tracks/{index}/fx/{fx_index}/params/{param_index}
  local track_index, fx_index, param_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)/params/(%d+)$")
  if track_index and fx_index and param_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    param_index = tonumber(param_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local _, param_name = reaper.TrackFX_GetParamName(track, fx_index, param_index, "")
    local value, minval, maxval = reaper.TrackFX_GetParam(track, fx_index, param_index)

    send_json(client_socket, {
      track_index = track_index,
      fx_index = fx_index,
      param_index = param_index,
      name = param_name,
      value = round(value, 4),
      min = round(minval, 4),
      max = round(maxval, 4)
    })
    return
  end

  -- Transport
  if path == "/transport" then
    local play_state = reaper.GetPlayState()
    local cursor_pos = reaper.GetCursorPosition()
    send_json(client_socket, {
      playing = (play_state & 1) == 1,
      paused = (play_state & 2) == 2,
      recording = (play_state & 4) == 4,
      cursor_position = round(cursor_pos, 3)
    })
    return
  end

  -- Project
  if path == "/project" then
    local project_path = reaper.GetProjectPath("")
    local _, project_name = reaper.GetProjectName(0, "")
    local tempo = reaper.Master_GetTempo()
    local _, bpm, bpi = reaper.GetProjectTimeSignature2(0)

    send_json(client_socket, {
      path = project_path,
      name = project_name,
      tempo = round(tempo, 2),
      time_signature = {
        beats_per_measure = math.floor(bpi),
        note_value = 4
      }
    })
    return
  end

  -- Sends: /tracks/{index}/sends
  local track_index = path:match("^/tracks/(%-?%d+)/sends$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local num_sends = reaper.GetTrackNumSends(track, 0)
    local sends = {}
    for i = 0, num_sends - 1 do
      local vol = reaper.GetTrackSendInfo_Value(track, 0, i, "D_VOL")
      local mute = reaper.GetTrackSendInfo_Value(track, 0, i, "B_MUTE")
      table.insert(sends, {
        index = i,
        volume_db = round(linear_to_db(vol), 2),
        mute = mute == 1
      })
    end

    send_json(client_socket, {track_index = track_index, sends = sends})
    return
  end

  send_error(client_socket, "Unknown endpoint: " .. path, 404)
end

-- ============================================================================
-- Function Call Handler (for MCP server)
-- ============================================================================

local function handle_function_call(func_name, args)
  -- Get track helper with proper indexing
  local function get_track_by_index(idx)
    if idx == -1 then
      return reaper.GetMasterTrack(0)
    end
    local count = reaper.CountTracks(0)
    if idx >= 0 and idx < count then
      return reaper.GetTrack(0, idx)
    end
    return nil
  end

  -- Track Operations
  if func_name == "CountTracks" then
    return {ok = true, ret = reaper.CountTracks(0)}

  elseif func_name == "GetTrackInfo" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    return {ok = true, ret = get_track_info(track)}

  elseif func_name == "GetAllTracksInfo" then
    local count = reaper.CountTracks(0)
    local tracks = {}
    for i = 0, count - 1 do
      local track = reaper.GetTrack(0, i)
      table.insert(tracks, get_track_info(track))
    end
    return {ok = true, tracks = tracks}

  elseif func_name == "InsertTrackAtIndex" then
    reaper.InsertTrackAtIndex(args[1], args[2])
    return {ok = true}

  elseif func_name == "DeleteTrack" then
    local track = get_track_by_index(args[2])
    if track then
      reaper.DeleteTrack(track)
      return {ok = true}
    end
    return {ok = false, error = "Track not found"}

  elseif func_name == "GetSetMediaTrackInfo_String" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local retval, str = reaper.GetSetMediaTrackInfo_String(track, args[2], args[3], args[4])
    return {ok = true, ret = retval, value = str}

  elseif func_name == "SetMediaTrackInfo_Value" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local ret = reaper.SetMediaTrackInfo_Value(track, args[2], args[3])
    return {ok = true, ret = ret}

  -- FX Operations
  elseif func_name == "TrackFX_GetCount" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    return {ok = true, ret = reaper.TrackFX_GetCount(track)}

  elseif func_name == "TrackFX_AddByName" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local fx_idx = reaper.TrackFX_AddByName(track, args[2], args[3], args[4])
    return {ok = true, ret = fx_idx}

  elseif func_name == "TrackFX_Delete" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    reaper.TrackFX_Delete(track, args[2])
    return {ok = true}

  elseif func_name == "TrackFX_GetFXName" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local retval, name = reaper.TrackFX_GetFXName(track, args[2], "")
    return {ok = true, ret = retval, name = name}

  elseif func_name == "TrackFX_GetEnabled" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    return {ok = true, ret = reaper.TrackFX_GetEnabled(track, args[2])}

  elseif func_name == "TrackFX_SetEnabled" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    reaper.TrackFX_SetEnabled(track, args[2], args[3])
    return {ok = true}

  elseif func_name == "TrackFX_GetNumParams" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    return {ok = true, ret = reaper.TrackFX_GetNumParams(track, args[2])}

  elseif func_name == "TrackFX_GetParamName" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local retval, name = reaper.TrackFX_GetParamName(track, args[2], args[3], "")
    return {ok = true, ret = retval, name = name}

  elseif func_name == "TrackFX_GetParam" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local val, minval, maxval = reaper.TrackFX_GetParam(track, args[2], args[3])
    return {ok = true, value = round(val, 4), min = round(minval, 4), max = round(maxval, 4)}

  elseif func_name == "TrackFX_SetParam" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local ret = reaper.TrackFX_SetParam(track, args[2], args[3], args[4])
    return {ok = true, ret = ret}

  -- Routing Operations
  elseif func_name == "CreateTrackSend" then
    local src = get_track_by_index(args[1])
    local dest = get_track_by_index(args[2])
    if not src then return {ok = false, error = "Source track not found"} end
    if not dest then return {ok = false, error = "Destination track not found"} end
    local idx = reaper.CreateTrackSend(src, dest)
    return {ok = true, ret = idx}

  elseif func_name == "RemoveTrackSend" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    reaper.RemoveTrackSend(track, args[2], args[3])
    return {ok = true}

  elseif func_name == "GetTrackNumSends" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    return {ok = true, ret = reaper.GetTrackNumSends(track, args[2])}

  elseif func_name == "SetTrackSendInfo_Value" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local ret = reaper.SetTrackSendInfo_Value(track, args[2], args[3], args[4], args[5])
    return {ok = true, ret = ret}

  elseif func_name == "SetTrackSendUIVol" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local ret = reaper.SetTrackSendUIVol(track, args[2], args[3], args[4])
    return {ok = true, ret = ret}

  -- Transport Operations
  elseif func_name == "OnPlayButton" then
    reaper.OnPlayButton()
    return {ok = true}

  elseif func_name == "OnStopButton" then
    reaper.OnStopButton()
    return {ok = true}

  elseif func_name == "OnPauseButton" then
    reaper.OnPauseButton()
    return {ok = true}

  elseif func_name == "OnRecordButton" then
    reaper.OnRecordButton()
    return {ok = true}

  elseif func_name == "GetPlayState" then
    local state = reaper.GetPlayState()
    return {ok = true, ret = state, playing = (state & 1) == 1, paused = (state & 2) == 2, recording = (state & 4) == 4}

  elseif func_name == "GetCursorPosition" then
    return {ok = true, ret = reaper.GetCursorPosition()}

  elseif func_name == "SetEditCurPos" then
    reaper.SetEditCurPos(args[1], args[2], args[3])
    return {ok = true}

  elseif func_name == "GetPlayPosition" then
    return {ok = true, ret = reaper.GetPlayPosition()}

  elseif func_name == "GetSetRepeat" then
    return {ok = true, ret = reaper.GetSetRepeat(args[1])}

  -- Project Operations
  elseif func_name == "Main_SaveProject" then
    reaper.Main_SaveProject(args[1], args[2])
    return {ok = true}

  elseif func_name == "GetProjectPath" then
    local retval, path = reaper.GetProjectPath("")
    return {ok = true, ret = path}

  elseif func_name == "GetProjectName" then
    local retval, name = reaper.GetProjectName(0, "")
    return {ok = true, ret = name}

  elseif func_name == "Master_GetTempo" then
    return {ok = true, ret = reaper.Master_GetTempo()}

  elseif func_name == "SetCurrentBPM" then
    reaper.SetCurrentBPM(args[1], args[2], args[3])
    return {ok = true}

  elseif func_name == "GetTimeSignature" then
    local bpm, bpi = reaper.GetProjectTimeSignature2(0)
    return {ok = true, bpm = bpm, bpi = bpi}

  elseif func_name == "GetProjectLength" then
    return {ok = true, ret = reaper.GetProjectLength(0)}

  -- Markers and Regions
  elseif func_name == "AddProjectMarker2" then
    local idx = reaper.AddProjectMarker2(args[1], args[2], args[3], args[4], args[5], args[6], args[7])
    return {ok = true, ret = idx}

  elseif func_name == "DeleteProjectMarker" then
    reaper.DeleteProjectMarker(args[1], args[2], args[3])
    return {ok = true}

  elseif func_name == "GetProjectMarkers" then
    local markers = {}
    local num_markers, num_regions = reaper.CountProjectMarkers(0)
    for i = 0, num_markers + num_regions - 1 do
      local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
      if not isrgn then
        table.insert(markers, {index = markrgnindexnumber, position = pos, name = name})
      end
    end
    return {ok = true, markers = markers}

  elseif func_name == "GetProjectRegions" then
    local regions = {}
    local num_markers, num_regions = reaper.CountProjectMarkers(0)
    for i = 0, num_markers + num_regions - 1 do
      local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
      if isrgn then
        table.insert(regions, {index = markrgnindexnumber, start = pos, ["end"] = rgnend, name = name})
      end
    end
    return {ok = true, regions = regions}

  elseif func_name == "GoToMarker" then
    reaper.GoToMarker(args[1], args[2], args[3])
    return {ok = true}

  elseif func_name == "GoToRegion" then
    reaper.GoToRegion(args[1], args[2], args[3])
    return {ok = true}

  -- Selection Operations
  elseif func_name == "Main_OnCommand" then
    reaper.Main_OnCommand(args[1], args[2])
    return {ok = true}

  elseif func_name == "SetTrackSelected" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    reaper.SetTrackSelected(track, args[2])
    return {ok = true}

  elseif func_name == "GetSelectedTracks" then
    local selected = {}
    local count = reaper.CountTracks(0)
    for i = 0, count - 1 do
      local track = reaper.GetTrack(0, i)
      if reaper.IsTrackSelected(track) then
        table.insert(selected, i)
      end
    end
    return {ok = true, tracks = selected}

  elseif func_name == "GetSelectedItems" then
    local items = {}
    local count = reaper.CountSelectedMediaItems(0)
    for i = 0, count - 1 do
      local item = reaper.GetSelectedMediaItem(0, i)
      local track = reaper.GetMediaItem_Track(item)
      local track_idx = reaper.GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER") - 1
      local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
      local length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
      table.insert(items, {track = track_idx, position = pos, length = length})
    end
    return {ok = true, items = items}

  -- Undo Operations
  elseif func_name == "Undo_DoUndo2" then
    local ret = reaper.Undo_DoUndo2(args[1])
    return {ok = true, ret = ret}

  elseif func_name == "Undo_DoRedo2" then
    local ret = reaper.Undo_DoRedo2(args[1])
    return {ok = true, ret = ret}

  elseif func_name == "GetUndoState" then
    local can_undo = reaper.Undo_CanUndo2(0)
    local can_redo = reaper.Undo_CanRedo2(0)
    return {ok = true, can_undo = can_undo or "", can_redo = can_redo or ""}

  -- Media Items
  elseif func_name == "GetTrackItems" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local items = {}
    local count = reaper.CountTrackMediaItems(track)
    for i = 0, count - 1 do
      local item = reaper.GetTrackMediaItem(track, i)
      local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
      local length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
      local mute = reaper.GetMediaItemInfo_Value(item, "B_MUTE") == 1
      table.insert(items, {index = i, position = pos, length = length, mute = mute})
    end
    return {ok = true, items = items}

  elseif func_name == "SetMediaItemInfo_Value" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local item = reaper.GetTrackMediaItem(track, args[2])
    if not item then
      return {ok = false, error = "Item not found"}
    end
    reaper.SetMediaItemInfo_Value(item, args[3], args[4])
    return {ok = true}

  elseif func_name == "CreateNewMIDIItemInProj" then
    local track = get_track_by_index(args[1])
    if not track then
      return {ok = false, error = "Track not found"}
    end
    local item = reaper.CreateNewMIDIItemInProj(track, args[2], args[3], args[4])
    return {ok = true, ret = item ~= nil}

  -- Time Selection
  elseif func_name == "SetTimeSelection" then
    reaper.GetSet_LoopTimeRange(true, false, args[1], args[2], false)
    return {ok = true}

  elseif func_name == "GetSet_LoopTimeRange" then
    local start_time, end_time = reaper.GetSet_LoopTimeRange(args[1], args[2], 0, 0, args[5])
    return {ok = true, start_time = start_time, end_time = end_time}

  -- Unknown function
  else
    return {ok = false, error = "Unknown function: " .. func_name}
  end
end

local function handle_post(path, body, client_socket)
  local data = json_decode(body) or {}

  -- Function call endpoint (for MCP server)
  if path == "/call" then
    local func_name = data.func
    local args = data.args or {}
    if not func_name then
      send_error(client_socket, "Missing 'func' in request body")
      return
    end
    local result = handle_function_call(func_name, args)
    send_json(client_socket, result)
    return
  end

  -- Insert track
  if path == "/tracks" then
    local index = data.index or reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(index, true)

    if data.name then
      local track = reaper.GetTrack(0, index)
      if track then
        reaper.GetSetMediaTrackInfo_String(track, "P_NAME", data.name, true)
      end
    end

    local track = reaper.GetTrack(0, index)
    send_json(client_socket, get_track_info(track), 201)
    return
  end

  -- Add FX: /tracks/{index}/fx
  local track_index = path:match("^/tracks/(%-?%d+)/fx$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local fx_name = data.name
    if not fx_name then
      send_error(client_socket, "Missing 'name' in request body")
      return
    end

    local fx_index = reaper.TrackFX_AddByName(track, fx_name, false, -1)
    if fx_index < 0 then
      send_error(client_socket, "Failed to add FX '" .. fx_name .. "'. Plugin may not be installed.")
      return
    end

    send_json(client_socket, get_fx_info(track, fx_index), 201)
    return
  end

  -- Transport play
  if path == "/transport/play" then
    reaper.OnPlayButton()
    send_json(client_socket, {status = "playing"})
    return
  end

  -- Transport stop
  if path == "/transport/stop" then
    reaper.OnStopButton()
    send_json(client_socket, {status = "stopped"})
    return
  end

  -- Create send
  if path == "/sends" then
    local src_index = data.src_track
    local dest_index = data.dest_track

    if not src_index or not dest_index then
      send_error(client_socket, "Missing 'src_track' or 'dest_track'")
      return
    end

    local src_track = get_track(src_index)
    local dest_track = get_track(dest_index)

    if not src_track then
      send_error(client_socket, "Source track " .. src_index .. " not found", 404)
      return
    end
    if not dest_track then
      send_error(client_socket, "Destination track " .. dest_index .. " not found", 404)
      return
    end

    local send_index = reaper.CreateTrackSend(src_track, dest_track)
    send_json(client_socket, {src_track = src_index, dest_track = dest_index, send_index = send_index}, 201)
    return
  end

  -- Save project
  if path == "/project/save" then
    reaper.Main_SaveProject(0, false)
    send_json(client_socket, {status = "saved"})
    return
  end

  send_error(client_socket, "Unknown endpoint: " .. path, 404)
end

local function handle_put(path, body, client_socket)
  local data = json_decode(body) or {}

  -- Update track: /tracks/{index}
  local track_index = path:match("^/tracks/(%-?%d+)$")
  if track_index then
    track_index = tonumber(track_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    if data.name then
      reaper.GetSetMediaTrackInfo_String(track, "P_NAME", data.name, true)
    end
    if data.volume_db then
      reaper.SetMediaTrackInfo_Value(track, "D_VOL", db_to_linear(data.volume_db))
    end
    if data.pan then
      local pan = math.max(-1, math.min(1, data.pan))
      reaper.SetMediaTrackInfo_Value(track, "D_PAN", pan)
    end
    if data.mute ~= nil then
      reaper.SetMediaTrackInfo_Value(track, "B_MUTE", data.mute and 1 or 0)
    end
    if data.solo ~= nil then
      reaper.SetMediaTrackInfo_Value(track, "I_SOLO", data.solo and 1 or 0)
    end

    send_json(client_socket, get_track_info(track))
    return
  end

  -- Update FX: /tracks/{index}/fx/{fx_index}
  local track_index, fx_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)$")
  if track_index and fx_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    if data.enabled ~= nil then
      reaper.TrackFX_SetEnabled(track, fx_index, data.enabled)
    end

    local fx_info = get_fx_info(track, fx_index)
    if not fx_info then
      send_error(client_socket, "FX " .. fx_index .. " not found", 404)
      return
    end

    send_json(client_socket, fx_info)
    return
  end

  -- Set FX param: /tracks/{index}/fx/{fx_index}/params/{param_index}
  local track_index, fx_index, param_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)/params/(%d+)$")
  if track_index and fx_index and param_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    param_index = tonumber(param_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    if data.value == nil then
      send_error(client_socket, "Missing 'value' in request body")
      return
    end

    reaper.TrackFX_SetParam(track, fx_index, param_index, data.value)

    local _, param_name = reaper.TrackFX_GetParamName(track, fx_index, param_index, "")
    local value, minval, maxval = reaper.TrackFX_GetParam(track, fx_index, param_index)

    send_json(client_socket, {
      track_index = track_index,
      fx_index = fx_index,
      param_index = param_index,
      name = param_name,
      value = round(value, 4),
      min = round(minval, 4),
      max = round(maxval, 4)
    })
    return
  end

  -- Set cursor: /transport/cursor
  if path == "/transport/cursor" then
    local position = data.position or 0
    reaper.SetEditCurPos(position, true, false)
    send_json(client_socket, {cursor_position = position})
    return
  end

  -- Update send: /tracks/{index}/sends/{send_index}
  local track_index, send_index = path:match("^/tracks/(%-?%d+)/sends/(%d+)$")
  if track_index and send_index then
    track_index = tonumber(track_index)
    send_index = tonumber(send_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    if data.volume_db then
      reaper.SetTrackSendInfo_Value(track, 0, send_index, "D_VOL", db_to_linear(data.volume_db))
    end
    if data.mute ~= nil then
      reaper.SetTrackSendInfo_Value(track, 0, send_index, "B_MUTE", data.mute and 1 or 0)
    end

    local vol = reaper.GetTrackSendInfo_Value(track, 0, send_index, "D_VOL")
    local mute = reaper.GetTrackSendInfo_Value(track, 0, send_index, "B_MUTE")

    send_json(client_socket, {
      track_index = track_index,
      send_index = send_index,
      volume_db = round(linear_to_db(vol), 2),
      mute = mute == 1
    })
    return
  end

  send_error(client_socket, "Unknown endpoint: " .. path, 404)
end

local function handle_delete(path, client_socket)
  -- Delete track: /tracks/{index}
  local track_index = path:match("^/tracks/(%-?%d+)$")
  if track_index then
    track_index = tonumber(track_index)
    if track_index == -1 then
      send_error(client_socket, "Cannot delete master track")
      return
    end

    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    reaper.DeleteTrack(track)
    send_json(client_socket, {deleted = track_index})
    return
  end

  -- Delete FX: /tracks/{index}/fx/{fx_index}
  local track_index, fx_index = path:match("^/tracks/(%-?%d+)/fx/(%d+)$")
  if track_index and fx_index then
    track_index = tonumber(track_index)
    fx_index = tonumber(fx_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    local fx_count = reaper.TrackFX_GetCount(track)
    if fx_index < 0 or fx_index >= fx_count then
      send_error(client_socket, "FX " .. fx_index .. " not found", 404)
      return
    end

    reaper.TrackFX_Delete(track, fx_index)
    send_json(client_socket, {track_index = track_index, deleted_fx_index = fx_index})
    return
  end

  -- Delete send: /tracks/{index}/sends/{send_index}
  local track_index, send_index = path:match("^/tracks/(%-?%d+)/sends/(%d+)$")
  if track_index and send_index then
    track_index = tonumber(track_index)
    send_index = tonumber(send_index)
    local track = get_track(track_index)
    if not track then
      send_error(client_socket, "Track " .. track_index .. " not found", 404)
      return
    end

    reaper.RemoveTrackSend(track, 0, send_index)
    send_json(client_socket, {track_index = track_index, deleted_send_index = send_index})
    return
  end

  send_error(client_socket, "Unknown endpoint: " .. path, 404)
end

local function handle_options(client_socket)
  -- CORS preflight
  send_response(client_socket, 200, "OK", "")
end

local function handle_request(request_text, client_socket)
  local request = parse_request(request_text)
  if not request then
    send_error(client_socket, "Invalid request")
    return
  end

  if request.method == "OPTIONS" then
    handle_options(client_socket)
  elseif request.method == "GET" then
    handle_get(request.path, client_socket)
  elseif request.method == "POST" then
    handle_post(request.path, request.body, client_socket)
  elseif request.method == "PUT" then
    handle_put(request.path, request.body, client_socket)
  elseif request.method == "DELETE" then
    handle_delete(request.path, client_socket)
  else
    send_error(client_socket, "Method not allowed", 405)
  end
end

-- ============================================================================
-- Server Main Loop
-- ============================================================================

local server_socket = nil

local function process_requests()
  if not server_socket then return end

  -- Check for new connections (non-blocking)
  local client, err = server_socket:accept()
  if client then
    client:settimeout(0.1)

    -- Read request
    local request_text = ""
    local line, err
    repeat
      line, err = client:receive("*l")
      if line then
        request_text = request_text .. line .. "\r\n"
      end
    until not line or line == ""

    -- Read body if Content-Length header present
    local content_length = request_text:match("[Cc]ontent%-[Ll]ength:%s*(%d+)")
    if content_length then
      content_length = tonumber(content_length)
      if content_length > 0 then
        local body, err = client:receive(content_length)
        if body then
          request_text = request_text .. body
        end
      end
    end

    if #request_text > 0 then
      handle_request(request_text, client)
    end

    client:close()
  end

  -- Continue running
  if server_running then
    reaper.defer(process_requests)
  end
end

local function start_server()
  server_socket = socket.tcp()
  server_socket:setoption("reuseaddr", true)

  local ok, err = server_socket:bind(HOST, PORT)
  if not ok then
    reaper.ShowConsoleMsg("ERROR: Failed to bind to " .. HOST .. ":" .. PORT .. "\n")
    reaper.ShowConsoleMsg("Error: " .. tostring(err) .. "\n")
    reaper.ShowConsoleMsg("Port may be in use. Try restarting REAPER.\n")
    return
  end

  server_socket:listen(5)
  server_socket:settimeout(0)  -- Non-blocking

  server_running = true

  reaper.ShowConsoleMsg("===========================================\n")
  reaper.ShowConsoleMsg("REAPER Web Server started!\n")
  reaper.ShowConsoleMsg("URL: http://" .. HOST .. ":" .. PORT .. "\n")
  reaper.ShowConsoleMsg("===========================================\n")
  reaper.ShowConsoleMsg("\nEndpoints:\n")
  reaper.ShowConsoleMsg("  GET  /ping - Health check\n")
  reaper.ShowConsoleMsg("  GET  /tracks/count - Track count\n")
  reaper.ShowConsoleMsg("  GET  /tracks/{index} - Track info\n")
  reaper.ShowConsoleMsg("  POST /tracks/{index}/fx - Add FX\n")
  reaper.ShowConsoleMsg("  ... and more (see README)\n")
  reaper.ShowConsoleMsg("\nUse track_index=-1 for master track\n")
  reaper.ShowConsoleMsg("===========================================\n")

  reaper.defer(process_requests)
end

-- Start the server
start_server()
