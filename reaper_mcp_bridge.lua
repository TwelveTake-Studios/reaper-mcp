-- REAPER MCP Bridge
-- This single bridge supports ALL profiles and includes:
-- - All ReaScript API functions (600+)
-- - All DSL (Domain Specific Language) functions for natural language control
-- Profile selection is handled by the Python MCP server, not this bridge

local bridge_dir = reaper.GetResourcePath() .. '/Scripts/mcp_bridge_data/'

-- Create bridge directory if it doesn't exist
local function ensure_dir()
    reaper.RecursiveCreateDirectory(bridge_dir, 0)
end

-- Array marker: a table tagged via as_array() always serializes as a JSON array,
-- even when empty, so an empty list encodes as [] instead of {}. Declared BEFORE
-- encode_json so the encoder sees ARRAY_MARKER as an upvalue -- a marker defined
-- after the encoder would resolve to a nil global and silently disable the tag.
local ARRAY_MARKER = {}
local function as_array(t)
    return setmetatable(t or {}, ARRAY_MARKER)
end

-- Simple JSON encoding (minimal implementation)
local function encode_json(v)
    if type(v) == "nil" then
        return "null"
    elseif type(v) == "boolean" then
        return tostring(v)
    elseif type(v) == "number" then
        return tostring(v)
    elseif type(v) == "string" then
        -- Escape backslashes first, then other special chars
        return string.format('"%s"', v:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'))
    elseif type(v) == "table" then
        local parts = {}
        local is_array = getmetatable(v) == ARRAY_MARKER or #v > 0
        if is_array then
            for i, item in ipairs(v) do
                table.insert(parts, encode_json(item))
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            for k, item in pairs(v) do
                table.insert(parts, string.format('"%s":%s', k, encode_json(item)))
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    elseif type(v) == "userdata" then
        -- Handle userdata (pointers) by converting to a handle ID
        return encode_json({__ptr = tostring(v)})
    else
        return "null"
    end
end

-- Better JSON decoding that handles arrays properly
local function decode_json(str)
    if not str or str == "" then return nil end
    
    -- Remove whitespace
    str = str:gsub("^%s*(.-)%s*$", "%1")
    
    -- Very basic JSON decoder
    if str == "null" then return nil
    elseif str == "true" then return true
    elseif str == "false" then return false
    elseif str:match("^%-?%d+%.?%d*$") then return tonumber(str)
    elseif str:match('^"(.*)"$') then
        -- Unescape string in a SINGLE pass so '\\' is consumed atomically.
        -- (Sequential gsubs corrupted Windows paths: in "Temp\\reaper" the second
        -- backslash + 'r' matched '\\r' and became a carriage return.)
        local s = str:match('^"(.*)"$')
        local escapes = { n = '\n', r = '\r', t = '\t', b = '\b', f = '\f',
                          ['"'] = '"', ['\\'] = '\\', ['/'] = '/' }
        s = s:gsub('\\(.)', function(c) return escapes[c] or c end)
        return s
    elseif str:match("^%[.*%]$") then
        -- Array - improved parsing
        local arr = {}
        local content = str:sub(2, -2)
        if content ~= "" then
            -- Handle nested structures better
            local i = 1
            local pos = 1
            local depth = 0
            local start = 1
            
            while pos <= #content do
                local char = content:sub(pos, pos)
                if char == '[' or char == '{' then
                    depth = depth + 1
                elseif char == ']' or char == '}' then
                    depth = depth - 1
                elseif char == ',' and depth == 0 then
                    -- Found a top-level comma
                    local value = content:sub(start, pos - 1)
                    arr[i] = decode_json(value:match("^%s*(.-)%s*$"))
                    i = i + 1
                    start = pos + 1
                end
                pos = pos + 1
            end
            
            -- Don't forget the last element
            if start <= #content then
                local value = content:sub(start)
                arr[i] = decode_json(value:match("^%s*(.-)%s*$"))
            end
        end
        return arr
    elseif str:match("^{.*}$") then
        -- Object - improved parsing
        local obj = {}
        local content = str:sub(2, -2)
        
        -- Better object parsing that handles nested values
        local pos = 1
        while pos <= #content do
            -- Find key
            local key_start = content:find('"', pos)
            if not key_start then break end
            local key_end = content:find('"', key_start + 1)
            if not key_end then break end
            local key = content:sub(key_start + 1, key_end - 1)
            
            -- Find colon
            local colon = content:find(':', key_end + 1)
            if not colon then break end
            
            -- Find value (handle nested structures)
            local value_start = colon + 1
            while value_start <= #content and content:sub(value_start, value_start):match("%s") do
                value_start = value_start + 1
            end
            
            local value_end = value_start
            local depth = 0
            local in_string = false
            local escape = false
            
            while value_end <= #content do
                local char = content:sub(value_end, value_end)
                
                if escape then
                    escape = false
                elseif char == '\\' then
                    escape = true
                elseif char == '"' and not escape then
                    in_string = not in_string
                elseif not in_string then
                    if char == '[' or char == '{' then
                        depth = depth + 1
                    elseif char == ']' or char == '}' then
                        depth = depth - 1
                    elseif (char == ',' or char == '}') and depth == 0 then
                        break
                    end
                end
                
                value_end = value_end + 1
            end
            
            local value = content:sub(value_start, value_end - 1)
            obj[key] = decode_json(value:match("^%s*(.-)%s*$"))
            
            pos = value_end + 1
        end
        
        return obj
    end
    return nil
end

-- Read file contents
local function read_file(filepath)
    local file = io.open(filepath, "r")
    if not file then return nil end
    local content = file:read("*all")
    file:close()
    return content
end

-- Write file contents
local function write_file(filepath, content)
    local file = io.open(filepath, "w")
    if not file then return false end
    file:write(content)
    file:close()
    return true
end

-- Check if file exists
local function file_exists(filepath)
    local file = io.open(filepath, "r")
    if file then
        file:close()
        return true
    end
    return false
end

-- Delete file
local function delete_file(filepath)
    os.remove(filepath)
end


-- ============================================================================
-- DSL HELPER FUNCTIONS
-- ============================================================================

-- ============================================================================
-- DSL HELPER FUNCTIONS
-- ============================================================================

-- Get detailed track information including MIDI/audio content and FX
local function GetTrackInfo(track_index)
    local track = nil
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end
    
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    -- Get track info
    local retval, name = reaper.GetTrackName(track)
    local retval, guid = reaper.GetSetMediaTrackInfo_String(track, "GUID", "", false)
    
    -- Check for MIDI and audio items
    local has_midi = false
    local has_audio = false
    local item_count = reaper.CountTrackMediaItems(track)
    
    for i = 0, item_count - 1 do
        local item = reaper.GetTrackMediaItem(track, i)
        if item then
            local take = reaper.GetActiveTake(item)
            if take then
                if reaper.TakeIsMIDI(take) then
                    has_midi = true
                else
                    has_audio = true
                end
            end
        end
    end
    
    -- Get FX names
    local fx_names = as_array({})
    local fx_count = reaper.TrackFX_GetCount(track)
    for i = 0, fx_count - 1 do
        local retval, fx_name = reaper.TrackFX_GetFXName(track, i, "")
        if retval then
            table.insert(fx_names, fx_name)
        end
    end
    
    -- Check for role in track notes
    local retval, notes = reaper.GetSetMediaTrackInfo_String(track, "P_EXT:role", "", false)
    local role = nil
    if notes and notes ~= "" then
        role = notes
    end
    
    return {
        ok = true,
        info = {
            guid = guid,
            name = name,
            has_midi = has_midi,
            has_audio = has_audio,
            fx_names = fx_names,
            role = role,
            muted = reaper.GetMediaTrackInfo_Value(track, "B_MUTE") == 1,
            soloed = reaper.GetMediaTrackInfo_Value(track, "I_SOLO") > 0
        }
    }
end

-- Get all tracks with detailed info
local function GetAllTracksInfo()
    local tracks = as_array({})
    local count = reaper.CountTracks(0)
    
    for i = 0, count - 1 do
        local result = GetTrackInfo(i)
        if result.ok then
            local info = result.info
            info.index = i
            table.insert(tracks, info)
        end
    end
    
    return {ok = true, tracks = tracks}
end

-- Get selected tracks
local function GetSelectedTracks()
    local selected = as_array({})
    local count = reaper.CountTracks(0)
    for i = 0, count - 1 do
        local track = reaper.GetTrack(0, i)
        if reaper.IsTrackSelected(track) then
            table.insert(selected, i)
        end
    end
    return {ok = true, tracks = selected}
end

-- Get/Set track notes (used for storing role)
local function SetTrackNotes(track_index, notes)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    -- Store in extended state
    reaper.GetSetMediaTrackInfo_String(track, "P_EXT:role", notes, true)
    return {ok = true}
end

-- Get current cursor position
local function GetCursorPosition()
    local pos = reaper.GetCursorPosition()
    return {ok = true, ret = pos}
end

-- Get time selection
local function GetTimeSelection()
    local start_time, end_time = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
    return {ok = true, start = start_time, ["end"] = end_time}
end

-- Set time selection
local function SetTimeSelection(start_time, end_time)
    reaper.GetSet_LoopTimeRange(true, false, start_time, end_time, false)
    return {ok = true}
end

-- Get loop time range
local function GetLoopTimeRange()
    local start_time, end_time = reaper.GetSet_LoopTimeRange(false, true, 0, 0, false)
    return {ok = true, start = start_time, ["end"] = end_time}
end

-- Convert bars to time duration
local function BarsToTime(bars, start_pos)
    -- Get tempo at position
    local tempo = reaper.Master_GetTempo()
    local retval, num, denom = reaper.TimeMap_GetTimeSigAtTime(0, start_pos or 0)
    
    -- Calculate duration
    local beats_per_bar = num
    local total_beats = bars * beats_per_bar
    local duration = (total_beats / tempo) * 60
    
    return {ok = true, ret = duration}
end

-- Find region by name
local function FindRegion(name)
    local retval, num_markers, num_regions = reaper.CountProjectMarkers(0)
    
    for i = 0, num_markers + num_regions - 1 do
        local retval, isrgn, pos, rgnend, rgn_name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
        if isrgn and rgn_name == name then
            return {ok = true, found = true, start = pos, ["end"] = rgnend}
        end
    end
    
    return {ok = true, found = false}
end

-- Find marker by name
local function FindMarker(name)
    local retval, num_markers, num_regions = reaper.CountProjectMarkers(0)
    
    for i = 0, num_markers + num_regions - 1 do
        local retval, isrgn, pos, rgnend, marker_name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
        if not isrgn and marker_name == name then
            return {ok = true, found = true, position = pos}
        end
    end
    
    return {ok = true, found = false}
end

-- Get selected items
local function GetSelectedItems()
    local items = as_array({})
    local count = reaper.CountSelectedMediaItems(0)
    
    for i = 0, count - 1 do
        local item = reaper.GetSelectedMediaItem(0, i)
        if item then
            local track = reaper.GetMediaItem_Track(item)
            local track_index = -1
            
            -- Find track index
            for j = 0, reaper.CountTracks(0) - 1 do
                if reaper.GetTrack(0, j) == track then
                    track_index = j
                    break
                end
            end
            
            local take = reaper.GetActiveTake(item)
            local is_midi = (take and reaper.TakeIsMIDI(take)) or false
            -- Guard: GetTakeName requires a take; an item with no active take (empty item,
            -- or one left by explode_takes) would crash on GetTakeName(item).
            local name = ""
            if take then
                local _
                _, name = reaper.GetTakeName(take)
            end
            
            table.insert(items, {
                index = i,
                track_index = track_index,
                position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
                length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
                name = name,
                is_midi = is_midi
            })
        end
    end
    
    return {ok = true, items = items}
end

-- Get all items
local function GetAllItems()
    local items = as_array({})
    local track_count = reaper.CountTracks(0)
    
    for t = 0, track_count - 1 do
        local track = reaper.GetTrack(0, t)
        local item_count = reaper.CountTrackMediaItems(track)
        
        for i = 0, item_count - 1 do
            local item = reaper.GetTrackMediaItem(track, i)
            if item then
                local take = reaper.GetActiveTake(item)
                local is_midi = (take and reaper.TakeIsMIDI(take)) or false
                -- Guard: GetTakeName needs a take; an item with no active take would crash.
                local name = ""
                if take then
                    local _
                    _, name = reaper.GetTakeName(take)
                end
                
                table.insert(items, {
                    index = i,
                    track_index = t,
                    position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
                    length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
                    name = name,
                    is_midi = is_midi
                })
            end
        end
    end
    
    return {ok = true, items = items}
end

-- Get items on specific track
local function GetTrackItems(track_index)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local items = as_array({})
    local item_count = reaper.CountTrackMediaItems(track)
    
    for i = 0, item_count - 1 do
        local item = reaper.GetTrackMediaItem(track, i)
        if item then
            local take = reaper.GetActiveTake(item)
            local is_midi = (take and reaper.TakeIsMIDI(take)) or false
            -- Guard: GetTakeName requires a take; an item with no active take (empty item,
            -- or one left by explode_takes) would crash on GetTakeName(item).
            local name = ""
            if take then
                local _
                _, name = reaper.GetTakeName(take)
            end
            
            table.insert(items, {
                index = i,
                track_index = track_index,
                position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
                length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
                name = name,
                is_midi = is_midi
            })
        end
    end
    
    return {ok = true, items = items}
end

-- Create MIDI item
local function CreateMIDIItem(track_index, start_pos, end_pos)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local item = reaper.CreateNewMIDIItemInProj(track, start_pos, end_pos, false)
    if not item then
        return {ok = false, error = "Failed to create MIDI item"}
    end
    
    -- Find item index on track
    local item_index = -1
    for i = 0, reaper.CountTrackMediaItems(track) - 1 do
        if reaper.GetTrackMediaItem(track, i) == item then
            item_index = i
            break
        end
    end
    
    return {ok = true, item_index = item_index}
end

-- Create audio item (empty)
local function CreateAudioItem(track_index, start_pos, end_pos)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    -- Create empty item
    local item = reaper.AddMediaItemToTrack(track)
    if not item then
        return {ok = false, error = "Failed to create audio item"}
    end
    
    -- Set position and length
    reaper.SetMediaItemInfo_Value(item, "D_POSITION", start_pos)
    reaper.SetMediaItemInfo_Value(item, "D_LENGTH", end_pos - start_pos)
    
    -- Find item index on track
    local item_index = -1
    for i = 0, reaper.CountTrackMediaItems(track) - 1 do
        if reaper.GetTrackMediaItem(track, i) == item then
            item_index = i
            break
        end
    end
    
    return {ok = true, item_index = item_index}
end

-- Set item loop source
local function SetItemLoopSource(track_index, item_index, loop_source)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local item = reaper.GetTrackMediaItem(track, item_index)
    if not item then
        return {ok = false, error = "Item not found"}
    end
    
    reaper.SetMediaItemInfo_Value(item, "B_LOOPSRC", loop_source and 1 or 0)
    return {ok = true}
end

-- Insert MIDI note
local function InsertMIDINote(track_index, item_index, pitch, start_ppq, length_ppq, velocity, channel)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local item = reaper.GetTrackMediaItem(track, item_index)
    if not item then
        return {ok = false, error = "Item not found"}
    end
    
    local take = reaper.GetActiveTake(item)
    if not take or not reaper.TakeIsMIDI(take) then
        return {ok = false, error = "Not a MIDI take"}
    end
    
    -- Convert time to PPQ
    local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local ppq_start = reaper.MIDI_GetPPQPosFromProjTime(take, item_pos + start_ppq)
    local ppq_end = reaper.MIDI_GetPPQPosFromProjTime(take, item_pos + start_ppq + length_ppq)
    
    reaper.MIDI_InsertNote(take, false, false, ppq_start, ppq_end, channel or 0, pitch, velocity or 100, false)
    reaper.MIDI_Sort(take)
    
    return {ok = true}
end

-- Track operations
local function GetTrackVolume(track_index)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local vol = reaper.GetMediaTrackInfo_Value(track, "D_VOL")
    return {ok = true, ret = vol}
end

local function SetTrackVolume(track_index, volume)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    reaper.SetMediaTrackInfo_Value(track, "D_VOL", volume)
    return {ok = true}
end

local function GetTrackPan(track_index)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    local pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN")
    return {ok = true, ret = pan}
end

local function SetTrackPan(track_index, pan)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    reaper.SetMediaTrackInfo_Value(track, "D_PAN", pan)
    return {ok = true}
end

local function SetTrackMute(track_index, mute)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    reaper.SetMediaTrackInfo_Value(track, "B_MUTE", mute and 1 or 0)
    return {ok = true}
end

local function SetTrackSolo(track_index, solo)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return {ok = false, error = "Track not found"}
    end
    
    reaper.SetMediaTrackInfo_Value(track, "I_SOLO", solo and 1 or 0)
    return {ok = true}
end

-- Transport operations
local function Play()
    reaper.Main_OnCommand(1007, 0) -- Transport: Play
    return {ok = true}
end

local function Stop()
    reaper.Main_OnCommand(1016, 0) -- Transport: Stop
    return {ok = true}
end

local function GetTempo()
    local tempo = reaper.Master_GetTempo()
    return {ok = true, ret = tempo}
end

local function SetTempo(bpm)
    reaper.SetTempoTimeSigMarker(0, -1, -1, -1, -1, bpm, 0, 0, false)
    return {ok = true}
end

local function GetTimeSignature()
    -- GetProjectTimeSignature2 returns: bpm (tempo), bpi (beats per measure = numerator)
    local bpm, bpi = reaper.GetProjectTimeSignature2(0)
    -- TimeMap_GetTimeSigAtTime at position 0 gives us the time signature
    -- Returns: retval, timesig_num, timesig_denom, tempo
    -- But Lua binding may differ - let's capture all and find correct values
    local r1, r2, r3, r4 = reaper.TimeMap_GetTimeSigAtTime(0, 0)
    -- Based on testing: r1=num(4), r2=tempo(92), so denominator not directly available
    -- For standard time signatures, denominator is typically 4 (quarter note)
    -- Use TimeMap2_timeToBeats to get more accurate info if needed
    local numerator = bpi  -- beats per measure
    local denominator = 4  -- assume quarter note (most common)
    return {ok = true, numerator = numerator, denominator = denominator, tempo = bpm}
end

-- Get or create an FX parameter envelope
local function GetFXEnvelope(track_index, fx_index, param_index)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end

    if not track then
        return {ok = false, error = "Track not found"}
    end

    -- GetFXEnvelope creates the envelope if it doesn't exist
    local envelope = reaper.GetFXEnvelope(track, fx_index, param_index, true)
    if not envelope then
        return {ok = false, error = "Could not get/create FX envelope"}
    end

    -- Get envelope info
    local retval, env_name = reaper.GetEnvelopeName(envelope)
    local point_count = reaper.CountEnvelopePoints(envelope)

    -- Get the parameter name for context
    local param_retval, param_name = reaper.TrackFX_GetParamName(track, fx_index, param_index, "")

    return {
        ok = true,
        envelope_name = env_name,
        param_name = param_name,
        point_count = point_count,
        track_index = track_index,
        fx_index = fx_index,
        param_index = param_index
    }
end

-- Add a point to an FX parameter envelope
local function AddFXEnvelopePoint(track_index, fx_index, param_index, time, value, shape)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end

    if not track then
        return {ok = false, error = "Track not found"}
    end

    -- Get or create the envelope
    local envelope = reaper.GetFXEnvelope(track, fx_index, param_index, true)
    if not envelope then
        return {ok = false, error = "Could not get/create FX envelope"}
    end

    -- Add the point (shape: 0=linear, 1=square, 2=slow start/end, 3=fast start, 4=fast end, 5=bezier)
    local point_index = reaper.InsertEnvelopePoint(envelope, time, value, shape or 0, 0, false, true)
    reaper.Envelope_SortPoints(envelope)

    return {
        ok = true,
        point_index = point_index,
        time = time,
        value = value,
        shape = shape or 0
    }
end

-- Get all points from an FX parameter envelope
local function GetFXEnvelopePoints(track_index, fx_index, param_index)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end

    if not track then
        return {ok = false, error = "Track not found"}
    end

    local envelope = reaper.GetFXEnvelope(track, fx_index, param_index, false)
    if not envelope then
        return {ok = false, error = "FX envelope not found (not created yet)"}
    end

    local points = as_array({})
    local count = reaper.CountEnvelopePoints(envelope)

    for i = 0, count - 1 do
        local retval, time, value, shape, tension, selected = reaper.GetEnvelopePoint(envelope, i)
        if retval then
            table.insert(points, {
                index = i,
                time = time,
                value = value,
                shape = shape,
                tension = tension,
                selected = selected
            })
        end
    end

    return {ok = true, points = points, count = count}
end

-- Delete a point from an FX parameter envelope
local function DeleteFXEnvelopePoint(track_index, fx_index, param_index, point_index)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end

    if not track then
        return {ok = false, error = "Track not found"}
    end

    local envelope = reaper.GetFXEnvelope(track, fx_index, param_index, false)
    if not envelope then
        return {ok = false, error = "FX envelope not found"}
    end

    local retval = reaper.DeleteEnvelopePointEx(envelope, -1, point_index)
    return {ok = retval}
end

-- Clear all points from an FX parameter envelope
local function ClearFXEnvelope(track_index, fx_index, param_index)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end

    if not track then
        return {ok = false, error = "Track not found"}
    end

    local envelope = reaper.GetFXEnvelope(track, fx_index, param_index, false)
    if not envelope then
        return {ok = false, error = "FX envelope not found"}
    end

    -- Delete all points
    local count = reaper.CountEnvelopePoints(envelope)
    for i = count - 1, 0, -1 do
        reaper.DeleteEnvelopePointEx(envelope, -1, i)
    end

    return {ok = true, deleted_count = count}
end

-- Get comprehensive project summary for Claude context
local function GetProjectSummary()
    -- Helper to convert linear volume to dB
    local function linear_to_db(vol)
        if vol <= 0 then return -150 end
        return 20 * math.log(vol) / math.log(10)
    end

    -- Get project name and path
    local retval, project_path = reaper.EnumProjects(-1, "")
    local project_name = ""
    if project_path and project_path ~= "" then
        project_name = project_path:match("([^/\\]+)%.rpp$") or project_path:match("([^/\\]+)$") or ""
    end

    -- Get tempo and time signature
    local bpm, bpi = reaper.GetProjectTimeSignature2(0)

    -- Get project length
    local project_length = reaper.GetProjectLength(0)

    -- Get track count
    local track_count = reaper.CountTracks(0)

    -- Get all tracks info
    local tracks = as_array({})
    for i = 0, track_count - 1 do
        local track = reaper.GetTrack(0, i)
        if track then
            local retval, name = reaper.GetTrackName(track)
            local vol = reaper.GetMediaTrackInfo_Value(track, "D_VOL")
            local pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN")
            local mute = reaper.GetMediaTrackInfo_Value(track, "B_MUTE") == 1
            local solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO") > 0

            -- Get FX info
            local fx_count = reaper.TrackFX_GetCount(track)
            local fx_names = as_array({})
            for j = 0, fx_count - 1 do
                local retval, fx_name = reaper.TrackFX_GetFXName(track, j, "")
                if retval then
                    table.insert(fx_names, fx_name)
                end
            end

            table.insert(tracks, {
                index = i,
                name = name,
                volume_db = linear_to_db(vol),
                pan = pan,
                mute = mute,
                solo = solo,
                fx_count = fx_count,
                fx_names = fx_names
            })
        end
    end

    -- Get master track info
    local master = reaper.GetMasterTrack(0)
    local master_vol = reaper.GetMediaTrackInfo_Value(master, "D_VOL")
    local master_fx_count = reaper.TrackFX_GetCount(master)
    local master_fx_names = as_array({})
    for j = 0, master_fx_count - 1 do
        local retval, fx_name = reaper.TrackFX_GetFXName(master, j, "")
        if retval then
            table.insert(master_fx_names, fx_name)
        end
    end

    local master_info = {
        volume_db = linear_to_db(master_vol),
        fx_count = master_fx_count,
        fx_names = master_fx_names
    }

    -- Get markers and regions
    local markers = as_array({})
    local regions = as_array({})
    local ret, num_markers, num_regions = reaper.CountProjectMarkers(0)
    for i = 0, num_markers + num_regions - 1 do
        local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
        if retval then
            if isrgn then
                table.insert(regions, {
                    index = markrgnindexnumber,
                    start = pos,
                    ["end"] = rgnend,
                    name = name
                })
            else
                table.insert(markers, {
                    index = markrgnindexnumber,
                    position = pos,
                    name = name
                })
            end
        end
    end

    return {
        ok = true,
        project_name = project_name,
        project_path = project_path,
        tempo = bpm,
        time_signature = {numerator = bpi, denominator = 4},
        project_length = project_length,
        track_count = track_count,
        tracks = tracks,
        master = master_info,
        markers = markers,
        regions = regions
    }
end

-- Export function table for DSL
DSL_FUNCTIONS = {
    -- Track info
    GetTrackInfo = GetTrackInfo,
    GetAllTracksInfo = GetAllTracksInfo,
    GetSelectedTracks = GetSelectedTracks,
    SetTrackNotes = SetTrackNotes,
    
    -- Time operations
    GetCursorPosition = GetCursorPosition,
    GetTimeSelection = GetTimeSelection,
    SetTimeSelection = SetTimeSelection,
    GetLoopTimeRange = GetLoopTimeRange,
    BarsToTime = BarsToTime,
    FindRegion = FindRegion,
    FindMarker = FindMarker,
    
    -- Item operations
    GetSelectedItems = GetSelectedItems,
    GetAllItems = GetAllItems,
    GetTrackItems = GetTrackItems,
    CreateMIDIItem = CreateMIDIItem,
    CreateAudioItem = CreateAudioItem,
    SetItemLoopSource = SetItemLoopSource,
    InsertMIDINote = InsertMIDINote,
    
    -- Track operations
    GetTrackVolume = GetTrackVolume,
    SetTrackVolume = SetTrackVolume,
    GetTrackPan = GetTrackPan,
    SetTrackPan = SetTrackPan,
    SetTrackMute = SetTrackMute,
    SetTrackSolo = SetTrackSolo,
    
    -- Transport
    Play = Play,
    Stop = Stop,
    GetTempo = GetTempo,
    SetTempo = SetTempo,
    GetTimeSignature = GetTimeSignature,

    -- Project summary
    GetProjectSummary = GetProjectSummary,

    -- FX parameter automation
    GetFXEnvelope = GetFXEnvelope,
    AddFXEnvelopePoint = AddFXEnvelopePoint,
    GetFXEnvelopePoints = GetFXEnvelopePoints,
    DeleteFXEnvelopePoint = DeleteFXEnvelopePoint,
    ClearFXEnvelope = ClearFXEnvelope
}

-- Resolve a take from (track_index, item_index, take_index).
-- Returns take, nil on success, or nil, errmsg on any out-of-range index.
-- Used by the Take FX handlers (TakeFX_* needs a MediaItem_Take*, not indices).
local function resolve_take(track_index, item_index, take_index)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return nil, "Track not found at index " .. tostring(track_index)
    end
    local item = reaper.GetTrackMediaItem(track, item_index)
    if not item then
        return nil, "Media item not found at index " .. tostring(item_index)
            .. " on track " .. tostring(track_index)
    end
    local take = reaper.GetTake(item, take_index)
    if not take then
        return nil, "Take not found at index " .. tostring(take_index)
    end
    return take, nil
end

-- Run a Main_OnCommand action against exactly one item: save the current item selection,
-- select only the target, fire the action, then restore whatever saved items still exist
-- (destructive actions like explode can invalidate item pointers; ValidatePtr2 guards that).
local function run_item_action(track_index, item_index, cmd_id)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return false, "Track not found at index " .. tostring(track_index)
    end
    local item = reaper.GetTrackMediaItem(track, item_index)
    if not item then
        return false, "Media item not found at index " .. tostring(item_index)
            .. " on track " .. tostring(track_index)
    end
    local saved = {}
    for i = 0, reaper.CountSelectedMediaItems(0) - 1 do
        saved[#saved + 1] = reaper.GetSelectedMediaItem(0, i)
    end
    reaper.SelectAllMediaItems(0, false)
    reaper.SetMediaItemSelected(item, true)
    reaper.Main_OnCommand(cmd_id, 0)
    reaper.SelectAllMediaItems(0, false)
    for _, it in ipairs(saved) do
        if reaper.ValidatePtr2(0, it, "MediaItem*") then
            reaper.SetMediaItemSelected(it, true)
        end
    end
    reaper.UpdateArrange()
    return true, nil
end

-- Resolve a track envelope by name from (track_index, env_name). -1 = master track.
local function resolve_envelope(track_index, env_name)
    local track
    if track_index == -1 then
        track = reaper.GetMasterTrack(0)
    else
        track = reaper.GetTrack(0, track_index)
    end
    if not track then
        return nil, "Track not found at index " .. tostring(track_index)
    end
    local env = reaper.GetTrackEnvelopeByName(track, env_name)
    if not env then
        return nil, "Envelope '" .. tostring(env_name) .. "' not found on track "
            .. tostring(track_index) .. " (create/show it in REAPER first)"
    end
    return env, nil
end

-- Resolve the active MIDI take of (track_index, item_index).
local function resolve_midi_take(track_index, item_index)
    local track = reaper.GetTrack(0, track_index)
    if not track then
        return nil, "Track not found at index " .. tostring(track_index)
    end
    local item = reaper.GetTrackMediaItem(track, item_index)
    if not item then
        return nil, "Media item not found at index " .. tostring(item_index)
            .. " on track " .. tostring(track_index)
    end
    local take = reaper.GetActiveTake(item)
    if not take or not reaper.TakeIsMIDI(take) then
        return nil, "Active take of item " .. tostring(item_index) .. " is not MIDI"
    end
    return take, nil
end

-- === v1.6.0 MIDI utilities — shared helpers ==============================
-- Pure transform seams (no reaper.*), sliced out for headless golden tests.
-- === MIDI_PURE_BEGIN (sliceable: no reaper.* — headless-testable) ===
-- note fields used here: {index, startppq, endppq, chan, pitch, vel, selected, muted}.
-- ctx = {item_start_ppq, ppq_per_qn}. A beat bound b maps to PPQ item_start_ppq + b*ppq_per_qn.
local function note_in_filter(note, filt, ctx)
    if note.pitch < (filt.pitch_low or 0) then return false end
    if note.pitch > (filt.pitch_high or 127) then return false end
    if filt.channel ~= nil and filt.channel ~= -1 and note.chan ~= filt.channel then return false end
    if filt.start_beat ~= nil and note.startppq < ctx.item_start_ppq + filt.start_beat * ctx.ppq_per_qn then
        return false
    end
    if filt.end_beat ~= nil and note.startppq > ctx.item_start_ppq + filt.end_beat * ctx.ppq_per_qn then
        return false
    end
    return true
end

-- transpose: pitch-only, count-preserving. Out-of-range result pitch -> skip (D3).
local function transpose_notes_pure(notes, semitones, filt, ctx)
    local changes = {}
    local notes_changed, skipped = 0, 0
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then
            local np = n.pitch + semitones
            if np < 0 or np > 127 then
                skipped = skipped + 1
            elseif np ~= n.pitch then
                changes[#changes + 1] = {index = n.index, new_pitch = np}
                notes_changed = notes_changed + 1
            end
        end
    end
    return {changes = changes, notes_changed = notes_changed, skipped = skipped}
end

-- nudge: shift matched notes' start AND end by the same tick delta (length preserved).
-- Notes moved before item start / past item end are ALLOWED and counted (D10), never clamped.
local function nudge_notes_pure(notes, delta_ppq, filt, ctx)
    local changes = {}
    local notes_changed, out_of_bounds = 0, 0
    if delta_ppq ~= 0 then
        for _, n in ipairs(notes) do
            if note_in_filter(n, filt, ctx) then
                local len = n.endppq - n.startppq
                local ns = n.startppq + delta_ppq
                local oob = false
                -- REAPER refuses MIDI notes before the item/source start; clamp to it and flag [D10].
                if ns < ctx.item_start_ppq then
                    ns = ctx.item_start_ppq
                    oob = true
                end
                local ne = ns + len                             -- length preserved
                if ne > ctx.item_end_ppq then oob = true end    -- past item end: REAPER allows, just flag
                if ns ~= n.startppq then                        -- only write notes that actually move
                    changes[#changes + 1] = {index = n.index, new_start = ns, new_end = ne}
                    notes_changed = notes_changed + 1
                end
                if oob then out_of_bounds = out_of_bounds + 1 end
            end
        end
    end
    return {changes = changes, notes_changed = notes_changed, out_of_bounds = out_of_bounds}
end

-- filter to the notes flagged selected in REAPER (order/fields/absolute index preserved).
local function filter_selected(notes)
    local out = {}
    for _, n in ipairs(notes) do
        if n.selected then out[#out + 1] = n end
    end
    return out
end

-- set_midi_note seams (single-note edit) ----------------------------------
local function beats_to_take_ppq(beat, item_start_ppq, ppq_per_qn)
    return item_start_ppq + beat * ppq_per_qn
end
local function len_beats_to_ppq(len_beats, ppq_per_qn)
    return len_beats * ppq_per_qn
end
-- move (start only) preserves length; resize (length only) keeps start; both sets both; neither untouched.
local function compute_note_span(old_start, old_end, new_start_ppq, new_len_ppq)
    if new_start_ppq and new_len_ppq then
        return new_start_ppq, new_start_ppq + new_len_ppq
    elseif new_start_ppq then
        return new_start_ppq, new_start_ppq + (old_end - old_start)
    elseif new_len_ppq then
        return old_start, old_start + new_len_ppq
    else
        return old_start, old_end
    end
end
local function note_out_of_bounds(startppq, endppq, item_start_ppq, item_end_ppq)
    return startppq < item_start_ppq or endppq > item_end_ppq
end
local function valid_pitch(p) return type(p) == "number" and p == math.floor(p) and p >= 0 and p <= 127 end
local function valid_channel(c) return type(c) == "number" and c == math.floor(c) and c >= 0 and c <= 15 end
local function valid_length(l) return type(l) == "number" and l > 0 end

-- linear velocity ramp keyed on onset: earliest filtered note -> start_vel, latest -> end_vel.
-- Notes sharing an onset get the same t (chord = one velocity). Result clamped to 1-127 (D3).
local function midi_ramp_velocities(notes, filt, ctx, start_vel, end_vel)
    local matched, min_ppq, max_ppq = {}, nil, nil
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then
            matched[#matched + 1] = n
            if not min_ppq or n.startppq < min_ppq then min_ppq = n.startppq end
            if not max_ppq or n.startppq > max_ppq then max_ppq = n.startppq end
        end
    end
    local changes, notes_changed, clamped = {}, 0, 0
    local span = (max_ppq and max_ppq - min_ppq) or 0
    for _, n in ipairs(matched) do
        local t = (span > 0) and (n.startppq - min_ppq) / span or 0
        local nv = math.floor(start_vel + t * (end_vel - start_vel) + 0.5)
        if nv < 1 then nv = 1; clamped = clamped + 1
        elseif nv > 127 then nv = 127; clamped = clamped + 1 end
        if nv ~= n.vel then
            changes[#changes + 1] = {index = n.index, new_vel = nv}
            notes_changed = notes_changed + 1
        end
    end
    return {changes = changes, notes_changed = notes_changed, clamped = clamped}
end

-- scale velocities: multiply / set / compress(-toward-pivot). compress ratio in [0,1] is a
-- convex blend (never clamps); set is validated (never clamps); only multiply can clamp [1,127].
-- pivot -1 (compress) = rounded mean of the filtered originals (once, order-independent).
local function compute_scaled_velocities(notes, opts, filt, ctx)
    local matched = {}
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then matched[#matched + 1] = n end
    end
    local pivot_used = opts.pivot
    if opts.mode == "compress" and opts.pivot == -1 then
        if #matched == 0 then
            pivot_used = -1
        else
            local sum = 0
            for _, n in ipairs(matched) do sum = sum + n.vel end
            pivot_used = math.floor(sum / #matched + 0.5)
        end
    end
    local out, notes_changed, clamped = {}, 0, 0
    for _, n in ipairs(matched) do
        local raw
        if opts.mode == "multiply" then
            raw = n.vel * opts.ratio
        elseif opts.mode == "set" then
            raw = opts.value
        else
            raw = pivot_used + (n.vel - pivot_used) * opts.ratio
        end
        local rounded = math.floor(raw + 0.5)
        local final = math.max(1, math.min(127, rounded))
        if final ~= rounded then clamped = clamped + 1 end
        local changed = final ~= n.vel
        if changed then notes_changed = notes_changed + 1 end
        out[#out + 1] = {index = n.index, new_vel = final, changed = changed}
    end
    return out, {notes_changed = notes_changed, clamped = clamped, pivot_used = pivot_used}
end

-- strum: group eligible notes into chords by onset (within chord_window_ppq), then stagger each
-- chord's onsets over spread_ppq (up = lowest first, down = highest first). Whole-note shift; length
-- preserved. D9 (invents no pitches). Only delays -> past-item-end counted (never before-start).
local function strum_notes_pure(notes, opts, filt, ctx)
    local elig = {}
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then elig[#elig + 1] = n end
    end
    table.sort(elig, function(a, b)
        if a.startppq ~= b.startppq then return a.startppq < b.startppq end
        return a.index < b.index
    end)
    local changes, notes_changed, out_of_bounds = {}, 0, 0
    local i = 1
    while i <= #elig do
        local anchor = elig[i].startppq
        local group, j = {}, i
        while j <= #elig and (elig[j].startppq - anchor) <= opts.chord_window_ppq do
            group[#group + 1] = elig[j]; j = j + 1
        end
        if #group >= 2 and opts.spread_ppq > 0 then
            table.sort(group, function(a, b)
                if a.pitch ~= b.pitch then return a.pitch < b.pitch end
                if a.chan ~= b.chan then return a.chan < b.chan end
                return a.index < b.index
            end)
            if opts.direction == "down" then
                local rev = {}
                for k = #group, 1, -1 do rev[#rev + 1] = group[k] end
                group = rev
            end
            local step = opts.spread_ppq / (#group - 1)
            for k, n in ipairs(group) do
                local ns = math.floor(anchor + (k - 1) * step + 0.5)
                local ne = ns + (n.endppq - n.startppq)
                if ns ~= n.startppq then
                    changes[#changes + 1] = {index = n.index, new_start = ns, new_end = ne}
                    notes_changed = notes_changed + 1
                end
                if ns < ctx.item_start_ppq or ne > ctx.item_end_ppq then
                    out_of_bounds = out_of_bounds + 1
                end
            end
        end
        i = j
    end
    return {changes = changes, notes_changed = notes_changed, out_of_bounds = out_of_bounds}
end

-- snap-to-scale seams -----------------------------------------------------
-- Named scales as intervals-from-root in semitones. A custom interval list arrives in this
-- same shape, so named and custom modes take one identical code path.
local MODE_INTERVALS = {
    major            = {0, 2, 4, 5, 7, 9, 11},
    minor            = {0, 2, 3, 5, 7, 8, 10},
    harmonic_minor   = {0, 2, 3, 5, 7, 8, 11},
    melodic_minor    = {0, 2, 3, 5, 7, 9, 11},
    dorian           = {0, 2, 3, 5, 7, 9, 10},
    phrygian         = {0, 1, 3, 5, 7, 8, 10},
    lydian           = {0, 2, 4, 6, 7, 9, 11},
    mixolydian       = {0, 2, 4, 5, 7, 9, 10},
    locrian          = {0, 1, 3, 5, 6, 8, 10},
    major_pentatonic = {0, 2, 4, 7, 9},
    minor_pentatonic = {0, 3, 5, 7, 10},
    blues            = {0, 3, 5, 6, 7, 10},
    whole_tone       = {0, 2, 4, 6, 8, 10},
    chromatic        = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11},
}
MODE_INTERVALS.ionian = MODE_INTERVALS.major
MODE_INTERVALS.aeolian = MODE_INTERVALS.minor
MODE_INTERVALS.natural_minor = MODE_INTERVALS.minor

-- The scale as a pitch-class set (semantically REAPER's (root, 12-bit mask), held as a plain
-- set so the seam stays Lua-version-agnostic — no bitwise ops, which the golden-test runtime
-- may not have). Nothing is sent to MIDI_SetScale: snap has no highlight side effect.
local function scale_pitch_classes(root, intervals)
    local pcs = {}
    for _, i in ipairs(intervals) do pcs[(root + i) % 12] = true end
    return pcs
end

-- mode arg -> interval list. A custom list rides through as-is; a name resolves via
-- MODE_INTERVALS (case-insensitive). nil = unknown name; the handler turns that into an error.
local function resolve_mode_intervals(mode)
    if type(mode) == "table" then return mode end
    return MODE_INTERVALS[tostring(mode):lower()]
end

-- Nearest in-scale pitch from p searching in dir (1 = up, -1 = down), or nil when the closest
-- in-scale pitch class lands outside MIDI 0-127 — every candidate beyond it is further out, so
-- there is no legal target this way (D3 skip; no cross-direction fallback). A non-empty scale
-- always has a member within 11 semitones of an off-scale pitch, so the bounded loop suffices.
local function nearest_in_scale(p, scale_pcs, dir)
    for d = 1, 11 do
        local t = p + dir * d
        if scale_pcs[t % 12] then
            if t >= 0 and t <= 127 then return t end
            return nil
        end
    end
    return nil
end

-- snap: pitch-only, count-preserving. Each off-scale filtered note moves to the nearest
-- in-scale pitch (up / down / nearest). `nearest` breaks a tie TOWARD the filtered mean (D4:
-- above the mean -> down, below -> up, exactly on it -> down). No legal target -> skip (D3).
-- In-scale notes are untouched; same-pitch collisions are left to remove_overlapping (D6).
local function snap_notes_to_scale_pure(notes, filt, ctx, scale_pcs, direction)
    local matched = {}
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then matched[#matched + 1] = n end
    end
    -- mean of the ORIGINAL pitches of the WHOLE filtered subset, once (order-independent)
    local mean = 0
    if #matched > 0 then
        local sum = 0
        for _, n in ipairs(matched) do sum = sum + n.pitch end
        mean = sum / #matched
    end
    local changes, notes_changed, skipped = {}, 0, 0
    for _, n in ipairs(matched) do
        if not scale_pcs[n.pitch % 12] then
            local up_t = nearest_in_scale(n.pitch, scale_pcs, 1)
            local down_t = nearest_in_scale(n.pitch, scale_pcs, -1)
            local target
            if direction == "up" then
                target = up_t
            elseif direction == "down" then
                target = down_t
            elseif up_t and down_t then
                local du, dd = up_t - n.pitch, n.pitch - down_t
                if du < dd then
                    target = up_t
                elseif dd < du then
                    target = down_t
                else
                    target = (n.pitch < mean) and up_t or down_t   -- tie -> toward the mean [D4]
                end
            else
                target = up_t or down_t                            -- nearest, only one legal side
            end
            if target then                                         -- always differs from n.pitch
                changes[#changes + 1] = {index = n.index, new_pitch = target}
                notes_changed = notes_changed + 1
            else
                skipped = skipped + 1
            end
        end
    end
    return {changes = changes, notes_changed = notes_changed, skipped = skipped}
end

-- quantize: snap targeted onsets to the PROJECT bar/beat grid [D11] — origin project QN 0,
-- spacing `grid` QN. Deliberately NOT item-relative: a producer's onsets land on project bars,
-- while the value filter and the returned beats stay item-anchored. All math is in QN, so it is
-- tempo-safe (no seconds, no hardcoded PPQ); the handler hands each note its project `qn` and
-- `len_qn`, membership still runs on PPQ via note_in_filter.
-- Swing [D5] delays ODD grid cells only (cell parity from the STRAIGHT grid, MPC-style).
-- [D10] a note snapped before the item start is clamped to it (REAPER refuses anything earlier)
-- and counted; a note pushed past the item end is allowed as-is and counted. Length preserved.
local function quantize_notes(notes, grid, strength, swing, filt, ctx)
    local changes, notes_changed, out_of_bounds = {}, 0, 0
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then
            local k = math.floor(n.qn / grid + 0.5)          -- nearest straight cell (k<0 before QN 0)
            local swing_delay = (k % 2 == 1) and (swing * grid / 3) or 0
            local target = k * grid + swing_delay
            local new_qn = n.qn + strength * (target - n.qn)  -- strength blend, in QN
            local oob, at_item_start = false, false
            if new_qn < ctx.item_start_qn then
                new_qn = ctx.item_start_qn
                oob, at_item_start = true, true
            end
            local new_end_qn = new_qn + n.len_qn              -- length preserved in QN
            local moved = new_qn ~= n.qn
            if moved and new_end_qn > ctx.item_end_qn then oob = true end
            if moved then
                changes[#changes + 1] = {index = n.index, new_qn = new_qn,
                                         new_end_qn = new_end_qn, at_item_start = at_item_start}
                notes_changed = notes_changed + 1
            end
            if oob then out_of_bounds = out_of_bounds + 1 end
        end
    end
    return {changes = changes, notes_changed = notes_changed, out_of_bounds = out_of_bounds}
end

-- stretch: scale each targeted note as a rigid unit about ONE fixed pivot — onset-offset AND
-- length scale by `factor`. Pivot is `pivot_ppq` when given, else the earliest onset among the
-- TARGETED notes (fixed once, so the group scales coherently). Pure PPQ, so tempo-independent;
-- only the caller's beat->PPQ conversion of pivot/window touches ppq_per_qn.
-- [D10] past item end: allowed as-is + counted. Before item start: REAPER refuses it, so the
-- start clamps to item_start_ppq while the scaled end STAYS PUT — the note comes out shorter
-- (Dave's call 2026-07-16, option (a): every end stays faithful to the scaling). Order is
-- clamp-then-floor: a clamp can shorten a note toward zero, and a note whose whole scaled span
-- lands before the item start would otherwise end up with new_end < new_start, so the 1-tick
-- min length runs last and turns that into a legal 1-tick note at the item start.
-- out_of_bounds counts the RAW scaled position — where the scaling put the note, not where it
-- was legalised to.
local function stretch_notes(notes, factor, pivot_ppq, filt, ctx)
    local targeted = {}
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then targeted[#targeted + 1] = n end
    end
    local pivot = pivot_ppq
    if not pivot then
        for _, n in ipairs(targeted) do
            if not pivot or n.startppq < pivot then pivot = n.startppq end
        end
    end
    local changes, notes_changed, out_of_bounds = {}, 0, 0
    if pivot then
        for _, n in ipairs(targeted) do
            local raw_s = math.floor(pivot + (n.startppq - pivot) * factor + 0.5)
            local raw_e = math.floor(pivot + (n.endppq - pivot) * factor + 0.5)
            if raw_s < ctx.item_start_ppq or raw_e > ctx.item_end_ppq then   -- judged on RAW
                out_of_bounds = out_of_bounds + 1
            end
            local ns = raw_s
            if ns < ctx.item_start_ppq then ns = ctx.item_start_ppq end      -- clamp first...
            local ne = raw_e                                                 -- scaled end stays put
            if ne < ns + 1 then ne = ns + 1 end                              -- ...then floor length
            if ns ~= n.startppq or ne ~= n.endppq then
                changes[#changes + 1] = {index = n.index, new_start = ns, new_end = ne}
                notes_changed = notes_changed + 1
            end
        end
    end
    return {changes = changes, notes_changed = notes_changed, out_of_bounds = out_of_bounds}
end

-- legato: close the gaps in a line. ONLY ends move, never starts — so unlike the other timing
-- transforms there is no before-item-start case to clamp; only past-item-end, which D10 allows.
--   connect (extend-only): each targeted note's end runs forward to the next relevant onset.
--     `chordal` takes the next DISTINCT onset among the targeted set (so a chord's notes all
--     extend to the next chord together); `per_pitch` takes the next onset of the same
--     (channel, pitch), which keeps interleaved voices independent.
--     A note that already reaches or overruns its next onset (gap <= 0) is left ALONE — legato
--     never trims, and the overlap is remove_overlapping's job (D6). A gap wider than
--     max_gap_ppq is a rest the player meant: left alone and counted in gaps_preserved.
--     The last note (no next onset) is left alone.
--   fixed: every targeted note's length is set to length_ppq, last one included; voice,
--     max_gap and the extend-only rule do not apply.
-- Anchors come from the TARGETED set only, so a targeted note may extend straight through an
-- untargeted one.
local function legato_pure(notes, opts, filt, ctx)
    local targeted = {}
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then targeted[#targeted + 1] = n end
    end
    local changes, notes_changed, gaps_preserved, out_of_bounds = {}, 0, 0, 0
    for _, n in ipairs(targeted) do
        local new_end
        if opts.mode == "fixed" then
            new_end = n.startppq + opts.length_ppq
        else
            local nxt
            for _, m in ipairs(targeted) do
                -- strictly later onsets only, so chord-mates never anchor each other
                if m.startppq > n.startppq
                   and (opts.voice ~= "per_pitch" or (m.pitch == n.pitch and m.chan == n.chan))
                   and (not nxt or m.startppq < nxt) then
                    nxt = m.startppq
                end
            end
            if nxt then
                local gap = nxt - n.endppq
                if gap > 0 then                          -- gap <= 0: already reaches -> never trim
                    if gap <= opts.max_gap_ppq then      -- inclusive: a gap exactly at the ceiling closes
                        new_end = nxt
                    else
                        gaps_preserved = gaps_preserved + 1
                    end
                end
            end
        end
        if new_end and new_end ~= n.endppq then
            changes[#changes + 1] = {index = n.index, new_end = new_end}
            notes_changed = notes_changed + 1
            if new_end > ctx.item_end_ppq then out_of_bounds = out_of_bounds + 1 end
        end
    end
    return {changes = changes, notes_changed = notes_changed,
            gaps_preserved = gaps_preserved, out_of_bounds = out_of_bounds}
end

-- humanize: apply PRE-DRAWN per-note offsets. The bridge rolls no dice (D8) — Python owns the
-- seeded RNG, so a run is reproducible. Offsets are keyed by ABSOLUTE note index (0-based here,
-- so 1-based in the Lua arrays), which is why filtered-out notes still consume a draw upstream:
-- the seed -> note mapping must not shift when the filter changes.
-- Start AND end move by the same delta, so length is preserved. That is precisely the bug in
-- the orphan Step 0 deleted: it clamped the start and left the end, silently restretching notes.
-- [D10] past item end: allowed as-is + counted. Before item start: REAPER refuses it, so clamp
-- to item_start_ppq (length still preserved) + count. Clamping is counted even when the note
-- ends up where it began (a note already at the item start with a negative draw), because the
-- transform did try to put it outside. A past-end note is only counted if this run moved it.
-- Velocity clamps to [1,127] — floor 1, never 0 (a humanized note must not go silent).
local function humanize_midi_notes_pure(notes, filt, ctx, toff_ppq, voff)
    local out, notes_changed, clamped, out_of_bounds = {}, 0, 0, 0
    for _, n in ipairs(notes) do
        if note_in_filter(n, filt, ctx) then
            local dt = toff_ppq[n.index + 1] or 0
            local vo = voff[n.index + 1] or 0
            local oob = false
            local ns = n.startppq + dt
            if ns < ctx.item_start_ppq then
                ns = ctx.item_start_ppq
                oob = true
            end
            local ne = ns + (n.endppq - n.startppq)            -- length preserved
            if dt ~= 0 and ne > ctx.item_end_ppq then oob = true end
            local timing_changed = ns ~= n.startppq
            local raw_vel = math.floor(n.vel + vo + 0.5)
            local nv = math.max(1, math.min(127, raw_vel))
            if nv ~= raw_vel then clamped = clamped + 1 end
            local vel_changed = nv ~= n.vel
            if timing_changed or vel_changed then
                notes_changed = notes_changed + 1
                out[#out + 1] = {index = n.index, timing_changed = timing_changed,
                                 vel_changed = vel_changed,
                                 new_start = ns, new_end = ne, new_vel = nv}
            end
            if oob then out_of_bounds = out_of_bounds + 1 end
        end
    end
    return out, {notes_changed = notes_changed, clamped = clamped,
                 skipped = 0, out_of_bounds = out_of_bounds}
end

-- remove_overlapping: the family's only COUNT-CHANGING tool — the only one that can destroy
-- musical content rather than move it, so the rules are deliberately conservative.
-- Two notes overlap only if they share a pitch AND a channel AND their spans strictly
-- intersect. Half-open: A.end == B.start is ABUTTING, not overlapping, which is what makes a
-- trim run idempotent. A chord (same onset, different pitch) is never an overlap; neither is
-- the same pitch on two channels.
-- `notes` here is ALREADY scoped by the caller's filter: an out-of-scope note is invisible —
-- never edited, never deleted, and never a partner that could cause someone else's deletion.
--   dedupe (both modes): notes sharing an onset collapse to one — highest velocity, tie to the
--     longest, tie to the lowest index. Runs first because trimming to a same-onset neighbour
--     would otherwise produce a zero-length note.
--   trim: each note's end pulls back to the next onset (one pass, off ORIGINAL onsets). If that
--     would leave it shorter than min_length_ppq it is removed instead — counted as deduped,
--     not trimmed, since nothing was left to trim.
--   delete: a greedy sweep drops the loser of each overlap (lower velocity, tie to the shorter,
--     tie to the higher index); the survivor's timing is never touched.
-- Returns edits sorted by index and removals sorted DESCENDING: MIDI_DeleteNote shifts every
-- higher index down, so deleting ascending would silently delete the wrong notes.
local function remove_overlaps_pure(notes, opts)
    local groups, order = {}, {}
    for _, n in ipairs(notes) do
        local key = n.pitch .. ":" .. n.chan
        if not groups[key] then groups[key] = {}; order[#order + 1] = key end
        local g = groups[key]
        g[#g + 1] = n
    end
    table.sort(order)                      -- pairs() order is undefined; keep output stable
    local edits, removals = {}, {}
    local trimmed, deduped, deleted = 0, 0, 0
    -- true when `a` should survive against `b`: higher velocity, then longer, then lower index
    local function beats(a, b)
        if a.vel ~= b.vel then return a.vel > b.vel end
        local la, lb = a.endppq - a.startppq, b.endppq - b.startppq
        if la ~= lb then return la > lb end
        return a.index < b.index
    end
    for _, key in ipairs(order) do
        local g = groups[key]
        table.sort(g, function(a, b)
            if a.startppq ~= b.startppq then return a.startppq < b.startppq end
            return a.index < b.index
        end)
        -- (1) dedupe: collapse each identical-onset run to its best note
        local kept = {}
        local i = 1
        while i <= #g do
            local j = i
            while j < #g and g[j + 1].startppq == g[i].startppq do j = j + 1 end
            local best = g[i]
            for k = i + 1, j do
                if beats(g[k], best) then best = g[k] end
            end
            for k = i, j do
                if g[k] ~= best then
                    removals[#removals + 1] = g[k].index
                    deduped = deduped + 1
                end
            end
            kept[#kept + 1] = best
            i = j + 1
        end
        if opts.mode == "trim" then
            -- (2a) pull each end back to the next onset; min_length_ppq 0 disables the floor
            -- naturally (a strict overlap always leaves a positive length)
            for k = 1, #kept - 1 do
                local a, b = kept[k], kept[k + 1]
                if a.endppq > b.startppq then
                    if (b.startppq - a.startppq) < opts.min_length_ppq then
                        removals[#removals + 1] = a.index
                        deduped = deduped + 1
                    else
                        edits[#edits + 1] = {index = a.index, new_end = b.startppq}
                        trimmed = trimmed + 1
                    end
                end
            end
        else
            -- (2b) greedy sweep: the loser of each overlap goes, the survivor is left alone
            local active
            for k = 1, #kept do
                local n = kept[k]
                if active and active.endppq > n.startppq then
                    local winner = beats(active, n) and active or n
                    local loser = (winner == active) and n or active
                    removals[#removals + 1] = loser.index
                    deleted = deleted + 1
                    active = winner
                else
                    active = n
                end
            end
        end
    end
    table.sort(edits, function(a, b) return a.index < b.index end)
    table.sort(removals, function(a, b) return a > b end)   -- DESCENDING; see note above
    return {edits = edits, removals = removals,
            trimmed = trimmed, deduped = deduped, deleted = deleted}
end
-- === MIDI_PURE_END ===

-- Impure helpers (need reaper.*): read notes, derive ctx, build the response note list.
local function midi_read_notes(take)
    local _, count = reaper.MIDI_CountEvts(take)
    local out = {}
    for n = 0, count - 1 do
        local ok, sel, mut, sppq, eppq, chan, pitch, vel = reaper.MIDI_GetNote(take, n)
        if ok then
            out[#out + 1] = {index = n, startppq = sppq, endppq = eppq,
                             chan = chan, pitch = pitch, vel = vel, selected = sel, muted = mut}
        end
    end
    return out
end

-- ctx for filter/timing math; ppq_per_qn is a fixed property of the take (tempo-map-safe).
local function midi_ctx(take, item)
    local ppq_per_qn = reaper.MIDI_GetPPQPosFromProjQN(take, 1) - reaper.MIDI_GetPPQPosFromProjQN(take, 0)
    local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
    local start_ppq = reaper.MIDI_GetPPQPosFromProjTime(take, item_pos)
    local end_ppq = reaper.MIDI_GetPPQPosFromProjTime(take, item_pos + item_len)
    return {
        ppq_per_qn = ppq_per_qn,
        item_start_ppq = start_ppq,
        item_end_ppq = end_ppq,
        -- QN bounds for the QN-native transforms (quantize): comparing in QN keeps the
        -- item-edge tests on the same tempo-safe axis the grid math runs on.
        item_start_qn = reaper.MIDI_GetProjQNFromPPQPos(take, start_ppq),
        item_end_qn = reaper.MIDI_GetProjQNFromPPQPos(take, end_ppq),
    }
end

-- The ONE shared response note-dict builder (contract [H]): seconds for back-compat +
-- item-relative start_beat/end_beat (tempo-safe) so output feeds the beat filter exactly.
local function midi_note_list(take, item)
    local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local item_start_qn = reaper.MIDI_GetProjQNFromPPQPos(take, reaper.MIDI_GetPPQPosFromProjTime(take, item_pos))
    local _, count = reaper.MIDI_CountEvts(take)
    local notes = as_array({})
    for n = 0, count - 1 do
        local ok, sel, mut, sppq, eppq, chan, pitch, vel = reaper.MIDI_GetNote(take, n)
        if ok then
            notes[#notes + 1] = {
                index = n, pitch = pitch, velocity = vel, channel = chan,
                selected = sel, muted = mut,
                start_time = reaper.MIDI_GetProjTimeFromPPQPos(take, sppq),
                end_time = reaper.MIDI_GetProjTimeFromPPQPos(take, eppq),
                start_beat = reaper.MIDI_GetProjQNFromPPQPos(take, sppq) - item_start_qn,
                end_beat = reaper.MIDI_GetProjQNFromPPQPos(take, eppq) - item_start_qn,
            }
        end
    end
    return notes, count
end

-- Expose the pure seams for headless golden tests.
_G.__MIDI_TEST = {note_in_filter = note_in_filter, transpose_notes_pure = transpose_notes_pure,
                  nudge_notes_pure = nudge_notes_pure, filter_selected = filter_selected,
                  compute_note_span = compute_note_span, beats_to_take_ppq = beats_to_take_ppq,
                  len_beats_to_ppq = len_beats_to_ppq, note_out_of_bounds = note_out_of_bounds,
                  valid_pitch = valid_pitch, valid_channel = valid_channel, valid_length = valid_length,
                  midi_ramp_velocities = midi_ramp_velocities,
                  compute_scaled_velocities = compute_scaled_velocities, strum_notes_pure = strum_notes_pure,
                  scale_pitch_classes = scale_pitch_classes, resolve_mode_intervals = resolve_mode_intervals,
                  nearest_in_scale = nearest_in_scale, snap_notes_to_scale_pure = snap_notes_to_scale_pure,
                  quantize_notes = quantize_notes, stretch_notes = stretch_notes,
                  legato_pure = legato_pure, humanize_midi_notes_pure = humanize_midi_notes_pure,
                  remove_overlaps_pure = remove_overlaps_pure}
-- ========================================================================

-- Main processing function
local function process_request()
    -- Look for any request files with numbered pattern
    for i = 1, 1000 do
        local numbered_request_file = bridge_dir .. 'request_' .. i .. '.json'
        local numbered_response_file = bridge_dir .. 'response_' .. i .. '.json'
        
        if file_exists(numbered_request_file) then
            -- Wrap in pcall to catch any errors
            local ok, err = pcall(function()
                -- Read and process request
                local request_data = read_file(numbered_request_file)
                if request_data then
                    reaper.ShowConsoleMsg("Processing request " .. i .. ": " .. request_data .. "\n")
                    
                    -- Parse the request
                    local request = decode_json(request_data)
                    if request and request.func then
                        local fname = request.func
                        local args = request.args or {}
                    
                    -- Call the REAPER function
                    local response = {ok = false}
                    
                    -- Handle all API functions
                                        if DSL_FUNCTIONS[fname] then
                        local result = DSL_FUNCTIONS[fname](table.unpack(args))
                        -- Copy all fields from result to response
                        for k, v in pairs(result) do
                            response[k] = v
                        end
                    
                    elseif fname == "InsertTrackAtIndex" then
                        if #args >= 2 then
                            reaper.InsertTrackAtIndex(args[1], args[2])
                            response.ok = true
                        else
                            response.error = "InsertTrackAtIndex requires 2 arguments"
                        end
                    
                    elseif fname == "CountTracks" then
                        local count = reaper.CountTracks(args[1] or 0)
                        response.ok = true
                        response.ret = count
                    
                    elseif fname == "GetAppVersion" then
                        local version = reaper.GetAppVersion()
                        response.ok = true
                        response.ret = version
                    
                    elseif fname == "GetTrack" then
                        if #args >= 2 then
                            local track = reaper.GetTrack(args[1], args[2])
                            response.ok = true
                            response.ret = track
                        else
                            response.error = "GetTrack requires 2 arguments"
                        end
                    
                    elseif fname == "CreateTrackSend" then
                        -- Create a send between two tracks
                        if #args >= 2 then
                            local src_track = nil
                            local dest_track = nil
                            
                            -- Handle source track
                            if type(args[1]) == "number" then
                                src_track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use source track pointer from previous call - use track index instead"
                                response.ok = false
                            elseif type(args[1]) == "userdata" then
                                src_track = args[1]
                            end
                            
                            -- Handle destination track
                            if src_track and type(args[2]) == "number" then
                                dest_track = reaper.GetTrack(0, args[2])
                            elseif src_track and type(args[2]) == "table" and args[2].__ptr then
                                response.error = "Cannot use destination track pointer from previous call - use track index instead"
                                response.ok = false
                                src_track = nil  -- Clear to prevent partial operation
                            elseif src_track and type(args[2]) == "userdata" then
                                dest_track = args[2]
                            end
                            
                            if src_track and dest_track then
                                local send_idx = reaper.CreateTrackSend(src_track, dest_track)
                                response.ok = true
                                response.ret = send_idx
                            elseif not src_track then
                                if not response.error then
                                    response.error = "Source track not found"
                                end
                                response.ok = false
                            else
                                if not response.error then
                                    response.error = "Destination track not found"
                                end
                                response.ok = false
                            end
                        else
                            response.error = "CreateTrackSend requires 2 arguments (source_track, dest_track)"
                            response.ok = false
                        end
                    
                    elseif fname == "SetTrackSendUIVol" then
                        -- Set track send UI volume
                        if #args >= 4 then
                            local track = nil
                            
                            -- Handle track parameter
                            if type(args[1]) == "number" then
                                track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                            elseif type(args[1]) == "userdata" then
                                track = args[1]
                            end
                            
                            if track then
                                local send_idx = args[2]
                                local volume = args[3]
                                local relative = args[4]
                                
                                local result = reaper.SetTrackSendUIVol(track, send_idx, volume, relative)
                                response.ok = true
                                response.ret = result
                            else
                                if not response.error then
                                    response.error = "Track not found"
                                end
                                response.ok = false
                            end
                        else
                            response.error = "SetTrackSendUIVol requires 4 arguments (track, send_index, volume, relative)"
                            response.ok = false
                        end
                    
                    elseif fname == "SetTrackSendUIPan" then
                        -- Set track send UI pan
                        if #args >= 4 then
                            local track = nil
                            
                            -- Handle track parameter
                            if type(args[1]) == "number" then
                                track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                            elseif type(args[1]) == "userdata" then
                                track = args[1]
                            end
                            
                            if track then
                                local send_idx = args[2]
                                local pan = args[3]
                                local relative = args[4]
                                
                                local result = reaper.SetTrackSendUIPan(track, send_idx, pan, relative)
                                response.ok = true
                                response.ret = result
                            else
                                if not response.error then
                                    response.error = "Track not found"
                                end
                                response.ok = false
                            end
                        else
                            response.error = "SetTrackSendUIPan requires 4 arguments (track, send_index, pan, relative)"
                            response.ok = false
                        end
                    
                    elseif fname == "SetTrackSendInfo_Value" then
                        -- Set track send info value
                        if #args >= 5 then
                            local track = nil
                            
                            -- Handle track parameter
                            if type(args[1]) == "number" then
                                track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                            elseif type(args[1]) == "userdata" then
                                track = args[1]
                            end
                            
                            if track then
                                local category = args[2]
                                local send_idx = args[3]
                                local param_name = args[4]
                                local value = args[5]
                                
                                local result = reaper.SetTrackSendInfo_Value(track, category, send_idx, param_name, value)
                                response.ok = true
                                response.ret = result
                            else
                                if not response.error then
                                    response.error = "Track not found"
                                end
                                response.ok = false
                            end
                        else
                            response.error = "SetTrackSendInfo_Value requires 5 arguments (track, category, send_index, param_name, value)"
                            response.ok = false
                        end

                    elseif fname == "RemoveTrackSend" then
                        -- Remove a track send
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                track = reaper.GetTrack(0, args[1])
                            end
                            if track then
                                local category = args[2]
                                local send_idx = args[3]
                                local result = reaper.RemoveTrackSend(track, category, send_idx)
                                response.ok = result
                                response.ret = result
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "RemoveTrackSend requires 3 arguments (track_index, category, send_index)"
                            response.ok = false
                        end

                    elseif fname == "GetTrackNumSends" then
                        -- Get number of sends from a track
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                track = reaper.GetTrack(0, args[1])
                            end
                            if track then
                                local category = args[2]
                                local result = reaper.GetTrackNumSends(track, category)
                                response.ok = true
                                response.ret = result
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "GetTrackNumSends requires 2 arguments (track_index, category)"
                            response.ok = false
                        end

                    elseif fname == "GetFXChunk" then
                        -- Get FX state chunk (for reading VSTi state like EZkeys)
                        if #args >= 2 then
                            local track = nil
                            local track_index = args[1]
                            local fx_index = args[2]

                            if track_index == -1 then
                                track = reaper.GetMasterTrack(0)
                            else
                                track = reaper.GetTrack(0, track_index)
                            end

                            if track then
                                -- Get the full track state chunk
                                local retval, chunk = reaper.GetTrackStateChunk(track, "", false)
                                if retval and chunk then
                                    -- Parse out the specific FX chunk
                                    -- FX are in <FXCHAIN> section, each FX starts with <VST or <JS etc
                                    local fx_count = 0
                                    local in_fxchain = false
                                    local fx_start = nil
                                    local bracket_depth = 0
                                    local fx_chunk = nil

                                    -- Find the FX chain section
                                    local fxchain_start = chunk:find("<FXCHAIN")
                                    if fxchain_start then
                                        local fxchain_section = chunk:sub(fxchain_start)

                                        -- Find all FX entries (VST, VST3, JS, etc)
                                        local pos = 1
                                        local current_fx = -1

                                        while true do
                                            -- Look for FX start markers
                                            local vst_pos = fxchain_section:find("\n%s*<VST[^>]*>", pos)
                                            local vst3_pos = fxchain_section:find("\n%s*<VST3[^>]*>", pos)
                                            local js_pos = fxchain_section:find("\n%s*<JS[^>]*>", pos)

                                            -- Find earliest match
                                            local next_fx = nil
                                            local next_pos = nil

                                            if vst_pos and (not next_pos or vst_pos < next_pos) then
                                                next_pos = vst_pos
                                            end
                                            if vst3_pos and (not next_pos or vst3_pos < next_pos) then
                                                next_pos = vst3_pos
                                            end
                                            if js_pos and (not next_pos or js_pos < next_pos) then
                                                next_pos = js_pos
                                            end

                                            if not next_pos then break end

                                            current_fx = current_fx + 1

                                            if current_fx == fx_index then
                                                -- Found the target FX, extract its chunk
                                                -- Find the matching closing >
                                                local depth = 1
                                                local i = next_pos + 1
                                                -- Skip to first <
                                                while i <= #fxchain_section and fxchain_section:sub(i, i) ~= "<" do
                                                    i = i + 1
                                                end
                                                local fx_chunk_start = i
                                                i = i + 1

                                                while i <= #fxchain_section and depth > 0 do
                                                    local c = fxchain_section:sub(i, i)
                                                    if c == "<" then
                                                        depth = depth + 1
                                                    elseif c == ">" then
                                                        depth = depth - 1
                                                    end
                                                    i = i + 1
                                                end

                                                fx_chunk = fxchain_section:sub(fx_chunk_start, i - 1)
                                                break
                                            end

                                            pos = next_pos + 1
                                        end

                                        if fx_chunk then
                                            response.ok = true
                                            response.chunk = fx_chunk
                                            response.fx_index = fx_index
                                        else
                                            response.ok = false
                                            response.error = "FX not found at index " .. tostring(fx_index)
                                        end
                                    else
                                        response.ok = false
                                        response.error = "No FX chain found on track"
                                    end
                                else
                                    response.ok = false
                                    response.error = "Could not get track state chunk"
                                end
                            else
                                response.ok = false
                                response.error = "Track not found"
                            end
                        else
                            response.error = "GetFXChunk requires 2 arguments (track_index, fx_index)"
                            response.ok = false
                        end

                    elseif fname == "InsertEnvelopePoint" then
                        -- Insert envelope point.
                        -- Primary convention (what the server sends):
                        --   (track_index, envelope_name, time, value, shape, tension, selected, noSort)
                        -- Legacy convention kept for compatibility: (envelope_userdata, time, value, ...)
                        if type(args[1]) == "number" and type(args[2]) == "string" then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                local result = reaper.InsertEnvelopePoint(
                                    env, args[3], args[4], args[5] or 0, args[6] or 0,
                                    args[7] and true or false, false)
                                reaper.Envelope_SortPoints(env)
                                reaper.UpdateArrange()
                                response.ok = result and true or false
                                response.ret = result
                                if not result then response.error = "InsertEnvelopePoint failed" end
                            else
                                response.error = err
                                response.ok = false
                            end
                        elseif type(args[1]) == "userdata" and #args >= 7 then
                            local result = reaper.InsertEnvelopePoint(
                                args[1], args[2], args[3], args[4], args[5], args[6], args[7])
                            response.ok = result
                            response.ret = result
                        else
                            response.error = "InsertEnvelopePoint requires (track_index, envelope_name, time, value, shape)"
                            response.ok = false
                        end
                    
                    elseif fname == "SetTrackSelected" then
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            if track then
                                reaper.SetTrackSelected(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                            end
                        else
                            response.error = "SetTrackSelected requires 2 arguments"
                        end
                    
                    elseif fname == "GetTrackName" then
                        if #args >= 1 then
                            local track = args[1]
                            -- Handle track index or pointer object
                            if type(args[1]) == "number" then
                                -- It's a track index
                                if args[1] == -1 then
                                    -- Special case for master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                                if not track then
                                    response.error = "Track not found at index " .. tostring(args[1])
                                    response.ok = false
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer object - we can't use it
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                                track = nil
                            elseif type(args[1]) == "userdata" then
                                -- It's already a track object
                                track = args[1]
                            end
                            
                            if track then
                                local retval, name = reaper.GetTrackName(track)
                                response.ok = true
                                response.ret = name
                            end
                        else
                            response.error = "GetTrackName requires 1 argument"
                        end
                    
                    elseif fname == "SetTrackName" then
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            if track then
                                reaper.GetSetMediaTrackInfo_String(track, "P_NAME", args[2], true)
                                response.ok = true
                            else
                                response.error = "Track not found"
                            end
                        else
                            response.error = "SetTrackName requires 2 arguments"
                        end
                    
                    elseif fname == "GetMasterTrack" then
                        local track = reaper.GetMasterTrack(args[1] or 0)
                        response.ok = true
                        response.ret = track
                    
                    elseif fname == "DeleteTrack" then
                        if args[1] then
                            -- Check if it's a track index or a pointer object
                            local track = nil
                            if type(args[1]) == "number" then
                                -- It's a track index
                                track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer object - we can't use it directly
                                -- For now, return an error
                                response.error = "Cannot use track pointer from previous call - use DeleteTrackByIndex instead"
                                response.ok = false
                            else
                                track = args[1]  -- Assume it's already a track
                            end
                            
                            if track then
                                reaper.DeleteTrack(track)
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "DeleteTrack requires track pointer or index"
                        end
                    
                    elseif fname == "DeleteTrackByIndex" then
                        if args[1] then
                            local track = reaper.GetTrack(0, args[1])
                            if track then
                                reaper.DeleteTrack(track)
                                response.ok = true
                            else
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            end
                        else
                            response.error = "DeleteTrackByIndex requires track index"
                        end
                    
                    elseif fname == "GetMediaTrackInfo_Value" then
                        if #args >= 2 then
                            local track = args[1]
                            -- Handle track index or pointer object
                            if type(args[1]) == "number" then
                                -- It's a track index
                                if args[1] == -1 then
                                    -- Special case for master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                                if not track then
                                    response.error = "Track not found at index " .. tostring(args[1])
                                    response.ok = false
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer object - we can't use it
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                                track = nil
                            end
                            
                            if track then
                                local value = reaper.GetMediaTrackInfo_Value(track, args[2])
                                response.ok = true
                                response.ret = value
                            end
                        else
                            response.error = "GetMediaTrackInfo_Value requires 2 arguments"
                        end
                    
                    elseif fname == "SetMediaTrackInfo_Value" then
                        if #args >= 3 then
                            local track = args[1]
                            -- Handle track index or pointer object
                            if type(args[1]) == "number" then
                                -- It's a track index
                                if args[1] == -1 then
                                    -- Special case for master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                                if not track then
                                    response.error = "Track not found at index " .. tostring(args[1])
                                    response.ok = false
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer object - we can't use it
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                                track = nil
                            end
                            
                            if track then
                                reaper.SetMediaTrackInfo_Value(track, args[2], args[3])
                                response.ok = true
                            end
                        else
                            response.error = "SetMediaTrackInfo_Value requires 3 arguments"
                        end
                    
                    elseif fname == "GetSetMediaTrackInfo_String" then
                        if #args >= 4 then
                            local track = args[1]
                            local param = args[2]
                            local newvalue = args[3]
                            local setnewvalue = args[4]
                            -- Convert string to boolean if needed
                            if type(setnewvalue) == "string" then
                                setnewvalue = (setnewvalue == "true" or setnewvalue == "1")
                            end
                            
                            -- Handle track index or pointer object
                            if type(args[1]) == "number" then
                                -- It's a track index
                                if args[1] == -1 then
                                    -- Special case for master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                                if not track then
                                    response.error = "Track not found at index " .. tostring(args[1])
                                    response.ok = false
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer object - we can't use it
                                response.error = "Cannot use track pointer from previous call - use track index instead"
                                response.ok = false
                                track = nil
                            elseif type(args[1]) == "userdata" then
                                -- It's already a track object
                                track = args[1]
                            end
                            
                            if track then
                                local ok, strval = reaper.GetSetMediaTrackInfo_String(track, param, newvalue, setnewvalue)
                                response.ok = ok
                                response.ret = strval
                            end
                        else
                            response.error = "GetSetMediaTrackInfo_String requires 4 arguments"
                        end
                    
                    elseif fname == "AddMediaItemToTrack" then
                        if args[1] then
                            local track = nil
                            -- Check if it's a track index (number) or a track object
                            if type(args[1]) == "number" then
                                -- It's a track index, get the track
                                track = reaper.GetTrack(0, args[1])
                            elseif type(args[1]) == "userdata" then
                                -- It's already a track object
                                track = args[1]
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use track pointer from previous call - bridge limitation"
                                response.ok = false
                            end
                            
                            if track then
                                local item = reaper.AddMediaItemToTrack(track)
                                response.ok = true
                                response.ret = item
                            else
                                response.error = "Invalid track parameter - provide track index or valid track object"
                                response.ok = false
                            end
                        else
                            response.error = "AddMediaItemToTrack requires track index or track object"
                        end
                    
                    elseif fname == "CountMediaItems" then
                        local count = reaper.CountMediaItems(args[1] or 0)
                        response.ok = true
                        response.ret = count
                    
                    elseif fname == "AddTakeToMediaItem" then
                        if args[1] then
                            local item = nil
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "userdata" then
                                -- It's already an item object
                                item = args[1]
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use item pointer from previous call - use item index instead"
                                response.ok = false
                            end
                            
                            if item then
                                local take = reaper.AddTakeToMediaItem(item)
                                response.ok = true
                                response.ret = take
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "AddTakeToMediaItem requires item index or item object"
                        end
                    
                    elseif fname == "GetMediaItem" then
                        if #args >= 2 then
                            local item = reaper.GetMediaItem(args[1], args[2])
                            response.ok = true
                            response.ret = item
                        else
                            response.error = "GetMediaItem requires 2 arguments"
                        end
                    
                    elseif fname == "GetMediaItemTake" then
                        if #args >= 2 then
                            local item = nil
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "userdata" then
                                -- It's already an item object
                                item = args[1]
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference
                                response.error = "Cannot use item pointer from previous call"
                                response.ok = false
                            end
                            
                            if item then
                                local take = reaper.GetMediaItemTake(item, args[2])
                                response.ok = true
                                response.ret = take
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "GetMediaItemTake requires 2 arguments"
                        end
                    
                    elseif fname == "CountTakes" then
                        if #args >= 1 then
                            local item = nil
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "userdata" then
                                -- It's already an item object
                                item = args[1]
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference
                                response.error = "Cannot use item pointer from previous call"
                                response.ok = false
                            end
                            
                            if item then
                                local count = reaper.CountTakes(item)
                                response.ok = true
                                response.ret = count
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "CountTakes requires 1 argument"
                        end
                    
                    elseif fname == "GetTrackMediaItem" then
                        if #args >= 2 then
                            local item = reaper.GetTrackMediaItem(args[1], args[2])
                            response.ok = true
                            response.ret = item
                        else
                            response.error = "GetTrackMediaItem requires 2 arguments"
                        end
                    
                    elseif fname == "DeleteTrackMediaItem" then
                        if #args >= 2 then
                            local track_index = args[1]
                            local item_index = args[2]
                            
                            -- Get track by index
                            local track
                            if track_index == -1 then
                                track = reaper.GetMasterTrack(0)
                            else
                                track = reaper.GetTrack(0, track_index)
                            end
                            
                            if not track then
                                response.error = "Track not found at index " .. tostring(track_index)
                                response.ok = false
                            else
                                -- Get item on track
                                local item = reaper.GetTrackMediaItem(track, item_index)
                                if not item then
                                    response.error = "Media item not found at index " .. tostring(item_index) .. " on track"
                                    response.ok = false
                                else
                                    -- Delete the item
                                    local result = reaper.DeleteTrackMediaItem(track, item)
                                    response.ok = result
                                end
                            end
                        else
                            response.error = "DeleteTrackMediaItem requires 2 arguments"
                        end
                    
                    elseif fname == "GetMediaItemInfo_Value" then
                        if #args >= 2 then
                            local item = args[1]
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                                if not item then
                                    response.error = "Item not found at index " .. tostring(args[1])
                                    response.ok = false
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use item pointer from previous call - use item index instead"
                                response.ok = false
                                item = nil
                            elseif type(args[1]) == "userdata" then
                                -- It's already an item object
                                item = args[1]
                            end
                            
                            if item then
                                local value = reaper.GetMediaItemInfo_Value(item, args[2])
                                response.ok = true
                                response.ret = value
                            end
                        else
                            response.error = "GetMediaItemInfo_Value requires 2 arguments"
                        end
                    
                    elseif fname == "SetMediaItemLength" then
                        if #args >= 3 then
                            local item = args[1]
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use item pointer from previous call - use item index instead"
                                response.ok = false
                                item = nil
                            end
                            
                            if item then
                                reaper.SetMediaItemLength(item, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "SetMediaItemLength requires 3 arguments"
                        end
                    
                    elseif fname == "SetMediaItemPosition" then
                        if #args >= 3 then
                            local item = args[1]
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use item pointer from previous call - use item index instead"
                                response.ok = false
                                item = nil
                            end
                            
                            if item then
                                reaper.SetMediaItemPosition(item, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "SetMediaItemPosition requires 3 arguments"
                        end
                    
                    elseif fname == "SetMediaItemSelected" then
                        if #args >= 2 then
                            local item = args[1]
                            -- Handle item index or pointer
                            if type(args[1]) == "number" then
                                -- It's an item index
                                item = reaper.GetMediaItem(0, args[1])
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference from a previous call - we can't use it
                                response.error = "Cannot use item pointer from previous call - use item index instead"
                                response.ok = false
                                item = nil
                            end
                            
                            if item then
                                reaper.SetMediaItemSelected(item, args[2])
                                response.ok = true
                            else
                                response.error = "Invalid item parameter"
                                response.ok = false
                            end
                        else
                            response.error = "SetMediaItemSelected requires 2 arguments"
                        end
                    
                    elseif fname == "GetProjectName" then
                        local retval, project_name = reaper.GetProjectName(args[1] or 0, "", 512)
                        response.ok = true
                        response.ret = project_name or ""
                        response.name = project_name or ""
                    
                    elseif fname == "GetProjectPath" then
                        local path = reaper.GetProjectPath("", 2048)
                        response.ok = true
                        response.ret = path
                    
                    elseif fname == "Main_SaveProject" then
                        reaper.Main_SaveProject(args[1] or 0, args[2] or false)
                        response.ok = true
                    
                    elseif fname == "GetCursorPosition" then
                        local pos = reaper.GetCursorPosition()
                        response.ok = true
                        response.ret = pos
                    
                    elseif fname == "SetEditCurPos" then
                        if #args >= 1 then
                            reaper.SetEditCurPos(args[1], args[2] or true, args[3] or false)
                            response.ok = true
                        else
                            response.error = "SetEditCurPos requires at least 1 argument"
                        end
                    
                    elseif fname == "GetPlayState" then
                        local state = reaper.GetPlayState()
                        response.ok = true
                        response.ret = state
                    
                    elseif fname == "Main_OnCommand" then
                        if #args >= 2 then
                            reaper.Main_OnCommand(args[1], args[2])
                            response.ok = true
                        else
                            response.error = "Main_OnCommand requires 2 arguments"
                        end
                    
                    elseif fname == "SetPlayState" then
                        if #args >= 3 then
                            local play = args[1] and 1 or 0
                            local pause = args[2] and 2 or 0
                            local rec = args[3] and 4 or 0
                            -- Use Main_OnCommand instead of CSurf_SetPlayState
                            -- Play = 1007, Pause = 1008, Stop = 1016, Record = 1013
                            if rec > 0 then
                                reaper.Main_OnCommand(1013, 0)  -- Record
                            elseif play > 0 then
                                reaper.Main_OnCommand(1007, 0)  -- Play
                            elseif pause > 0 then
                                reaper.Main_OnCommand(1008, 0)  -- Pause
                            else
                                reaper.Main_OnCommand(1016, 0)  -- Stop
                            end
                            response.ok = true
                        else
                            response.error = "SetPlayState requires 3 arguments"
                        end
                    
                    elseif fname == "GetSetRepeat" then
                        if #args >= 1 then
                            local prev = reaper.GetSetRepeat(args[1])
                            response.ok = true
                            response.ret = prev
                        else
                            response.error = "GetSetRepeat requires 1 argument"
                        end
                    
                    elseif fname == "Undo_BeginBlock" then
                        reaper.Undo_BeginBlock()
                        response.ok = true
                    
                    elseif fname == "Undo_EndBlock" then
                        if #args >= 1 then
                            reaper.Undo_EndBlock(args[1], args[2] or -1)
                            response.ok = true
                        else
                            response.error = "Undo_EndBlock requires at least 1 argument"
                        end
                    
                    elseif fname == "UpdateArrange" then
                        reaper.UpdateArrange()
                        response.ok = true
                    
                    elseif fname == "UpdateTimeline" then
                        reaper.UpdateTimeline()
                        response.ok = true
                    
                    elseif fname == "AddProjectMarker" then
                        if #args >= 5 then
                            local index = reaper.AddProjectMarker(args[1], args[2], args[3], args[4], args[5], args[6] or -1)
                            response.ok = true
                            response.ret = index
                        else
                            response.error = "AddProjectMarker requires at least 5 arguments"
                        end
                    
                    elseif fname == "DeleteProjectMarker" then
                        if #args >= 3 then
                            local result = reaper.DeleteProjectMarker(args[1], args[2], args[3])
                            response.ok = result
                        else
                            response.error = "DeleteProjectMarker requires 3 arguments"
                        end
                    
                    elseif fname == "CountProjectMarkers" then
                        local ret, num_markers, num_regions = reaper.CountProjectMarkers(args[1] or 0)
                        response.ok = true
                        response.ret = {num_markers, num_regions}
                    
                    elseif fname == "EnumProjectMarkers" then
                        if #args >= 1 then
                            local ret, is_region, pos, region_end, name, idx = reaper.EnumProjectMarkers(args[1])
                            if ret then
                                response.ok = true
                                response.ret = {ret, is_region, pos, region_end, name, idx}
                            else
                                response.ok = true
                                response.ret = as_array({})
                            end
                        else
                            response.error = "EnumProjectMarkers requires 1 argument"
                        end

                    elseif fname == "GetProjectMarkers" then
                        -- Get all markers (not regions) in the project
                        local markers = as_array({})
                        local ret, num_markers, num_regions = reaper.CountProjectMarkers(0)
                        for i = 0, num_markers + num_regions - 1 do
                            local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
                            if retval and not isrgn then
                                table.insert(markers, {
                                    index = markrgnindexnumber,
                                    position = pos,
                                    name = name
                                })
                            end
                        end
                        response.ok = true
                        response.markers = markers

                    elseif fname == "GetProjectRegions" then
                        -- Get all regions in the project
                        local regions = as_array({})
                        local ret, num_markers, num_regions = reaper.CountProjectMarkers(0)
                        for i = 0, num_markers + num_regions - 1 do
                            local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(i)
                            if retval and isrgn then
                                table.insert(regions, {
                                    index = markrgnindexnumber,
                                    start = pos,
                                    ["end"] = rgnend,
                                    name = name
                                })
                            end
                        end
                        response.ok = true
                        response.regions = regions
                    
                    elseif fname == "GetSet_LoopTimeRange" then
                        if #args >= 2 then
                            if args[1] then  -- Set mode
                                if #args >= 5 then
                                    reaper.GetSet_LoopTimeRange(true, args[2], args[3], args[4], args[5])
                                    response.ok = true
                                else
                                    response.error = "GetSet_LoopTimeRange set mode requires 5 arguments"
                                end
                            else  -- Get mode
                                local start_time, end_time = reaper.GetSet_LoopTimeRange(false, args[2], 0, 0, false)
                                response.ok = true
                                response.ret = {start_time, end_time}
                            end
                        else
                            response.error = "GetSet_LoopTimeRange requires at least 2 arguments"
                        end
                    
                    elseif fname == "MIDI_CountEvts" then
                        if #args >= 1 then
                            local take = args[1]
                            -- Handle take object or pointer
                            if type(args[1]) == "table" and args[1].__ptr then
                                -- It's a pointer reference - we can't use it
                                response.error = "Cannot use take pointer from previous call"
                                response.ok = false
                            else
                                local retval, notes, cc, text = reaper.MIDI_CountEvts(take)
                                response.ok = true
                                response.retval = retval
                                response.notes = notes
                                response.cc = cc
                                response.text = text
                            end
                        else
                            response.error = "MIDI_CountEvts requires 1 argument (take)"
                        end
                    
                    elseif fname == "GetItemTakeAndCountMIDI" then
                        -- Combined function to get item, take and count MIDI events
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Count MIDI events
                                    local retval, notes, cc, text = reaper.MIDI_CountEvts(take)
                                    response.ok = true
                                    response.retval = retval
                                    response.notes = notes
                                    response.cc = cc
                                    response.text = text
                                end
                            end
                        else
                            response.error = "GetItemTakeAndCountMIDI requires 2 arguments (item_index, take_index)"
                        end
                    
                    elseif fname == "InsertMIDINoteToItemTake" then
                        -- Combined function to insert MIDI note
                        if #args >= 11 then
                            local item_index = args[1]
                            local take_index = args[2]
                            local pitch = args[3]
                            local velocity = args[4]
                            local start_time = args[5]
                            local duration = args[6]
                            local channel = args[7]
                            local selected = args[8]
                            local muted = args[9]
                            -- args[10] reserved for future use
                            -- args[11] reserved for future use
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Convert time to PPQ
                                    local ppq_start = reaper.MIDI_GetPPQPosFromProjTime(take, start_time)
                                    local ppq_end = reaper.MIDI_GetPPQPosFromProjTime(take, start_time + duration)
                                    
                                    -- Insert note
                                    local result = reaper.MIDI_InsertNote(take, selected, muted, ppq_start, ppq_end, channel, pitch, velocity, true)
                                    response.ok = result
                                    if not result then
                                        response.error = "Failed to insert MIDI note"
                                    end
                                end
                            end
                        else
                            response.error = "InsertMIDINoteToItemTake requires 11 arguments"
                        end
                    
                    elseif fname == "GetMIDIScaleFromItemTake" then
                        -- Combined function to get MIDI scale
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Get scale
                                    local root, scale, name = reaper.MIDI_GetScale(take)
                                    response.ok = true
                                    response.root = root
                                    response.scale = scale
                                    response.name = name or ""
                                end
                            end
                        else
                            response.error = "GetMIDIScaleFromItemTake requires 2 arguments (item_index, take_index)"
                        end
                    
                    elseif fname == "SortMIDIInItemTake" then
                        -- Combined function to sort MIDI
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Sort MIDI
                                    reaper.MIDI_Sort(take)
                                    response.ok = true
                                end
                            end
                        else
                            response.error = "SortMIDIInItemTake requires 2 arguments (item_index, take_index)"
                        end
                    
                    elseif fname == "InsertMIDICCToItemTake" then
                        -- Combined function to insert MIDI CC
                        if #args >= 7 then
                            local item_index = args[1]
                            local take_index = args[2]
                            local time = args[3]
                            local channel = args[4]
                            local cc_number = args[5]
                            local value = args[6]
                            local selected = args[7]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Convert time to PPQ
                                    local ppq_pos = reaper.MIDI_GetPPQPosFromProjTime(take, time)
                                    
                                    -- Insert CC event
                                    local inserted = reaper.MIDI_InsertCC(take, selected, false, ppq_pos, 0xB0, channel, cc_number, value)
                                    if inserted then
                                        response.ok = true
                                    else
                                        response.ok = false
                                        response.error = "Failed to insert MIDI CC"
                                    end
                                end
                            end
                        else
                            response.error = "InsertMIDICCToItemTake requires 7 arguments"
                        end
                    
                    elseif fname == "SetMIDIScaleToItemTake" then
                        -- Combined function to set MIDI scale
                        if #args >= 5 then
                            local item_index = args[1]
                            local take_index = args[2]
                            local root = args[3]
                            local scale = args[4]
                            local name = args[5] or ""
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Set scale
                                    local result = reaper.MIDI_SetScale(take, root, scale, name)
                                    response.ok = result
                                    if not result then
                                        response.error = "Failed to set MIDI scale"
                                    end
                                end
                            end
                        else
                            response.error = "SetMIDIScaleToItemTake requires 5 arguments"
                        end
                    
                    elseif fname == "SelectAllMIDIInItemTake" then
                        -- Combined function to select all MIDI events
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Select all MIDI events
                                    reaper.MIDI_SelectAll(take, true)
                                    response.ok = true
                                end
                            end
                        else
                            response.error = "SelectAllMIDIInItemTake requires 2 arguments"
                        end
                    
                    elseif fname == "GetAllMIDIEventsFromItemTake" then
                        -- Combined function to get all MIDI events
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Failed to find media item at index " .. tostring(item_index)
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Failed to find take at index " .. tostring(take_index)
                                    response.ok = false
                                else
                                    -- Get all events
                                    local retval, events = reaper.MIDI_GetAllEvts(take, "")
                                    response.ok = retval
                                    response.ret = events
                                    if not retval then
                                        response.error = "Failed to get MIDI events"
                                    end
                                end
                            end
                        else
                            response.error = "GetAllMIDIEventsFromItemTake requires 2 arguments"
                        end
                    
                    elseif fname == "TrackFX_AddByName" then
                        -- Add FX to track by name
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local fx_index = reaper.TrackFX_AddByName(track, args[2], args[3] or false, args[4] or -1)
                                response.ok = true
                                response.ret = fx_index
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_AddByName requires at least 3 arguments"
                        end
                    
                    elseif fname == "TrackFX_GetCount" then
                        -- Get FX count for track
                        if #args >= 1 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    -- Master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local count = reaper.TrackFX_GetCount(track)
                                response.ok = true
                                response.ret = count
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetCount requires 1 argument"
                        end
                    
                    elseif fname == "GetTrackEnvelopeByName" then
                        -- Get envelope by name
                        if #args >= 2 then
                            local track = nil
                            local track_index = args[1]
                            
                            -- Handle case where args[1] might be a table with a numeric value
                            if type(track_index) == "table" then
                                -- Try multiple ways to extract numeric value from table
                                -- Check for direct numeric index
                                if track_index[1] and type(track_index[1]) == "number" then
                                    track_index = track_index[1]
                                -- Check for 'value' key
                                elseif track_index.value and type(track_index.value) == "number" then
                                    track_index = track_index.value
                                -- Check for 'track_index' key
                                elseif track_index.track_index and type(track_index.track_index) == "number" then
                                    track_index = track_index.track_index
                                else
                                    -- Try to find any numeric value in table
                                    for k, v in pairs(track_index) do
                                        if type(v) == "number" then
                                            track_index = v
                                            break
                                        end
                                    end
                                end
                            end
                            
                            if type(track_index) == "number" then
                                if track_index == -1 then
                                    -- Master track
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, track_index)
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                response.error = "Invalid track index type: " .. type(args[1]) .. " (could not extract number from table)"
                                response.ok = false
                            end
                            
                            if track then
                                local envelope = reaper.GetTrackEnvelopeByName(track, args[2])
                                response.ok = true
                                response.ret = envelope
                            elseif response.ok ~= false then
                                -- Only set error if not already set
                                local track_count = reaper.CountTracks(0)
                                response.error = "Track not found at index " .. tostring(track_index) .. " (project has " .. track_count .. " tracks)"
                                response.ok = false
                            end
                        else
                            response.error = "GetTrackEnvelopeByName requires 2 arguments"
                        end
                    
                    elseif fname == "GetTrackAutomationMode" then
                        -- Get track automation mode
                        if #args >= 1 then
                            local track = nil
                            local track_index = args[1]
                            
                            -- Handle case where args[1] might be a table with a numeric value
                            if type(track_index) == "table" then
                                -- Try multiple ways to extract numeric value from table
                                if track_index[1] and type(track_index[1]) == "number" then
                                    track_index = track_index[1]
                                elseif track_index.value and type(track_index.value) == "number" then
                                    track_index = track_index.value
                                elseif track_index.track_index and type(track_index.track_index) == "number" then
                                    track_index = track_index.track_index
                                else
                                    -- Try to find any numeric value in table
                                    for k, v in pairs(track_index) do
                                        if type(v) == "number" then
                                            track_index = v
                                            break
                                        end
                                    end
                                end
                            end
                            
                            if type(track_index) == "number" then
                                track = reaper.GetTrack(0, track_index)
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local mode = reaper.GetTrackAutomationMode(track)
                                response.ok = true
                                response.ret = mode
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "GetTrackAutomationMode requires 1 argument"
                        end
                    
                    elseif fname == "SetTrackAutomationMode" then
                        -- Set track automation mode
                        if #args >= 2 then
                            local track = nil
                            local track_index = args[1]
                            
                            -- Handle case where args[1] might be a table with a numeric value
                            if type(track_index) == "table" then
                                -- Try multiple ways to extract numeric value from table
                                if track_index[1] and type(track_index[1]) == "number" then
                                    track_index = track_index[1]
                                elseif track_index.value and type(track_index.value) == "number" then
                                    track_index = track_index.value
                                elseif track_index.track_index and type(track_index.track_index) == "number" then
                                    track_index = track_index.track_index
                                else
                                    -- Try to find any numeric value in table
                                    for k, v in pairs(track_index) do
                                        if type(v) == "number" then
                                            track_index = v
                                            break
                                        end
                                    end
                                end
                            end
                            
                            if type(track_index) == "number" then
                                track = reaper.GetTrack(0, track_index)
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.SetTrackAutomationMode(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "SetTrackAutomationMode requires 2 arguments"
                        end
                    
                    elseif fname == "TrackFX_Delete" then
                        -- Delete FX from track
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.TrackFX_Delete(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_Delete requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetEnabled" then
                        -- Get FX enabled state
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_GetEnabled(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetEnabled requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_SetEnabled" then
                        -- Set FX enabled state
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.TrackFX_SetEnabled(track, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetEnabled requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetFXName" then
                        -- Get FX name
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local retval, name = reaper.TrackFX_GetFXName(track, args[2], "", args[4] or 256)
                                if retval then
                                    response.ret = name
                                    response.ok = true
                                else
                                    response.error = "Failed to get FX name"
                                    response.ok = false
                                end
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetFXName requires at least 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetNumParams" then
                        -- Get FX parameter count
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_GetNumParams(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetNumParams requires 2 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetEQParam" then
                        -- Get ReaEQ band parameter (per-param query: track, fxidx, paramidx)
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                local retval, bandtype, bandidx, paramtype, normval = reaper.TrackFX_GetEQParam(track, args[2], args[3])
                                response.ok = retval
                                response.ret = retval
                                response.bandtype = bandtype
                                response.bandidx = bandidx
                                response.paramtype = paramtype
                                response.normval = normval
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetEQParam requires 3 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_SetEQParam" then
                        -- Set ReaEQ band parameter (track, fxidx, bandtype, bandidx, paramtype, val, isnorm)
                        if #args >= 7 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                local retval = reaper.TrackFX_SetEQParam(track, args[2], args[3], args[4], args[5], args[6], args[7])
                                response.ok = retval
                                response.ret = retval
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetEQParam requires 7 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetEQ" then
                        -- Locate (or instantiate) ReaEQ in track FX chain (track, instantiate)
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                response.ret = reaper.TrackFX_GetEQ(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetEQ requires 2 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetEQBandEnabled" then
                        -- Query whether a ReaEQ band is enabled (track, fxidx, bandtype, bandidx)
                        if #args >= 4 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                response.ret = reaper.TrackFX_GetEQBandEnabled(track, args[2], args[3], args[4])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetEQBandEnabled requires 4 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_SetEQBandEnabled" then
                        -- Enable/disable a ReaEQ band (track, fxidx, bandtype, bandidx, enable)
                        if #args >= 5 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                local retval = reaper.TrackFX_SetEQBandEnabled(track, args[2], args[3], args[4], args[5])
                                response.ok = retval
                                response.ret = retval
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetEQBandEnabled requires 5 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetFormattedParamValue" then
                        -- Get human-readable formatted FX parameter value (track, fxidx, paramidx)
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end

                            if track then
                                local retval, buf = reaper.TrackFX_GetFormattedParamValue(track, args[2], args[3], "")
                                response.ok = retval
                                response.ret = buf
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetFormattedParamValue requires 3 arguments"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetParam" then
                        -- Get FX parameter value
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local retval, minval, maxval = reaper.TrackFX_GetParam(track, args[2], args[3])
                                response.value = retval
                                response.min = minval
                                response.max = maxval
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetParam requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_SetParam" then
                        -- Set FX parameter value
                        if #args >= 4 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_SetParam(track, args[2], args[3], args[4])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetParam requires 4 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetParamName" then
                        -- Get FX parameter name
                        if #args >= 4 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local retval, name = reaper.TrackFX_GetParamName(track, args[2], args[3], "", args[4] or 256)
                                if retval then
                                    response.ret = name
                                    response.ok = true
                                else
                                    response.error = "Failed to get parameter name"
                                    response.ok = false
                                end
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetParamName requires at least 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetPreset" then
                        -- Get FX preset name
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                local retval, name = reaper.TrackFX_GetPreset(track, args[2], "", args[3] or 256)
                                if retval then
                                    response.ret = name
                                    response.ok = true
                                else
                                    response.error = "Failed to get preset name"
                                    response.ok = false
                                end
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetPreset requires at least 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_SetPreset" then
                        -- Set FX preset
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_SetPreset(track, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetPreset requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_Show" then
                        -- Show/hide FX window
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.TrackFX_Show(track, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_Show requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetOpen" then
                        -- Get FX window open state
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_GetOpen(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetOpen requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_SetOpen" then
                        -- Set FX window open state
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.TrackFX_SetOpen(track, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetOpen requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetChainVisible" then
                        -- Get FX chain visibility
                        if #args >= 1 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_GetChainVisible(track)
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetChainVisible requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_CopyToTrack" then
                        -- Copy/move FX between tracks
                        if #args >= 5 then
                            local src_track = nil
                            local dest_track = nil

                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    src_track = reaper.GetMasterTrack(0)
                                else
                                    src_track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use source track pointer from previous call"
                                response.ok = false
                            else
                                src_track = args[1]
                            end

                            if type(args[3]) == "number" then
                                if args[3] == -1 then
                                    dest_track = reaper.GetMasterTrack(0)
                                else
                                    dest_track = reaper.GetTrack(0, args[3])
                                end
                            elseif type(args[3]) == "table" and args[3].__ptr then
                                response.error = "Cannot use destination track pointer from previous call"
                                response.ok = false
                            else
                                dest_track = args[3]
                            end
                            
                            if src_track and dest_track then
                                reaper.TrackFX_CopyToTrack(src_track, args[2], dest_track, args[4], args[5])
                                response.ok = true
                            else
                                if not src_track then
                                    response.error = "Source track not found"
                                else
                                    response.error = "Destination track not found"
                                end
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_CopyToTrack requires 5 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_GetOffline" then
                        -- Get FX offline state
                        if #args >= 2 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                response.ret = reaper.TrackFX_GetOffline(track, args[2])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetOffline requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "TrackFX_SetOffline" then
                        -- Set FX offline state
                        if #args >= 3 then
                            local track = nil
                            if type(args[1]) == "number" then
                                if args[1] == -1 then
                                    track = reaper.GetMasterTrack(0)
                                else
                                    track = reaper.GetTrack(0, args[1])
                                end
                            elseif type(args[1]) == "table" and args[1].__ptr then
                                response.error = "Cannot use track pointer from previous call"
                                response.ok = false
                            else
                                track = args[1]
                            end
                            
                            if track then
                                reaper.TrackFX_SetOffline(track, args[2], args[3])
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_SetOffline requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetGlobalAutomationOverride" then
                        -- Get global automation override
                        local mode = reaper.GetGlobalAutomationOverride()
                        response.ok = true
                        response.ret = mode
                    
                    elseif fname == "SetGlobalAutomationOverride" then
                        -- Set global automation override
                        if #args >= 1 then
                            reaper.SetGlobalAutomationOverride(args[1])
                            response.ok = true
                        else
                            response.error = "SetGlobalAutomationOverride requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMainHwnd" then
                        -- Get main window handle
                        local hwnd = reaper.GetMainHwnd()
                        response.ok = true
                        response.ret = hwnd
                    
                    elseif fname == "GetMousePosition" then
                        -- Get current mouse position
                        local x, y = reaper.GetMousePosition()
                        response.ok = true
                        response.ret = {x, y}
                    
                    elseif fname == "GetCursorContext" then
                        -- Get cursor context
                        local context = reaper.GetCursorContext()
                        response.ok = true
                        response.ret = context
                    
                    elseif fname == "ShowMessageBox" then
                        -- Show message box
                        if #args >= 3 then
                            local result = reaper.ShowMessageBox(args[1], args[2], args[3])
                            response.ok = true
                            response.ret = result
                        else
                            response.error = "ShowMessageBox requires 3 arguments (message, title, type)"
                            response.ok = false
                        end
                    
                    elseif fname == "ShowConsoleMsg" then
                        -- Show console message
                        if #args >= 1 then
                            reaper.ShowConsoleMsg(args[1])
                            response.ok = true
                        else
                            response.error = "ShowConsoleMsg requires 1 argument (message)"
                            response.ok = false
                        end
                    
                    elseif fname == "ClearConsole" then
                        -- Clear console
                        reaper.ClearConsole()
                        response.ok = true
                    
                    elseif fname == "PCM_Source_CreateFromFile" then
                        -- Create PCM source from file
                        if #args >= 1 then
                            local source = reaper.PCM_Source_CreateFromFile(args[1])
                            response.ok = true
                            response.ret = source
                        else
                            response.error = "PCM_Source_CreateFromFile requires 1 argument (filename)"
                            response.ok = false
                        end
                    
                    elseif fname == "SetMediaItemTake_Source" then
                        -- Set media source on take
                        if #args >= 2 then
                            local retval = reaper.SetMediaItemTake_Source(args[1], args[2])
                            response.ok = true
                            response.ret = retval
                        else
                            response.error = "SetMediaItemTake_Source requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaItemTake_Source" then
                        -- Get media source from take
                        if #args >= 1 then
                            local source = reaper.GetMediaItemTake_Source(args[1])
                            response.ok = true
                            response.ret = source
                        else
                            response.error = "GetMediaItemTake_Source requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaSourceSampleRate" then
                        -- Get sample rate from media source
                        if #args >= 1 then
                            local samplerate = reaper.GetMediaSourceSampleRate(args[1])
                            response.ok = true
                            response.ret = samplerate
                        else
                            response.error = "GetMediaSourceSampleRate requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaSourceNumChannels" then
                        -- Get channel count from media source
                        if #args >= 1 then
                            local channels = reaper.GetMediaSourceNumChannels(args[1])
                            response.ok = true
                            response.ret = channels
                        else
                            response.error = "GetMediaSourceNumChannels requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "DB2SLIDER" then
                        -- Convert dB to slider value
                        if #args >= 1 then
                            local slider = reaper.DB2SLIDER(args[1])
                            response.ok = true
                            response.ret = slider
                        else
                            response.error = "DB2SLIDER requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "SLIDER2DB" then
                        -- Convert slider value to dB
                        if #args >= 1 then
                            local db = reaper.SLIDER2DB(args[1])
                            response.ok = true
                            response.ret = db
                        else
                            response.error = "SLIDER2DB requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "AddTakeToMediaItem" then
                        -- Add take to media item
                        if #args >= 1 then
                            local take = reaper.AddTakeToMediaItem(args[1])
                            response.ok = true
                            response.ret = take
                        else
                            response.error = "AddTakeToMediaItem requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "CountTakes" then
                        -- Count takes in media item
                        if #args >= 1 then
                            local count = reaper.CountTakes(args[1])
                            response.ok = true
                            response.ret = count
                        else
                            response.error = "CountTakes requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetTake" then
                        -- Get take from item by indices
                        if #args >= 2 then
                            local item = reaper.GetMediaItem(0, args[1])
                            if item then
                                local take = reaper.GetMediaItemTake(item, args[2])
                                response.ok = true
                                response.ret = take
                            else
                                response.error = "Item not found"
                                response.ok = false
                            end
                        else
                            response.error = "GetTake requires 2 arguments"
                            response.ok = false
                        end

                    -- ===== Take FX (v1.3.0) =====
                    -- All take-addressed by (track_index, item_index, take_index) via resolve_take.
                    elseif fname == "TakeFX_GetCount" then
                        if #args >= 3 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                response.ret = reaper.TakeFX_GetCount(take)
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetCount requires 3 arguments (track, item, take)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetList" then
                        -- List all FX on a take: index, name, enabled
                        if #args >= 3 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                local fx = as_array({})
                                local count = reaper.TakeFX_GetCount(take)
                                for f = 0, count - 1 do
                                    local _, fx_name = reaper.TakeFX_GetFXName(take, f, "")
                                    fx[#fx + 1] = {
                                        index = f,
                                        name = fx_name,
                                        enabled = reaper.TakeFX_GetEnabled(take, f)
                                    }
                                end
                                response.fx = fx
                                response.ret = count
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetList requires 3 arguments (track, item, take)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_AddByName" then
                        -- args: track, item, take, fx_name
                        if #args >= 4 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                -- TakeFX_AddByName(take, fxname, instantiate); -1 = add to end
                                response.ret = reaper.TakeFX_AddByName(take, args[4], -1)
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_AddByName requires 4 arguments (track, item, take, fx_name)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_Delete" then
                        -- args: track, item, take, fx_index
                        if #args >= 4 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                response.ret = reaper.TakeFX_Delete(take, args[4])
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_Delete requires 4 arguments (track, item, take, fx_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetFXName" then
                        -- args: track, item, take, fx_index
                        if #args >= 4 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                local _, fx_name = reaper.TakeFX_GetFXName(take, args[4], "")
                                response.ret = fx_name
                                response.value = fx_name
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetFXName requires 4 arguments (track, item, take, fx_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetEnabled" then
                        -- args: track, item, take, fx_index
                        if #args >= 4 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                response.ret = reaper.TakeFX_GetEnabled(take, args[4])
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetEnabled requires 4 arguments (track, item, take, fx_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_SetEnabled" then
                        -- args: track, item, take, fx_index, enabled
                        if #args >= 5 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                reaper.TakeFX_SetEnabled(take, args[4], args[5])
                                response.ret = true
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_SetEnabled requires 5 arguments (track, item, take, fx_index, enabled)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetNumParams" then
                        -- args: track, item, take, fx_index
                        if #args >= 4 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                response.ret = reaper.TakeFX_GetNumParams(take, args[4])
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetNumParams requires 4 arguments (track, item, take, fx_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetParamName" then
                        -- args: track, item, take, fx_index, param_index
                        if #args >= 5 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                local _, p_name = reaper.TakeFX_GetParamName(take, args[4], args[5], "")
                                response.ret = p_name
                                response.value = p_name
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetParamName requires 5 arguments (track, item, take, fx_index, param_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_GetParam" then
                        -- args: track, item, take, fx_index, param_index
                        if #args >= 5 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                local val, minval, maxval = reaper.TakeFX_GetParam(take, args[4], args[5])
                                response.value = val
                                response.min = minval
                                response.max = maxval
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_GetParam requires 5 arguments (track, item, take, fx_index, param_index)"
                            response.ok = false
                        end

                    elseif fname == "TakeFX_SetParam" then
                        -- args: track, item, take, fx_index, param_index, value
                        if #args >= 6 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                response.ret = reaper.TakeFX_SetParam(take, args[4], args[5], args[6])
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "TakeFX_SetParam requires 6 arguments (track, item, take, fx_index, param_index, value)"
                            response.ok = false
                        end

                    -- ===== Takes & comping (v1.3.0 Phase B) =====
                    elseif fname == "GetTakes" then
                        -- args: track, item -> list takes with name + active flag
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if item then
                                local active = reaper.GetActiveTake(item)
                                local takes = as_array({})
                                local count = reaper.CountTakes(item)
                                for t = 0, count - 1 do
                                    local take = reaper.GetTake(item, t)
                                    if take then
                                        -- GetTakeName returns a single string (not retval, name)
                                        takes[#takes + 1] = {
                                            index = t,
                                            name = reaper.GetTakeName(take),
                                            is_active = (take == active)
                                        }
                                    end
                                end
                                response.takes = takes
                                response.ret = count
                                response.ok = true
                            else
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            end
                        else
                            response.error = "GetTakes requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "GetActiveTakeIndex" then
                        -- args: track, item -> index of the active take (-1 if none)
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if item then
                                local active = reaper.GetActiveTake(item)
                                local idx = -1
                                if active then
                                    for t = 0, reaper.CountTakes(item) - 1 do
                                        if reaper.GetTake(item, t) == active then
                                            idx = t
                                            break
                                        end
                                    end
                                end
                                response.ret = idx
                                response.ok = true
                            else
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            end
                        else
                            response.error = "GetActiveTakeIndex requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "SetActiveTakeByIndex" then
                        -- args: track, item, take
                        if #args >= 3 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                reaper.SetActiveTake(take)
                                reaper.UpdateArrange()
                                response.ret = true
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "SetActiveTakeByIndex requires 3 arguments (track, item, take)"
                            response.ok = false
                        end

                    elseif fname == "ExplodeTakes" then
                        -- args: track, item -> action 40642 "Take: Explode takes of items in place"
                        if #args >= 2 then
                            local ok2, err = run_item_action(args[1], args[2], 40642)
                            response.ok = ok2
                            response.ret = ok2
                            if not ok2 then response.error = err end
                        else
                            response.error = "ExplodeTakes requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "CropToActiveTake" then
                        -- args: track, item -> action 40131 "Take: Crop to active take in items"
                        if #args >= 2 then
                            local ok2, err = run_item_action(args[1], args[2], 40131)
                            response.ok = ok2
                            response.ret = ok2
                            if not ok2 then response.error = err end
                        else
                            response.error = "CropToActiveTake requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "DeleteTakeByIndex" then
                        -- args: track, item, take -> activate that take, then action 40129
                        -- "Take: Delete active take from items"
                        if #args >= 3 then
                            local take, err = resolve_take(args[1], args[2], args[3])
                            if take then
                                reaper.SetActiveTake(take)
                                local ok2, err2 = run_item_action(args[1], args[2], 40129)
                                response.ok = ok2
                                response.ret = ok2
                                if not ok2 then response.error = err2 end
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "DeleteTakeByIndex requires 3 arguments (track, item, take)"
                            response.ok = false
                        end

                    elseif fname == "SelectCompLane" then
                        -- args: track, lane -> C_LANEPLAYS:lane = 1 (lane plays exclusively).
                        -- Requires the track to be in fixed-lane mode (I_FREEMODE == 2).
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            if track then
                                local mode = reaper.GetMediaTrackInfo_Value(track, "I_FREEMODE")
                                local lanes = reaper.GetMediaTrackInfo_Value(track, "I_NUMFIXEDLANES")
                                if mode ~= 2 then
                                    response.error = "Track " .. tostring(args[1])
                                        .. " is not in fixed-lane mode (enable track lanes first)"
                                    response.ok = false
                                elseif args[2] < 0 or args[2] >= lanes then
                                    response.error = "Lane " .. tostring(args[2])
                                        .. " out of range (track has " .. tostring(math.floor(lanes)) .. " lanes)"
                                    response.ok = false
                                else
                                    reaper.SetMediaTrackInfo_Value(track, "C_LANEPLAYS:" .. math.floor(args[2]), 1)
                                    reaper.UpdateArrange()
                                    response.ret = true
                                    response.ok = true
                                end
                            else
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            end
                        else
                            response.error = "SelectCompLane requires 2 arguments (track, lane)"
                            response.ok = false
                        end

                    -- ===== v1.3.1 fixes & additions (ported from PR #1, credit @nuxero) =====
                    elseif fname == "SetMediaItemInfo_Value" then
                        -- args: track_index, item_index, param_name, value
                        if #args >= 4 then
                            local track
                            if args[1] == -1 then
                                track = reaper.GetMasterTrack(0)
                            else
                                track = reaper.GetTrack(0, args[1])
                            end
                            if not track then
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            else
                                local item = reaper.GetTrackMediaItem(track, args[2])
                                if not item then
                                    response.error = "Media item not found at index " .. tostring(args[2])
                                        .. " on track " .. tostring(args[1])
                                    response.ok = false
                                else
                                    reaper.SetMediaItemInfo_Value(item, args[3], args[4])
                                    reaper.UpdateArrange()
                                    response.ret = true
                                    response.ok = true
                                end
                            end
                        else
                            response.error = "SetMediaItemInfo_Value requires 4 arguments (track, item, param, value)"
                            response.ok = false
                        end

                    elseif fname == "GetItemInfo" then
                        -- args: track_index, item_index
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if item then
                                local take = reaper.GetActiveTake(item)
                                local is_midi = false
                                local take_name = ""
                                if take then
                                    is_midi = reaper.TakeIsMIDI(take)
                                    -- GetTakeName returns a single string
                                    take_name = reaper.GetTakeName(take) or ""
                                end
                                response.ok = true
                                response.info = {
                                    position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
                                    length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
                                    volume = reaper.GetMediaItemInfo_Value(item, "D_VOL"),
                                    mute = reaper.GetMediaItemInfo_Value(item, "B_MUTE") == 1,
                                    loop_source = reaper.GetMediaItemInfo_Value(item, "B_LOOPSRC") == 1,
                                    fade_in = reaper.GetMediaItemInfo_Value(item, "D_FADEINLEN"),
                                    fade_out = reaper.GetMediaItemInfo_Value(item, "D_FADEOUTLEN"),
                                    is_midi = is_midi,
                                    take_name = take_name
                                }
                            else
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            end
                        else
                            response.error = "GetItemInfo requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "SetMIDINoteVelocity" then
                        -- args: track_index, item_index, note_index, velocity
                        if #args >= 4 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if take then
                                local ok = reaper.MIDI_SetNote(take, args[3], nil, nil, nil, nil, nil, nil, args[4], false)
                                response.ok = ok
                                response.ret = ok
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "SetMIDINoteVelocity requires 4 arguments (track, item, note, velocity)"
                            response.ok = false
                        end

                    elseif fname == "GetMIDINotes" then
                        -- args: track_index, item_index -> notes from the active MIDI take
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if not item then
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            else
                                local take = reaper.GetActiveTake(item)
                                if not take or not reaper.TakeIsMIDI(take) then
                                    response.error = "Active take is not MIDI"
                                    response.ok = false
                                else
                                    local notes, note_count = midi_note_list(take, item)
                                    response.notes = notes
                                    response.ret = note_count
                                    response.ok = true
                                end
                            end
                        else
                            response.error = "GetMIDINotes requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "TransposeMIDINotes" then
                        -- args: track_index, item_index, semitones, filter{}  (v1.6.0)
                        if #args >= 3 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local semitones = args[3]
                                    local filt = args[4] or {}
                                    local res = transpose_notes_pure(midi_read_notes(take), semitones, filt, ctx)
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, ch in ipairs(res.changes) do
                                            reaper.MIDI_SetNote(take, ch.index, nil, nil, nil, nil, nil, ch.new_pitch, nil, true)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Transpose MIDI notes", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = res.skipped
                                        response.out_of_bounds = 0
                                        response.ok = true
                                    else
                                        response.error = "Transpose failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "TransposeMIDINotes requires track_index, item_index, semitones"
                            response.ok = false
                        end

                    elseif fname == "NudgeMIDINotes" then
                        -- args: track_index, item_index, amount_beats, filter{}  (v1.6.0)
                        if #args >= 3 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local filt = args[4] or {}
                                    local delta_ppq = math.floor(args[3] * ctx.ppq_per_qn + 0.5)
                                    local res = nudge_notes_pure(midi_read_notes(take), delta_ppq, filt, ctx)
                                    if res.notes_changed > 0 then
                                        reaper.Undo_BeginBlock()
                                        local wok, werr = pcall(function()
                                            for _, ch in ipairs(res.changes) do
                                                reaper.MIDI_SetNote(take, ch.index, nil, nil, ch.new_start, ch.new_end, nil, nil, nil, true)
                                            end
                                            reaper.MIDI_Sort(take)
                                        end)
                                        reaper.Undo_EndBlock("Nudge MIDI notes", 4)
                                        if not wok then
                                            response.error = "Nudge failed: " .. tostring(werr)
                                            response.ok = false
                                        end
                                    end
                                    if not response.error then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = res.out_of_bounds
                                        response.ok = true
                                    end
                                end
                            end
                        else
                            response.error = "NudgeMIDINotes requires track_index, item_index, amount_beats"
                            response.ok = false
                        end

                    elseif fname == "GetSelectedMIDINotes" then
                        -- args: track_index, item_index -> only the notes selected in REAPER (v1.6.0, read-only, D2)
                        if #args >= 2 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local sel = as_array(filter_selected((midi_note_list(take, item))))
                                response.notes = sel
                                response.ret = #sel
                                response.ok = true
                            end
                        else
                            response.error = "GetSelectedMIDINotes requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "SelectAllMIDINotes" then
                        -- TEST-ONLY helper (v1.6.0). No public @mcp.tool() wraps this: the
                        -- selection *writer* tool is deferred to v1.7.0 (S2). It exists solely so
                        -- the get_selected_midi_notes live test can arrange a non-empty selection
                        -- (freshly inserted notes come in unselected), proving the selected=true
                        -- value flows through and a selected note carries Shape H. Uses the proper
                        -- resolve_midi_take addressing, not the orphan GetMediaItem+take_index path.
                        -- args: track_index, item_index, select (bool, default true)
                        if #args >= 2 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local want = args[3]
                                if want == nil then want = true end
                                reaper.MIDI_SelectAll(take, want)   -- flips flags only; no sort needed
                                response.ok = true
                            end
                        else
                            response.error = "SelectAllMIDINotes requires track_index, item_index"
                            response.ok = false
                        end

                    elseif fname == "SetMIDINote" then
                        -- args: track_index, item_index, note_index, edits{pitch?, start_beat?, length_beats?, channel?}
                        if #args >= 3 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            local note_index = args[3]
                            local edits = args[4] or {}
                            local ok0, _sel, _mut, sppq, eppq = false, nil, nil, nil, nil
                            if take then ok0, _sel, _mut, sppq, eppq = reaper.MIDI_GetNote(take, note_index) end
                            if not take then
                                response.error = err
                                response.ok = false
                            elseif not ok0 then
                                response.error = "Note not found at index " .. tostring(note_index)
                                response.ok = false
                            elseif edits.pitch == nil and edits.start_beat == nil and edits.length_beats == nil and edits.channel == nil then
                                response.error = "set_midi_note requires at least one of pitch/start_beat/length_beats/channel"
                                response.ok = false
                            elseif edits.pitch ~= nil and not valid_pitch(edits.pitch) then
                                response.error = "pitch must be an integer 0-127"
                                response.ok = false
                            elseif edits.channel ~= nil and not valid_channel(edits.channel) then
                                response.error = "channel must be an integer 0-15"
                                response.ok = false
                            elseif edits.length_beats ~= nil and not valid_length(edits.length_beats) then
                                response.error = "length_beats must be > 0"
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local timing = (edits.start_beat ~= nil or edits.length_beats ~= nil)
                                    local startIn, endIn, oob = nil, nil, false
                                    if timing then
                                        local nsp = edits.start_beat ~= nil and beats_to_take_ppq(edits.start_beat, ctx.item_start_ppq, ctx.ppq_per_qn) or nil
                                        local nlp = edits.length_beats ~= nil and len_beats_to_ppq(edits.length_beats, ctx.ppq_per_qn) or nil
                                        local fs, fe = compute_note_span(sppq, eppq, nsp, nlp)
                                        oob = note_out_of_bounds(fs, fe, ctx.item_start_ppq, ctx.item_end_ppq)
                                        if fs < ctx.item_start_ppq then     -- REAPER floors at item start; clamp, keep length
                                            fe = fe + (ctx.item_start_ppq - fs)
                                            fs = ctx.item_start_ppq
                                        end
                                        startIn, endIn = fs, fe
                                    end
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        reaper.MIDI_SetNote(take, note_index, nil, nil, startIn, endIn, edits.channel, edits.pitch, nil, true)
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Set MIDI note", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = 1
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = oob and 1 or 0
                                        response.ok = true
                                    else
                                        response.error = "Set note failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "SetMIDINote requires track_index, item_index, note_index"
                            response.ok = false
                        end

                    elseif fname == "RampMIDINoteVelocities" then
                        -- args: track_index, item_index, start_velocity, end_velocity, filter{}
                        if #args >= 4 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local filt = args[5] or {}
                                    local res = midi_ramp_velocities(midi_read_notes(take), filt, ctx, args[3], args[4])
                                    if res.notes_changed > 0 then
                                        reaper.Undo_BeginBlock()
                                        local wok, werr = pcall(function()
                                            for _, ch in ipairs(res.changes) do
                                                reaper.MIDI_SetNote(take, ch.index, nil, nil, nil, nil, nil, nil, ch.new_vel, true)
                                            end
                                            reaper.MIDI_Sort(take)
                                        end)
                                        reaper.Undo_EndBlock("Ramp MIDI note velocities", 4)
                                        if not wok then
                                            response.error = "Ramp failed: " .. tostring(werr)
                                            response.ok = false
                                        end
                                    end
                                    if not response.error then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = res.clamped
                                        response.skipped = 0
                                        response.out_of_bounds = 0
                                        response.ok = true
                                    end
                                end
                            end
                        else
                            response.error = "RampMIDINoteVelocities requires track, item, start_velocity, end_velocity"
                            response.ok = false
                        end

                    elseif fname == "ScaleMIDINoteVelocities" then
                        -- args: track, item, mode, ratio, value, pivot, filter{}  (validation done server-side)
                        if #args >= 6 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local opts = {mode = args[3], ratio = args[4], value = args[5], pivot = args[6]}
                                    local filt = args[7] or {}
                                    local out, stats = compute_scaled_velocities(midi_read_notes(take), opts, filt, ctx)
                                    if stats.notes_changed > 0 then
                                        reaper.Undo_BeginBlock()
                                        local wok, werr = pcall(function()
                                            for _, ch in ipairs(out) do
                                                if ch.changed then
                                                    reaper.MIDI_SetNote(take, ch.index, nil, nil, nil, nil, nil, nil, ch.new_vel, true)
                                                end
                                            end
                                            reaper.MIDI_Sort(take)
                                        end)
                                        reaper.Undo_EndBlock("Scale MIDI note velocities", 4)
                                        if not wok then
                                            response.error = "Scale velocities failed: " .. tostring(werr)
                                            response.ok = false
                                        end
                                    end
                                    if not response.error then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = stats.notes_changed
                                        response.clamped = stats.clamped
                                        response.skipped = 0
                                        response.out_of_bounds = 0
                                        response.pivot_used = stats.pivot_used
                                        response.ok = true
                                    end
                                end
                            end
                        else
                            response.error = "ScaleMIDINoteVelocities requires track, item, mode, ratio, value, pivot"
                            response.ok = false
                        end

                    elseif fname == "StrumMIDINotes" then
                        -- args: track, item, spread_beats, direction, chord_window_beats, filter{}
                        if #args >= 5 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local opts = {
                                        spread_ppq = args[3] * ctx.ppq_per_qn,
                                        direction = args[4],
                                        chord_window_ppq = args[5] * ctx.ppq_per_qn,
                                    }
                                    local filt = args[6] or {}
                                    local res = strum_notes_pure(midi_read_notes(take), opts, filt, ctx)
                                    if res.notes_changed > 0 then
                                        reaper.Undo_BeginBlock()
                                        local wok, werr = pcall(function()
                                            for _, ch in ipairs(res.changes) do
                                                reaper.MIDI_SetNote(take, ch.index, nil, nil, ch.new_start, ch.new_end, nil, nil, nil, true)
                                            end
                                            reaper.MIDI_Sort(take)
                                        end)
                                        reaper.Undo_EndBlock("Strum MIDI", 4)
                                        if not wok then
                                            response.error = "Strum failed: " .. tostring(werr)
                                            response.ok = false
                                        end
                                    end
                                    if not response.error then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = res.out_of_bounds
                                        response.ok = true
                                    end
                                end
                            end
                        else
                            response.error = "StrumMIDINotes requires track, item, spread_beats, direction, chord_window_beats"
                            response.ok = false
                        end

                    elseif fname == "SnapMIDINotesToScale" then
                        -- args: track, item, root, mode, direction, filter{}  (v1.6.0)
                        if #args >= 5 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                -- mode: a name from MODE_INTERVALS, or a custom interval list
                                local intervals = resolve_mode_intervals(args[4])
                                if not intervals or #intervals == 0 then
                                    response.error = "Unknown scale mode: " .. tostring(args[4])
                                    response.ok = false
                                else
                                    local item = reaper.GetMediaItemTake_Item(take)
                                    local ctx = midi_ctx(take, item)
                                    if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                        response.error = "Could not determine PPQ-per-quarter-note for take"
                                        response.ok = false
                                    else
                                        local scale_pcs = scale_pitch_classes(args[3], intervals)
                                        local filt = args[6] or {}
                                        local res = snap_notes_to_scale_pure(midi_read_notes(take), filt, ctx,
                                                                             scale_pcs, args[5])
                                        reaper.Undo_BeginBlock()
                                        local wok, werr = pcall(function()
                                            for _, ch in ipairs(res.changes) do
                                                reaper.MIDI_SetNote(take, ch.index, nil, nil, nil, nil, nil, ch.new_pitch, nil, true)
                                            end
                                            reaper.MIDI_Sort(take)
                                        end)
                                        reaper.Undo_EndBlock("Snap MIDI notes to scale", 4)
                                        if wok then
                                            response.notes = midi_note_list(take, item)
                                            response.notes_changed = res.notes_changed
                                            response.clamped = 0
                                            response.skipped = res.skipped
                                            response.out_of_bounds = 0
                                            response.ok = true
                                        else
                                            response.error = "Snap to scale failed: " .. tostring(werr)
                                            response.ok = false
                                        end
                                    end
                                end
                            end
                        else
                            response.error = "SnapMIDINotesToScale requires track_index, item_index, root, mode, direction"
                            response.ok = false
                        end

                    elseif fname == "QuantizeMIDINotes" then
                        -- args: track, item, grid, strength, swing, filter{}  (v1.6.0)
                        if #args >= 5 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                elseif not (args[3] and args[3] > 0) then
                                    response.error = "grid must be > 0"
                                    response.ok = false
                                else
                                    -- give each note its PROJECT QN + length-in-QN; the grid math is
                                    -- QN-native (tempo-safe) while the filter still runs on PPQ
                                    local notes = midi_read_notes(take)
                                    for _, n in ipairs(notes) do
                                        n.qn = reaper.MIDI_GetProjQNFromPPQPos(take, n.startppq)
                                        n.len_qn = reaper.MIDI_GetProjQNFromPPQPos(take, n.endppq) - n.qn
                                    end
                                    local filt = args[6] or {}
                                    local res = quantize_notes(notes, args[3], args[4], args[5], filt, ctx)
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, ch in ipairs(res.changes) do
                                            -- a start clamped to the item edge uses the exact item_start_ppq:
                                            -- round-tripping it through QN could land a hair early, and REAPER
                                            -- refuses any note before the item start outright [D10].
                                            local ns = ch.at_item_start and ctx.item_start_ppq
                                                       or reaper.MIDI_GetPPQPosFromProjQN(take, ch.new_qn)
                                            local ne = reaper.MIDI_GetPPQPosFromProjQN(take, ch.new_end_qn)
                                            reaper.MIDI_SetNote(take, ch.index, nil, nil, ns, ne, nil, nil, nil, true)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Quantize MIDI notes", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = res.out_of_bounds
                                        response.ok = true
                                    else
                                        response.error = "Quantize failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "QuantizeMIDINotes requires track_index, item_index, grid, strength, swing"
                            response.ok = false
                        end

                    elseif fname == "StretchMIDINotes" then
                        -- args: track, item, factor, opts{pivot_beat?, + the 5 filter keys}  (v1.6.0)
                        if #args >= 4 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                elseif not (args[3] and args[3] > 0) then
                                    response.error = "factor must be > 0"
                                    response.ok = false
                                else
                                    -- opts doubles as the filter: note_in_filter reads only its own 5
                                    -- keys and ignores the extra pivot_beat, so one object serves both
                                    local opts = args[4] or {}
                                    local pivot_ppq = nil
                                    if opts.pivot_beat ~= nil then
                                        pivot_ppq = ctx.item_start_ppq + opts.pivot_beat * ctx.ppq_per_qn
                                    end
                                    local res = stretch_notes(midi_read_notes(take), args[3], pivot_ppq, opts, ctx)
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, ch in ipairs(res.changes) do
                                            reaper.MIDI_SetNote(take, ch.index, nil, nil, ch.new_start, ch.new_end, nil, nil, nil, true)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Stretch MIDI notes", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = res.out_of_bounds
                                        response.ok = true
                                    else
                                        response.error = "Stretch failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "StretchMIDINotes requires track_index, item_index, factor"
                            response.ok = false
                        end

                    elseif fname == "LegatoMIDINotes" then
                        -- args: track, item, mode, voice, max_gap_beats, length_beats, filter{}
                        if #args >= 6 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local opts = {
                                        mode = args[3],
                                        voice = args[4],
                                        max_gap_ppq = args[5] * ctx.ppq_per_qn,
                                        length_ppq = args[6] * ctx.ppq_per_qn,
                                    }
                                    local filt = args[7] or {}
                                    local res = legato_pure(midi_read_notes(take), opts, filt, ctx)
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, ch in ipairs(res.changes) do
                                            -- end only: legato never moves a start
                                            reaper.MIDI_SetNote(take, ch.index, nil, nil, nil, ch.new_end, nil, nil, nil, true)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Legato MIDI", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = res.notes_changed
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = res.out_of_bounds
                                        response.gaps_preserved = res.gaps_preserved
                                        response.ok = true
                                    else
                                        response.error = "Legato failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "LegatoMIDINotes requires track, item, mode, voice, max_gap_beats, length_beats"
                            response.ok = false
                        end

                    elseif fname == "HumanizeMIDINotes" then
                        -- args: track, item, timing_offsets[] (beats), velocity_offsets[], filter{}
                        -- Offsets arrive PRE-DRAWN from Python's seeded RNG: no dice here (D8).
                        if #args >= 4 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                else
                                    local toff_beats = args[3] or {}
                                    local voff = args[4] or {}
                                    local filt = args[5] or {}
                                    local toff_ppq = {}
                                    for i = 1, #toff_beats do
                                        toff_ppq[i] = math.floor(toff_beats[i] * ctx.ppq_per_qn + 0.5)
                                    end
                                    local recs, stats = humanize_midi_notes_pure(midi_read_notes(take),
                                                                                 filt, ctx, toff_ppq, voff)
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, r in ipairs(recs) do
                                            -- nil for every facet not being changed, so an
                                            -- untouched start/velocity is left exactly as it was
                                            reaper.MIDI_SetNote(take, r.index, nil, nil,
                                                r.timing_changed and r.new_start or nil,
                                                r.timing_changed and r.new_end or nil,
                                                nil, nil,
                                                r.vel_changed and r.new_vel or nil, true)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Humanize MIDI", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.notes_changed = stats.notes_changed
                                        response.clamped = stats.clamped
                                        response.skipped = 0
                                        response.out_of_bounds = stats.out_of_bounds
                                        response.ok = true
                                    else
                                        response.error = "Humanize failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "HumanizeMIDINotes requires track, item, timing_offsets, velocity_offsets"
                            response.ok = false
                        end

                    elseif fname == "RemoveOverlappingMIDINotes" then
                        -- args: track, item, mode, min_length_beats, filter{}   (v1.6.0)
                        -- The only count-CHANGING tool: it deletes notes. Deletes run descending.
                        if args[1] ~= nil and args[2] ~= nil then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if not take then
                                response.error = err
                                response.ok = false
                            else
                                local item = reaper.GetMediaItemTake_Item(take)
                                local ctx = midi_ctx(take, item)
                                local mode = args[3] or "trim"
                                if not (ctx.ppq_per_qn and ctx.ppq_per_qn > 0) then
                                    response.error = "Could not determine PPQ-per-quarter-note for take"
                                    response.ok = false
                                elseif mode ~= "trim" and mode ~= "delete" then
                                    response.error = "mode must be 'trim' or 'delete'"
                                    response.ok = false
                                else
                                    local filt = args[5] or {}
                                    -- scope FIRST: an out-of-scope note must be invisible to overlap
                                    -- detection, not merely spared from the edit
                                    local scoped = {}
                                    for _, n in ipairs(midi_read_notes(take)) do
                                        if note_in_filter(n, filt, ctx) then scoped[#scoped + 1] = n end
                                    end
                                    local res = remove_overlaps_pure(scoped, {
                                        mode = mode,
                                        min_length_ppq = (args[4] or 0) * ctx.ppq_per_qn,
                                    })
                                    reaper.Undo_BeginBlock()
                                    local wok, werr = pcall(function()
                                        for _, e in ipairs(res.edits) do        -- trims first...
                                            reaper.MIDI_SetNote(take, e.index, nil, nil, nil, e.new_end, nil, nil, nil, true)
                                        end
                                        for _, idx in ipairs(res.removals) do   -- ...then deletes, descending
                                            reaper.MIDI_DeleteNote(take, idx)
                                        end
                                        reaper.MIDI_Sort(take)
                                    end)
                                    reaper.Undo_EndBlock("Remove overlapping MIDI notes", 4)
                                    if wok then
                                        response.notes = midi_note_list(take, item)
                                        response.mode = mode
                                        response.notes_changed = res.trimmed   -- 0 in delete mode
                                        response.clamped = 0
                                        response.skipped = 0
                                        response.out_of_bounds = 0
                                        response.trimmed = res.trimmed
                                        response.deduped = res.deduped
                                        response.deleted = res.deleted
                                        response.notes_removed = res.deduped + res.deleted
                                        response.ok = true
                                    else
                                        response.error = "Remove overlapping failed: " .. tostring(werr)
                                        response.ok = false
                                    end
                                end
                            end
                        else
                            response.error = "RemoveOverlappingMIDINotes requires track_index, item_index"
                            response.ok = false
                        end

                    elseif fname == "Track_GetPeakInfo" then
                        -- args: track_index, channel -> current peak in dB
                        if #args >= 2 then
                            local track
                            if args[1] == -1 then
                                track = reaper.GetMasterTrack(0)
                            else
                                track = reaper.GetTrack(0, args[1])
                            end
                            if track then
                                local peak = reaper.Track_GetPeakInfo(track, args[2])
                                local peak_db = -150
                                if peak > 0 then
                                    peak_db = 20 * math.log(peak, 10)
                                end
                                response.ret = peak_db
                                response.ok = true
                            else
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            end
                        else
                            response.error = "Track_GetPeakInfo requires 2 arguments (track, channel)"
                            response.ok = false
                        end

                    elseif fname == "Track_GetPeakHoldDB" then
                        -- args: track_index, channel -> held peak (dB) since last meter reset
                        if #args >= 2 then
                            local track
                            if args[1] == -1 then
                                track = reaper.GetMasterTrack(0)
                            else
                                track = reaper.GetTrack(0, args[1])
                            end
                            if track then
                                -- API returns dB/100 (0.01 == 1 dB)
                                response.ret = reaper.Track_GetPeakHoldDB(track, args[2], false) * 100
                                response.ok = true
                            else
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            end
                        else
                            response.error = "Track_GetPeakHoldDB requires 2 arguments (track, channel)"
                            response.ok = false
                        end

                    elseif fname == "ClearAllPeakIndicators" then
                        -- reset peak hold on master + all tracks (clearOnRead flag)
                        local master = reaper.GetMasterTrack(0)
                        if master then
                            reaper.Track_GetPeakHoldDB(master, 0, true)
                            reaper.Track_GetPeakHoldDB(master, 1, true)
                        end
                        for i = 0, reaper.CountTracks(0) - 1 do
                            local tr = reaper.GetTrack(0, i)
                            if tr then
                                reaper.Track_GetPeakHoldDB(tr, 0, true)
                                reaper.Track_GetPeakHoldDB(tr, 1, true)
                            end
                        end
                        response.ret = true
                        response.ok = true

                    elseif fname == "TrackFX_CopyToTrack" then
                        -- args: src_track, fx_index, dst_track, dst_position, is_move
                        if #args >= 5 then
                            local function trk(idx)
                                if idx == -1 then return reaper.GetMasterTrack(0) end
                                return reaper.GetTrack(0, idx)
                            end
                            local src, dst = trk(args[1]), trk(args[3])
                            if src and dst then
                                reaper.TrackFX_CopyToTrack(src, args[2], dst, args[4], args[5] and true or false)
                                response.ret = true
                                response.ok = true
                            else
                                response.error = "Track not found (src " .. tostring(args[1])
                                    .. ", dst " .. tostring(args[3]) .. ")"
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_CopyToTrack requires 5 arguments (src_track, fx, dst_track, position, move)"
                            response.ok = false
                        end

                    -- ===== v1.3.2: explicit handlers for tools that fell to the generic fallback =====
                    elseif fname == "MIDI_DeleteNote" then
                        -- args: track, item, note_index
                        if #args >= 3 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if take then
                                local ok2 = reaper.MIDI_DeleteNote(take, args[3])
                                reaper.MIDI_Sort(take)
                                response.ret = ok2
                                response.ok = ok2
                                if not ok2 then response.error = "Note not found at index " .. tostring(args[3]) end
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "MIDI_DeleteNote requires 3 arguments (track, item, note_index)"
                            response.ok = false
                        end

                    elseif fname == "SplitMediaItem" then
                        -- args: track, item, position (project seconds). Returns right-half item index.
                        if #args >= 3 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if item then
                                local right = reaper.SplitMediaItem(item, args[3])
                                if right then
                                    local right_index = -1
                                    for i = 0, reaper.CountTrackMediaItems(track) - 1 do
                                        if reaper.GetTrackMediaItem(track, i) == right then
                                            right_index = i
                                            break
                                        end
                                    end
                                    reaper.UpdateArrange()
                                    response.ret = right_index
                                    response.ok = true
                                else
                                    response.error = "Split failed (position outside the item?)"
                                    response.ok = false
                                end
                            else
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            end
                        else
                            response.error = "SplitMediaItem requires 3 arguments (track, item, position)"
                            response.ok = false
                        end

                    elseif fname == "DuplicateItem" then
                        -- args: track, item -> action 41295 "Item: Duplicate items"
                        if #args >= 2 then
                            local ok2, err = run_item_action(args[1], args[2], 41295)
                            response.ok = ok2
                            response.ret = ok2
                            if not ok2 then response.error = err end
                        else
                            response.error = "DuplicateItem requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "GetMIDIItemInfo" then
                        -- args: track, item
                        if #args >= 2 then
                            local track = reaper.GetTrack(0, args[1])
                            local item = track and reaper.GetTrackMediaItem(track, args[2])
                            if item then
                                local take = reaper.GetActiveTake(item)
                                local is_midi = take and reaper.TakeIsMIDI(take) or false
                                local note_count = 0
                                if is_midi then
                                    local _, notes = reaper.MIDI_CountEvts(take)
                                    note_count = notes
                                end
                                response.ok = true
                                response.info = {
                                    position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
                                    length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
                                    is_midi = is_midi,
                                    note_count = note_count
                                }
                            else
                                response.error = track and ("Media item not found at index " .. tostring(args[2]))
                                    or ("Track not found at index " .. tostring(args[1]))
                                response.ok = false
                            end
                        else
                            response.error = "GetMIDIItemInfo requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "ClearMIDIItem" then
                        -- args: track, item -> remove all MIDI events from the active take
                        if #args >= 2 then
                            local take, err = resolve_midi_take(args[1], args[2])
                            if take then
                                reaper.MIDI_SetAllEvts(take, "")
                                reaper.MIDI_Sort(take)
                                response.ret = true
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "ClearMIDIItem requires 2 arguments (track, item)"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_GetPresetList" then
                        -- args: track, fx. REAPER's API cannot enumerate preset NAMES;
                        -- return the count plus the current preset name/index.
                        if #args >= 2 then
                            local track
                            if args[1] == -1 then track = reaper.GetMasterTrack(0)
                            else track = reaper.GetTrack(0, args[1]) end
                            if track then
                                local idx, count = reaper.TrackFX_GetPresetIndex(track, args[2])
                                local _, cur = reaper.TrackFX_GetPreset(track, args[2], "")
                                response.ok = true
                                response.preset_count = count
                                response.current_index = idx
                                response.current_preset = cur
                                response.note = "REAPER's API cannot list preset names; use set_fx_preset with a known name"
                            else
                                response.error = "Track not found at index " .. tostring(args[1])
                                response.ok = false
                            end
                        else
                            response.error = "TrackFX_GetPresetList requires 2 arguments (track, fx)"
                            response.ok = false
                        end

                    elseif fname == "TrackFX_SavePreset" then
                        -- Honest unsupported: vanilla ReaScript has no API to save a named FX preset.
                        response.ok = false
                        response.error = "Not supported: REAPER's API cannot save named FX presets. "
                            .. "Save manually via the FX window's preset menu (+ button), or use "
                            .. "get_track_fx_chunk to capture the current FX state instead."

                    elseif fname == "CountEnvelopePoints" then
                        -- args: track, envelope_name
                        if #args >= 2 then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                response.ret = reaper.CountEnvelopePoints(env)
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "CountEnvelopePoints requires 2 arguments (track, envelope_name)"
                            response.ok = false
                        end

                    elseif fname == "GetEnvelopePoints" then
                        -- args: track, envelope_name
                        if #args >= 2 then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                local points = as_array({})
                                local count = reaper.CountEnvelopePoints(env)
                                for p = 0, count - 1 do
                                    local ok2, time, value, shape, tension, selected =
                                        reaper.GetEnvelopePoint(env, p)
                                    if ok2 then
                                        points[#points + 1] = {
                                            index = p, time = time, value = value,
                                            shape = shape, tension = tension, selected = selected
                                        }
                                    end
                                end
                                response.points = points
                                response.ret = count
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "GetEnvelopePoints requires 2 arguments (track, envelope_name)"
                            response.ok = false
                        end

                    elseif fname == "DeleteEnvelopePoint" then
                        -- args: track, envelope_name, point_index
                        if #args >= 3 then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                local ok2 = reaper.DeleteEnvelopePointEx(env, -1, args[3])
                                reaper.Envelope_SortPoints(env)
                                reaper.UpdateArrange()
                                response.ret = ok2
                                response.ok = ok2
                                if not ok2 then response.error = "Point not found at index " .. tostring(args[3]) end
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "DeleteEnvelopePoint requires 3 arguments (track, envelope_name, point_index)"
                            response.ok = false
                        end

                    elseif fname == "ClearEnvelope" then
                        -- args: track, envelope_name -> delete all points (explicit loop;
                        -- DeleteEnvelopePointRange can leave a point behind)
                        if #args >= 2 then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                local count = reaper.CountEnvelopePoints(env)
                                for p = count - 1, 0, -1 do
                                    reaper.DeleteEnvelopePointEx(env, -1, p)
                                end
                                reaper.Envelope_SortPoints(env)
                                reaper.UpdateArrange()
                                response.remaining = reaper.CountEnvelopePoints(env)
                                response.ret = true
                                response.ok = true
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "ClearEnvelope requires 2 arguments (track, envelope_name)"
                            response.ok = false
                        end

                    elseif fname == "SetEnvelopeArm" then
                        -- args: track, envelope_name, arm. No direct API; edit the state chunk's ARM flag.
                        if #args >= 3 then
                            local env, err = resolve_envelope(args[1], args[2])
                            if env then
                                local ok2, chunk = reaper.GetEnvelopeStateChunk(env, "", false)
                                if ok2 and chunk then
                                    local flag = args[3] and "1" or "0"
                                    local new_chunk, n = chunk:gsub("\nARM %d", "\nARM " .. flag, 1)
                                    if n > 0 then
                                        reaper.SetEnvelopeStateChunk(env, new_chunk, false)
                                        response.ret = true
                                        response.ok = true
                                    else
                                        response.error = "ARM flag not found in envelope state"
                                        response.ok = false
                                    end
                                else
                                    response.error = "Could not read envelope state"
                                    response.ok = false
                                end
                            else
                                response.error = err
                                response.ok = false
                            end
                        else
                            response.error = "SetEnvelopeArm requires 3 arguments (track, envelope_name, arm)"
                            response.ok = false
                        end

                    elseif fname == "GetUndoState" then
                        -- next undo/redo action labels (nil-safe)
                        response.can_undo = reaper.Undo_CanUndo2(0)
                        response.can_redo = reaper.Undo_CanRedo2(0)
                        response.ok = true

                    elseif fname == "SetTimeSignature" then
                        -- args: numerator, denominator -> tempo/time-sig marker at project start
                        if #args >= 2 then
                            local bpm = reaper.Master_GetTempo()
                            local ok2 = reaper.SetTempoTimeSigMarker(0, -1, 0, -1, -1, bpm, args[1], args[2], false)
                            reaper.UpdateTimeline()
                            response.ret = ok2
                            response.ok = ok2
                            if not ok2 then response.error = "SetTempoTimeSigMarker failed" end
                        else
                            response.error = "SetTimeSignature requires 2 arguments (numerator, denominator)"
                            response.ok = false
                        end

                    elseif fname == "RenderProject" then
                        -- args: output_path, start_time (-1 = project start), end_time (-1 = project end),
                        --       tail_seconds. Renders the master mix via "render last settings" (41824).
                        if #args >= 1 and type(args[1]) == "string" and args[1] ~= "" then
                            local path = args[1]
                            local start_t = tonumber(args[2]) or -1
                            local end_t = tonumber(args[3]) or -1
                            local tail = tonumber(args[4]) or 0

                            local dir = path:match("^(.*)[/\\]") or ""
                            local file = path:match("[^/\\]+$") or path
                            local base = file:gsub("%.[A-Za-z0-9]+$", "")
                            local ext = file:match("%.([A-Za-z0-9]+)$")

                            reaper.GetSetProjectInfo_String(0, "RENDER_FILE", dir, true)
                            reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", base, true)
                            if ext and ext:lower() == "wav" then
                                reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "evaw", true)
                            end
                            -- master mix, source = master
                            reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)
                            if start_t >= 0 and end_t > start_t then
                                reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true) -- custom bounds
                                reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", start_t, true)
                                reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", end_t + tail, true)
                            elseif tail > 0 then
                                local proj_len = reaper.GetProjectLength(0)
                                reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true)
                                reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", 0, true)
                                reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", proj_len + tail, true)
                            else
                                reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 1, true) -- entire project
                            end
                            -- Read back REAPER's own computed output target(s)
                            local _, targets = reaper.GetSetProjectInfo_String(0, "RENDER_TARGETS", "", false)
                            -- Existing-target handling is part of the tool contract (args[5]
                            -- = overwrite). We never delete files unless the caller asked,
                            -- because REAPER's behavior on existing files (prompt vs
                            -- auto-increment) is a user preference we cannot assume.
                            local existing = {}
                            local function exists(p)
                                local f = io.open(p, "rb")
                                if f then f:close() return true end
                                return false
                            end
                            if targets and targets ~= "" then
                                for t in string.gmatch(targets, "[^;]+") do
                                    if exists(t) then existing[#existing + 1] = t end
                                end
                            elseif exists(path) then
                                existing[#existing + 1] = path
                            end
                            if #existing > 0 and not args[5] then
                                response.error = "Render target already exists: "
                                    .. table.concat(existing, "; ")
                                    .. ". Pass overwrite=true to replace it, or render to a "
                                    .. "different path. (Rendering onto an existing file may "
                                    .. "otherwise pop REAPER's overwrite prompt, which blocks "
                                    .. "unattended rendering.)"
                                response.ok = false
                            else
                                if #existing > 0 then
                                    for _, t in ipairs(existing) do os.remove(t) end
                                end
                                -- 42230 = render using last settings, auto-close render dialog.
                                -- (41824 opens the dialog on projects that have never rendered.)
                                reaper.Main_OnCommand(42230, 0)
                                response.ret = true
                                response.output = path
                                response.targets = targets
                                response.ok = true
                            end
                        else
                            response.error = "RenderProject requires output_path (string)"
                            response.ok = false
                        end

                    elseif fname == "IsTrackVisible" then
                        -- Check if track is visible in TCP/MCP
                        if #args >= 2 then
                            local visible = reaper.IsTrackVisible(args[1], args[2])
                            response.ok = true
                            response.ret = visible
                        else
                            response.error = "IsTrackVisible requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "SetOnlyTrackSelected" then
                        -- Set only one track selected
                        if #args >= 1 then
                            local track = args[1]
                            -- Handle track index
                            if type(track) == "number" then
                                track = reaper.GetTrack(0, track)
                            end
                            if track then
                                reaper.SetOnlyTrackSelected(track)
                                response.ok = true
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "SetOnlyTrackSelected requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "NamedCommandLookup" then
                        -- Look up named command
                        if #args >= 1 then
                            local cmd_id = reaper.NamedCommandLookup(args[1])
                            response.ok = true
                            response.ret = cmd_id
                        else
                            response.error = "NamedCommandLookup requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "ReverseNamedCommandLookup" then
                        -- Reverse command lookup
                        if #args >= 2 then
                            local name = reaper.ReverseNamedCommandLookup(args[1], args[2])
                            response.ok = true
                            response.ret = name or ""
                        else
                            response.error = "ReverseNamedCommandLookup requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetToggleCommandStateEx" then
                        -- Get toggle command state for section
                        if #args >= 2 then
                            local state = reaper.GetToggleCommandStateEx(args[1], args[2])
                            response.ok = true
                            response.ret = state
                        else
                            response.error = "GetToggleCommandStateEx requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "RefreshToolbar" then
                        -- Refresh toolbar
                        if #args >= 1 then
                            reaper.RefreshToolbar(args[1])
                            response.ok = true
                        else
                            response.error = "RefreshToolbar requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "EnumerateFiles" then
                        -- Enumerate files
                        if #args >= 2 then
                            local file = reaper.EnumerateFiles(args[1], args[2])
                            response.ok = true
                            response.ret = file or ""
                        else
                            response.error = "EnumerateFiles requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "EnumerateSubdirectories" then
                        -- Enumerate subdirectories
                        if #args >= 2 then
                            local dir = reaper.EnumerateSubdirectories(args[1], args[2])
                            response.ok = true
                            response.ret = dir or ""
                        else
                            response.error = "EnumerateSubdirectories requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetProjectPath" then
                        -- Get project path
                        if #args >= 1 then
                            local path = reaper.GetProjectPath(args[1])
                            response.ok = true
                            response.ret = path or ""
                        else
                            response.error = "GetProjectPath requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetProjectName" then
                        -- Get project name
                        if #args >= 1 then
                            local name = reaper.GetProjectName(args[1])
                            response.ok = true
                            response.ret = name or ""
                        else
                            response.error = "GetProjectName requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "IsProjectDirty" then
                        -- Check if project is dirty
                        if #args >= 1 then
                            local dirty = reaper.IsProjectDirty(args[1])
                            response.ok = true
                            response.ret = dirty
                        else
                            response.error = "IsProjectDirty requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetResourcePath" then
                        -- Get resource path
                        local path = reaper.GetResourcePath()
                        response.ok = true
                        response.ret = path
                    
                    elseif fname == "GetExePath" then
                        -- Get exe path
                        local path = reaper.GetExePath()
                        response.ok = true
                        response.ret = path
                    
                    elseif fname == "GetExtState" then
                        -- Get extended state
                        if #args >= 2 then
                            local value = reaper.GetExtState(args[1], args[2])
                            response.ok = true
                            response.ret = value or ""
                        else
                            response.error = "GetExtState requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "SetExtState" then
                        -- Set extended state
                        if #args >= 4 then
                            reaper.SetExtState(args[1], args[2], args[3], args[4])
                            response.ok = true
                        else
                            response.error = "SetExtState requires 4 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "HasExtState" then
                        -- Check if extended state exists
                        if #args >= 2 then
                            local exists = reaper.HasExtState(args[1], args[2])
                            response.ok = true
                            response.ret = exists
                        else
                            response.error = "HasExtState requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DeleteExtState" then
                        -- Delete extended state
                        if #args >= 3 then
                            reaper.DeleteExtState(args[1], args[2], args[3])
                            response.ok = true
                        else
                            response.error = "DeleteExtState requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DockWindowActivate" then
                        -- Activate docker window
                        if #args >= 1 then
                            reaper.DockWindowActivate(args[1])
                            response.ok = true
                        else
                            response.error = "DockWindowActivate requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "DockWindowAddEx" then
                        -- Add window to docker
                        if #args >= 4 then
                            reaper.DockWindowAddEx(args[1], args[2], args[3], args[4])
                            response.ok = true
                        else
                            response.error = "DockWindowAddEx requires 4 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DockWindowRefresh" then
                        -- Refresh docker windows
                        reaper.DockWindowRefresh()
                        response.ok = true
                    
                    elseif fname == "DockWindowRefreshByName" then
                        -- Refresh docker window by name
                        if #args >= 1 then
                            reaper.DockWindowRefreshByName(args[1])
                            response.ok = true
                        else
                            response.error = "DockWindowRefreshByName requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "DockGetPosition" then
                        -- Get docker position
                        if #args >= 1 then
                            local pos = reaper.DockGetPosition(args[1])
                            response.ok = true
                            response.ret = pos
                        else
                            response.error = "DockGetPosition requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "DeleteTakeFromMediaItem" then
                        -- Delete take from item
                        if #args >= 1 then
                            local result = reaper.DeleteTakeFromMediaItem(args[1])
                            response.ok = result
                        else
                            response.error = "DeleteTakeFromMediaItem requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetNumTakeMarkers" then
                        -- Get number of take markers
                        if #args >= 1 then
                            local count = reaper.GetNumTakeMarkers(args[1])
                            response.ok = true
                            response.ret = count
                        else
                            response.error = "GetNumTakeMarkers requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetTakeMarker" then
                        -- Get take marker info
                        if #args >= 2 then
                            local position, name, color = reaper.GetTakeMarker(args[1], args[2])
                            response.ok = true
                            response.position = position
                            response.name = name or ""
                            response.color = color or 0
                        else
                            response.error = "GetTakeMarker requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "SetTakeMarker" then
                        -- Set/add take marker
                        if #args >= 5 then
                            local idx = reaper.SetTakeMarker(args[1], args[2], args[3], args[4], args[5])
                            response.ok = true
                            response.ret = idx
                        else
                            response.error = "SetTakeMarker requires 5 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DeleteTakeMarker" then
                        -- Delete take marker
                        if #args >= 2 then
                            local result = reaper.DeleteTakeMarker(args[1], args[2])
                            response.ok = result
                        else
                            response.error = "DeleteTakeMarker requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "CountTakeEnvelopes" then
                        -- Count take envelopes
                        if #args >= 1 then
                            local count = reaper.CountTakeEnvelopes(args[1])
                            response.ok = true
                            response.ret = count
                        else
                            response.error = "CountTakeEnvelopes requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetTakeEnvelopeByName" then
                        -- Get take envelope by name
                        if #args >= 2 then
                            local env = reaper.GetTakeEnvelopeByName(args[1], args[2])
                            response.ok = true
                            response.ret = env
                        else
                            response.error = "GetTakeEnvelopeByName requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "EnumProjectMarkers" then
                        -- Enumerate project markers
                        if #args >= 1 then
                            local retval, isrgn, pos, rgnend, name, markrgnindexnumber = reaper.EnumProjectMarkers(args[1])
                            response.ok = retval > 0
                            response.isrgn = isrgn
                            response.pos = pos
                            response.rgnend = rgnend
                            response.name = name or ""
                            response.markrgnindexnumber = markrgnindexnumber
                        else
                            response.error = "EnumProjectMarkers requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "EnumProjectMarkers3" then
                        -- Enumerate project markers with color
                        if #args >= 2 then
                            local retval, isrgn, pos, rgnend, name, markrgnindexnumber, color = reaper.EnumProjectMarkers3(args[1], args[2])
                            response.ok = retval > 0
                            response.isrgn = isrgn
                            response.pos = pos
                            response.rgnend = rgnend
                            response.name = name or ""
                            response.markrgnindexnumber = markrgnindexnumber
                            response.color = color
                        else
                            response.error = "EnumProjectMarkers3 requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "CountProjectMarkers" then
                        -- Count project markers
                        if #args >= 1 then
                            local num_markers, num_regions = reaper.CountProjectMarkers(args[1])
                            response.ok = true
                            response.num_markers = num_markers
                            response.num_regions = num_regions
                        else
                            response.error = "CountProjectMarkers requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "SetProjectMarker" then
                        -- Set project marker
                        if #args >= 5 then
                            local result = reaper.SetProjectMarker(args[1], args[2], args[3], args[4], args[5])
                            response.ok = result
                        else
                            response.error = "SetProjectMarker requires 5 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "SetProjectMarker3" then
                        -- Set project marker with color
                        if #args >= 7 then
                            local result = reaper.SetProjectMarker3(args[1], args[2], args[3], args[4], args[5], args[6], args[7])
                            response.ok = result
                        else
                            response.error = "SetProjectMarker3 requires 7 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DeleteProjectMarker" then
                        -- Delete project marker
                        if #args >= 3 then
                            local result = reaper.DeleteProjectMarker(args[1], args[2], args[3])
                            response.ok = true
                            response.ret = result
                        else
                            response.error = "DeleteProjectMarker requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GoToMarker" then
                        -- Go to marker
                        if #args >= 3 then
                            reaper.GoToMarker(args[1], args[2], args[3])
                            response.ok = true
                        else
                            response.error = "GoToMarker requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "CountTrackEnvelopes" then
                        -- Count track envelopes
                        if #args >= 1 then
                            local count = reaper.CountTrackEnvelopes(args[1])
                            response.ok = true
                            response.ret = count
                        else
                            response.error = "CountTrackEnvelopes requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetTrackName" then
                        -- Get track name
                        if #args >= 1 then
                            local track = reaper.GetTrack(0, args[1])
                            if track then
                                local retval, name = reaper.GetTrackName(track)
                                response.ok = retval
                                response.ret = name or ""
                            else
                                response.error = "Track not found"
                                response.ok = false
                            end
                        else
                            response.error = "GetTrackName requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaItem_Track" then
                        -- Get item's track
                        if #args >= 1 then
                            local track = reaper.GetMediaItem_Track(args[1])
                            response.ok = true
                            response.ret = track
                        else
                            response.error = "GetMediaItem_Track requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "TakeIsMIDI" then
                        -- Check if take is MIDI
                        if #args >= 1 then
                            local ismidi = reaper.TakeIsMIDI(args[1])
                            response.ok = true
                            response.ret = ismidi
                        else
                            response.error = "TakeIsMIDI requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "MIDI_GetNote" then
                        -- Get MIDI note
                        if #args >= 2 then
                            local retval, selected, muted, startppqpos, endppqpos, chan, pitch, vel = reaper.MIDI_GetNote(args[1], args[2])
                            response.ok = retval
                            response.selected = selected
                            response.muted = muted
                            response.startppqpos = startppqpos
                            response.endppqpos = endppqpos
                            response.chan = chan
                            response.pitch = pitch
                            response.vel = vel
                        else
                            response.error = "MIDI_GetNote requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GenerateMIDIChordSequence" then
                        -- Generate MIDI chord sequence by item/take indices
                        if #args >= 4 then
                            local item_index = args[1]
                            local take_index = args[2]
                            local chord_progression = args[3]  -- Table of chord names
                            local duration = args[4]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Item not found"
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Take not found"
                                    response.ok = false
                                else
                                    -- Check if MIDI
                                    if not reaper.TakeIsMIDI(take) then
                                        response.error = "Take is not MIDI"
                                        response.ok = false
                                    else
                                        -- Chord definitions (simplified)
                                        local chord_types = {
                                            maj = {0, 4, 7},
                                            min = {0, 3, 7},
                                            ["7"] = {0, 4, 7, 10},
                                            maj7 = {0, 4, 7, 11},
                                            min7 = {0, 3, 7, 10},
                                            dim = {0, 3, 6},
                                            aug = {0, 4, 8}
                                        }
                                        
                                        -- Note name to MIDI mapping
                                        local note_map = {C = 0, D = 2, E = 4, F = 5, G = 7, A = 9, B = 11}
                                        
                                        local ppq_per_quarter = 960
                                        local current_pos = 0
                                        local chords_added = 0
                                        
                                        for _, chord_name in ipairs(chord_progression) do
                                            -- Parse chord (e.g., "Cmaj", "Am7")
                                            local root_note = nil
                                            local chord_type = nil
                                            
                                            -- Find root note
                                            for note, value in pairs(note_map) do
                                                if string.sub(chord_name, 1, #note) == note then
                                                    root_note = value + 60  -- Middle octave
                                                    local rest = string.sub(chord_name, #note + 1)
                                                    
                                                    -- Handle sharps/flats
                                                    if string.sub(rest, 1, 1) == "#" then
                                                        root_note = root_note + 1
                                                        rest = string.sub(rest, 2)
                                                    elseif string.sub(rest, 1, 1) == "b" then
                                                        root_note = root_note - 1
                                                        rest = string.sub(rest, 2)
                                                    end
                                                    
                                                    -- Find chord type
                                                    chord_type = chord_types[rest] or chord_types.maj
                                                    break
                                                end
                                            end
                                            
                                            if root_note then
                                                -- Insert chord notes
                                                for _, interval in ipairs(chord_type) do
                                                    local pitch = root_note + interval
                                                    reaper.MIDI_InsertNote(take, false, false, current_pos, 
                                                                          current_pos + (duration * ppq_per_quarter),
                                                                          0, pitch, 80, false)
                                                end
                                                chords_added = chords_added + 1
                                                current_pos = current_pos + (duration * ppq_per_quarter)
                                            end
                                        end
                                        
                                        -- Sort notes
                                        reaper.MIDI_Sort(take)
                                        
                                        response.ok = true
                                        response.chords_added = chords_added
                                        response.progression = table.concat(chord_progression, " → ")
                                    end
                                end
                            end
                        else
                            response.error = "GenerateMIDIChordSequence requires 4 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DetectMIDIChordProgressions" then
                        -- Detect chord progressions by item/take indices
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Item not found"
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Take not found"
                                    response.ok = false
                                else
                                    -- Check if MIDI
                                    if not reaper.TakeIsMIDI(take) then
                                        response.error = "Take is not MIDI"
                                        response.ok = false
                                    else
                                        -- Get all notes
                                        local retval, notes = reaper.MIDI_CountEvts(take)
                                        
                                        -- Group notes by time to find chords
                                        local time_groups = {}
                                        
                                        for i = 0, notes - 1 do
                                            local retval, selected, muted, startppqpos, endppqpos, chan, pitch, vel = reaper.MIDI_GetNote(take, i)
                                            if retval then
                                                -- Quantize time to group simultaneous notes
                                                local time_key = math.floor(startppqpos / 240) * 240  -- Quarter note quantization
                                                
                                                if not time_groups[time_key] then
                                                    time_groups[time_key] = {}
                                                end
                                                table.insert(time_groups[time_key], pitch)
                                            end
                                        end
                                        
                                        -- Analyze chords
                                        local chords = {}
                                        local sorted_times = {}
                                        for time, _ in pairs(time_groups) do
                                            table.insert(sorted_times, time)
                                        end
                                        table.sort(sorted_times)
                                        
                                        local count = 0
                                        for _, time in ipairs(sorted_times) do
                                            if count >= 10 then break end  -- First 10 chords
                                            
                                            local pitches = time_groups[time]
                                            if #pitches >= 3 then  -- At least 3 notes for a chord
                                                -- Sort pitches
                                                table.sort(pitches)
                                                
                                                -- Basic chord detection
                                                local root = pitches[1] % 12
                                                local note_names = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"}
                                                local chord_name = note_names[root + 1]
                                                
                                                -- Check for major/minor (simplified)
                                                if #pitches >= 3 then
                                                    local third = (pitches[2] - pitches[1]) % 12
                                                    if third == 4 then
                                                        chord_name = chord_name .. " major"
                                                    elseif third == 3 then
                                                        chord_name = chord_name .. " minor"
                                                    end
                                                end
                                                
                                                table.insert(chords, chord_name)
                                                count = count + 1
                                            end
                                        end
                                        
                                        if #chords > 0 then
                                            response.ok = true
                                            response.progression = table.concat(chords, " → ")
                                        else
                                            response.ok = true
                                            response.progression = "No clear chord progression detected"
                                        end
                                    end
                                end
                            end
                        else
                            response.error = "DetectMIDIChordProgressions requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMIDINoteDistribution" then
                        -- Get MIDI note distribution by item/take indices
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Item not found"
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Take not found"
                                    response.ok = false
                                else
                                    -- Check if MIDI
                                    if not reaper.TakeIsMIDI(take) then
                                        response.error = "Take is not MIDI"
                                        response.ok = false
                                    else
                                        -- Get all notes
                                        local retval, notes = reaper.MIDI_CountEvts(take)
                                        
                                        -- Count note occurrences
                                        local pitch_counts = {}
                                        local total_velocity = 0
                                        
                                        for i = 0, notes - 1 do
                                            local retval, selected, muted, startppqpos, endppqpos, chan, pitch, vel = reaper.MIDI_GetNote(take, i)
                                            if retval then
                                                pitch_counts[pitch] = (pitch_counts[pitch] or 0) + 1
                                                total_velocity = total_velocity + vel
                                            end
                                        end
                                        
                                        -- Build distribution info
                                        local distribution = as_array({})
                                        for pitch, count in pairs(pitch_counts) do
                                            table.insert(distribution, {pitch=pitch, count=count})
                                        end
                                        
                                        -- Sort by count
                                        table.sort(distribution, function(a, b) return a.count > b.count end)
                                        
                                        response.ok = true
                                        response.notes_total = notes
                                        response.distribution = distribution
                                        response.avg_velocity = notes > 0 and (total_velocity / notes) or 0
                                    end
                                end
                            end
                        else
                            response.error = "GetMIDINoteDistribution requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DetectMIDIKeySignature" then
                        -- Detect key signature by item/take indices
                        if #args >= 2 then
                            local item_index = args[1]
                            local take_index = args[2]
                            
                            -- Get item
                            local item = reaper.GetMediaItem(0, item_index)
                            if not item then
                                response.error = "Item not found"
                                response.ok = false
                            else
                                -- Get take
                                local take = reaper.GetMediaItemTake(item, take_index)
                                if not take then
                                    response.error = "Take not found"
                                    response.ok = false
                                else
                                    -- Check if MIDI
                                    if not reaper.TakeIsMIDI(take) then
                                        response.error = "Take is not MIDI"
                                        response.ok = false
                                    else
                                        -- Get all notes
                                        local retval, notes = reaper.MIDI_CountEvts(take)
                                        
                                        -- Count pitch classes
                                        local pitch_classes = {}
                                        for i = 0, 11 do
                                            pitch_classes[i] = 0
                                        end
                                        
                                        for i = 0, notes - 1 do
                                            local retval, selected, muted, startppqpos, endppqpos, chan, pitch, vel = reaper.MIDI_GetNote(take, i)
                                            if retval then
                                                local pitch_class = pitch % 12
                                                pitch_classes[pitch_class] = pitch_classes[pitch_class] + 1
                                            end
                                        end
                                        
                                        -- Key profiles (simplified)
                                        local major_profile = {6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88}
                                        local minor_profile = {6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17}
                                        
                                        local note_names = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"}
                                        
                                        -- Calculate correlation with each key
                                        local best_major_key = nil
                                        local best_major_score = -1
                                        local best_minor_key = nil
                                        local best_minor_score = -1
                                        
                                        for root = 0, 11 do
                                            -- Calculate major correlation
                                            local major_score = 0
                                            local minor_score = 0
                                            
                                            for i = 0, 11 do
                                                local shifted_idx = (i + root) % 12
                                                major_score = major_score + pitch_classes[shifted_idx] * major_profile[i + 1]
                                                minor_score = minor_score + pitch_classes[shifted_idx] * minor_profile[i + 1]
                                            end
                                            
                                            if major_score > best_major_score then
                                                best_major_score = major_score
                                                best_major_key = root
                                            end
                                            
                                            if minor_score > best_minor_score then
                                                best_minor_score = minor_score
                                                best_minor_key = root
                                            end
                                        end
                                        
                                        -- Determine major or minor
                                        local key, confidence
                                        if best_major_score > best_minor_score then
                                            key = note_names[best_major_key + 1] .. " major"
                                            confidence = (best_major_score / (best_major_score + best_minor_score)) * 100
                                        else
                                            key = note_names[best_minor_key + 1] .. " minor"
                                            confidence = (best_minor_score / (best_major_score + best_minor_score)) * 100
                                        end
                                        
                                        response.ok = true
                                        response.key = key
                                        response.confidence = confidence
                                        response.notes_analyzed = notes
                                    end
                                end
                            end
                        else
                            response.error = "DetectMIDIKeySignature requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "Master_GetTempo" then
                        -- Get master tempo
                        local tempo = reaper.Master_GetTempo()
                        response.ok = true
                        response.ret = tempo
                    
                    elseif fname == "CountTempoTimeSigMarkers" then
                        -- Count tempo/time sig markers
                        if #args >= 1 then
                            local count = reaper.CountTempoTimeSigMarkers(args[1])
                            response.ok = true
                            response.ret = count
                        else
                            response.error = "CountTempoTimeSigMarkers requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "PCM_Source_GetSectionInfo" then
                        -- Get PCM source section info
                        if #args >= 2 then
                            local source = args[1]
                            local offset = args[2]
                            -- Note: This is a simplified version - real API has more params
                            -- For video detection, we'll check file extension
                            local filename_result = reaper.GetMediaSourceFileName(source, "")
                            local has_video = false
                            if filename_result and filename_result ~= "" then
                                local ext = filename_result:match("%.([^%.]+)$")
                                if ext then
                                    ext = ext:lower()
                                    has_video = (ext == "mp4" or ext == "mov" or ext == "avi" or 
                                               ext == "mkv" or ext == "webm" or ext == "wmv")
                                end
                            end
                            response.ok = true
                            response.has_video = has_video
                            response.ret = true
                        else
                            response.error = "PCM_Source_GetSectionInfo requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaSourceFileName" then
                        -- Get media source filename
                        if #args >= 2 then
                            local filename = reaper.GetMediaSourceFileName(args[1], args[2])
                            response.ok = true
                            response.ret = filename
                        else
                            response.error = "GetMediaSourceFileName requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetProjectInfo" then
                        -- Get project info (simplified)
                        if #args >= 2 then
                            local proj = args[1]
                            local param = args[2]
                            if param == "PROJECT_FRAMERATE" then
                                -- Get project frame rate (default 30)
                                local fps = 30.0  -- Default
                                response.ok = true
                                response.ret = fps
                            else
                                response.error = "Unknown project info parameter: " .. param
                                response.ok = false
                            end
                        else
                            response.error = "GetProjectInfo requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "SetEditCurPos" then
                        -- Set edit cursor position
                        if #args >= 3 then
                            reaper.SetEditCurPos(args[1], args[2], args[3])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "SetEditCurPos requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "PCM_Source_BuildPeaks" then
                        -- Build peaks for PCM source
                        if #args >= 2 then
                            local ret = reaper.PCM_Source_BuildPeaks(args[1], args[2])
                            response.ok = true
                            response.ret = ret
                        else
                            response.error = "PCM_Source_BuildPeaks requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "UpdateItemInProject" then
                        -- Update item in project
                        if #args >= 1 then
                            reaper.UpdateItemInProject(args[1])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "UpdateItemInProject requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetSet_ArrangeView2" then
                        -- Get/set arrange view
                        if #args >= 4 then
                            local screen_x_start, screen_x_end = reaper.GetSet_ArrangeView2(args[1], args[2], args[3], args[4])
                            response.ok = true
                            response.start_time = screen_x_start
                            response.end_time = screen_x_end
                            response.ret = true
                        else
                            response.error = "GetSet_ArrangeView2 requires 4 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetMediaItemTakeInfo_Value" then
                        -- Get take info value
                        if #args >= 2 then
                            local value = reaper.GetMediaItemTakeInfo_Value(args[1], args[2])
                            response.ok = true
                            response.ret = value
                        else
                            response.error = "GetMediaItemTakeInfo_Value requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "DeleteExtState" then
                        -- Delete extended state
                        if #args >= 3 then
                            reaper.DeleteExtState(args[1], args[2], args[3])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "DeleteExtState requires 3 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetResourcePath" then
                        -- Get REAPER resource path
                        local path = reaper.GetResourcePath()
                        response.ok = true
                        response.ret = path
                    
                    elseif fname == "ShowConsoleMsg" then
                        -- Show console message
                        if #args >= 1 then
                            reaper.ShowConsoleMsg(args[1])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "ShowConsoleMsg requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "ValidatePtr" then
                        -- Validate pointer
                        if #args >= 2 then
                            local ptr = reaper.ValidatePtr(args[1], args[2])
                            response.ok = true
                            response.ret = ptr
                        else
                            response.error = "ValidatePtr requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "GetCurrentProjectInLoadSave" then
                        -- Get current project
                        local proj = reaper.GetCurrentProjectInLoadSave()
                        response.ok = true
                        response.ret = proj
                    
                    elseif fname == "Main_openProject" then
                        -- Open project
                        if #args >= 1 then
                            reaper.Main_openProject(args[1])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "Main_openProject requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetProjectName" then
                        -- Get project name
                        if #args >= 2 then
                            local name = reaper.GetProjectName(args[1], args[2])
                            response.ok = true
                            response.ret = name
                        else
                            response.error = "GetProjectName requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "IsProjectDirty" then
                        -- Check if project is dirty
                        if #args >= 1 then
                            local dirty = reaper.IsProjectDirty(args[1])
                            response.ok = true
                            response.ret = dirty
                        else
                            response.error = "IsProjectDirty requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "GetProjectNotes" then
                        -- Get project notes
                        if #args >= 1 then
                            local notes = reaper.GetProjectNotes(args[1])
                            response.ok = true
                            response.ret = notes
                        else
                            response.error = "GetProjectNotes requires 1 argument"
                            response.ok = false
                        end
                    
                    elseif fname == "SetProjectNotes" then
                        -- Set project notes
                        if #args >= 2 then
                            reaper.SetProjectNotes(args[1], args[2])
                            response.ok = true
                            response.ret = true
                        else
                            response.error = "SetProjectNotes requires 2 arguments"
                            response.ok = false
                        end
                    
                    elseif fname == "MIDI_SetNote" then
                        -- Set MIDI note properties
                        if #args >= 9 then
                            local retval = reaper.MIDI_SetNote(args[1], args[2], args[3], args[4], args[5], args[6], args[7], args[8], args[9])
                            response.ok = retval
                            response.ret = retval
                        else
                            response.error = "MIDI_SetNote requires 9 arguments"
                            response.ok = false
                        end
                    
                    else
                        -- Try generic function call
                        if reaper[fname] then
                            local ok, result = pcall(reaper[fname], table.unpack(args))
                            if ok then
                                response.ok = true
                                response.ret = result
                            else
                                response.error = "Error calling " .. fname .. ": " .. tostring(result)
                            end
                        else
                            response.error = "Unknown function: " .. fname
                        end
                    end
                    
                    -- Write response
                    local response_json = encode_json(response)
                    reaper.ShowConsoleMsg("Sending response " .. i .. ": " .. response_json .. "\n")
                    write_file(numbered_response_file, response_json)
                end
            end
            end)
            
            if not ok then
                -- Error occurred, write error response
                reaper.ShowConsoleMsg("ERROR processing request " .. i .. ": " .. tostring(err) .. "\n")
                local error_response = {ok = false, error = "Bridge error: " .. tostring(err)}
                write_file(numbered_response_file, encode_json(error_response))
            end
            
            -- Always clean up request file
            delete_file(numbered_request_file)
        end
    end
end

-- Main loop
ensure_dir()
reaper.ShowConsoleMsg("REAPER MCP Bridge (File-based, Full API) started\n")
reaper.ShowConsoleMsg("Bridge directory: " .. bridge_dir .. "\n")

function main()
    process_request()
    reaper.defer(main)
end

main()