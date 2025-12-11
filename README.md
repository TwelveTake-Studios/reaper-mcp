# TwelveTake REAPER MCP

A [TwelveTake Studios](https://twelvetake.com) project.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-yellow)](https://buymeacoffee.com/twelvetake)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-support-ff5e5b)](https://ko-fi.com/twelvetake)

A comprehensive Model Context Protocol (MCP) server that enables AI assistants to control REAPER DAW for mixing, mastering, MIDI composition, and full music production workflows.

**Version:** 1.0.0

## Features

- **129 MCP tools** for complete DAW control
- **File-based communication** - reliable, no network dependencies
- **Python and Lua bridge scripts** - choose your preference
- **Full mixing workflow** - tracks, FX, routing, automation
- **MIDI composition** - create items, add notes, batch operations
- **Audio editing** - split, duplicate, fade, position items
- **Mastering helpers** - one-click mastering chain, parallel compression

## Requirements

- REAPER (any recent version)
- Python 3.8+ (for the MCP server)
- An MCP-compatible AI assistant (Claude Code, etc.)

## Installation

### 1. Install the Bridge Script in REAPER

The bridge script runs inside REAPER and handles communication with the MCP server.

1. Copy `reaper_mcp_bridge.lua` to your REAPER Scripts folder:
   - Windows: `%APPDATA%\REAPER\Scripts\`
   - macOS: `~/Library/Application Support/REAPER/Scripts/`
   - Linux: `~/.config/REAPER/Scripts/`
2. In REAPER: **Actions → Show action list → Load ReaScript**
3. Select `reaper_mcp_bridge.lua` and click **Run**

You should see "REAPER MCP Bridge started" in REAPER's console.

### 2. Install the MCP Server

```bash
pip install -r requirements.txt
```

Or install dependencies directly:
```bash
pip install mcp httpx
```

### 3. Configure Your AI Assistant

Add to your MCP configuration (e.g., `~/.claude.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "reaper": {
      "command": "python",
      "args": ["path/to/reaper_mcp_server.py"]
    }
  }
}
```

### 4. Verify Connection

```bash
python test_connection.py
```

## Communication Modes

The MCP server supports two communication modes:

### File-Based (Default)

Uses JSON files for communication. More reliable, no network configuration needed.

```
MCP Server                    REAPER Bridge
    │                              │
    ├── writes request_N.json ────►│
    │                              ├── processes request
    │◄── reads response_N.json ────┤
```

**Bridge directory:** `%APPDATA%\REAPER\Scripts\mcp_bridge_data`

### HTTP Mode (Advanced)

Uses HTTP requests on localhost. Requires additional setup:
- **Lua HTTP bridge**: Requires LuaSocket (install via ReaPack → "sockmonkey")
- **Python HTTP bridge**: Requires Python enabled in REAPER preferences

```bash
# Set environment variable to use HTTP mode
REAPER_COMM_MODE=http python reaper_mcp_server.py
```

**Default port:** 9000

## Quick Start Examples

### Basic Track Operations
```
"How many tracks are in my project?"
"Create a new track called 'Vocals'"
"Set track 0 volume to -6dB"
"Mute track 2"
"Solo the drums track"
```

### Mixing
```
"Add ReaComp to the bass track"
"Set up sidechain compression from the kick to the bass"
"Create a drum bus and route tracks 0-3 to it"
"Add a mastering chain to the master track"
```

### FX and Parameters
```
"What plugins are on track 0?"
"Get the parameters for the compressor on track 1"
"Set the threshold to -20dB"
"Bypass the EQ on the vocal track"
```

### MIDI Composition
```
"Create a 4-bar MIDI item on track 0"
"Add a C major chord at the start"
"Get all the notes in the MIDI item"
"Set the velocity of note 0 to 100"
```

### Transport and Navigation
```
"Play the project"
"Stop playback"
"Set the cursor to 30 seconds"
"Add a marker called 'Chorus' at the current position"
```

### Project Management
```
"What's the project tempo?"
"Set the tempo to 120 BPM"
"Save the project"
"Render to D:/Output/mix.wav"
```

## Tool Reference

### Track Operations (19 tools)

| Tool | Description |
|------|-------------|
| `get_track_count()` | Get total number of tracks (excluding master) |
| `get_track(index)` | Get track info (name, volume, pan, mute, solo) |
| `get_all_tracks()` | Get info for all tracks |
| `get_master_track()` | Get master track info |
| `insert_track(index, name)` | Create a new track |
| `delete_track(index)` | Delete a track |
| `set_track_name(index, name)` | Rename a track |
| `set_track_volume(index, db)` | Set volume in dB |
| `set_track_pan(index, pan)` | Set pan (-1 to 1) |
| `set_track_mute(index, mute)` | Mute/unmute track |
| `set_track_solo(index, solo)` | Solo/unsolo track |
| `set_track_phase(index, invert)` | Invert phase |
| `set_track_width(index, width)` | Set stereo width (0-2) |
| `set_track_color(index, r, g, b)` | Set track color |
| `get_track_peak(index, channel)` | Get current peak level |
| `set_track_as_folder(index, depth)` | Set as folder parent/child |
| `arm_track(index, arm)` | Arm for recording |
| `set_track_input(index, input)` | Set record input |
| `set_track_monitor(index, mode)` | Set monitor mode |

### FX Operations (15 tools)

| Tool | Description |
|------|-------------|
| `track_fx_get_count(index)` | Count FX on track |
| `track_fx_get_list(index)` | List all FX with details |
| `track_fx_add_by_name(index, name)` | Add FX plugin |
| `track_fx_delete(index, fx_index)` | Remove FX |
| `track_fx_get_name(index, fx_index)` | Get FX name |
| `track_fx_get_enabled(index, fx_index)` | Check if enabled |
| `track_fx_set_enabled(index, fx_index, enabled)` | Enable/bypass FX |
| `track_fx_get_num_params(index, fx_index)` | Count parameters |
| `track_fx_get_param_name(index, fx_index, param)` | Get parameter name |
| `track_fx_get_param(index, fx_index, param)` | Get parameter value |
| `track_fx_set_param(index, fx_index, param, value)` | Set parameter value |
| `get_fx_presets(index, fx_index)` | List available presets |
| `get_fx_preset(index, fx_index)` | Get current preset |
| `set_fx_preset(index, fx_index, name)` | Load preset |
| `save_fx_preset(index, fx_index, name)` | Save current settings as preset |

### Routing (9 tools)

| Tool | Description |
|------|-------------|
| `create_send(src, dest)` | Create send between tracks |
| `delete_send(index, send_index)` | Remove a send |
| `set_send_volume(index, send_index, db)` | Set send level |
| `get_track_num_sends(index)` | Count sends from track |
| `set_send_dest_channels(index, send_index, chan)` | Route to specific channels |
| `set_send_source_channels(index, send_index, chan)` | Set source channels |
| `setup_sidechain_send(src, dest, db)` | Create sidechain send |
| `configure_reacomp_sidechain(index, fx_index, use)` | Configure ReaComp sidechain |
| `setup_sidechain_compression(trigger, target, fx, db)` | Complete sidechain setup |

### Transport (10 tools)

| Tool | Description |
|------|-------------|
| `play()` | Start playback |
| `stop()` | Stop playback |
| `pause()` | Pause playback |
| `record()` | Start recording |
| `get_play_state()` | Get current state (playing/paused/recording) |
| `get_cursor_position()` | Get edit cursor position (seconds) |
| `set_cursor_position(seconds)` | Move edit cursor |
| `get_play_position()` | Get playback position (seconds) |
| `toggle_repeat()` | Toggle loop mode |
| `get_repeat_state()` | Check if looping |

### Project (14 tools)

| Tool | Description |
|------|-------------|
| `save_project()` | Save current project |
| `create_project(name)` | Create new project |
| `open_project(path)` | Open project file |
| `get_project_path()` | Get project directory |
| `get_project_name()` | Get project filename |
| `get_project_length()` | Get project length (seconds) |
| `get_tempo()` | Get project tempo (BPM) |
| `set_tempo(bpm)` | Set project tempo |
| `get_time_signature()` | Get time signature |
| `set_time_signature(num, denom)` | Set time signature |
| `render_project(path, start, end, tail)` | Render to audio file |
| `render_region(index, path)` | Render specific region |
| `zoom_to_selection()` | Zoom to time selection |
| `zoom_to_project()` | Zoom to show entire project |

### MIDI Operations (8 tools)

| Tool | Description |
|------|-------------|
| `create_midi_item(track, pos, length)` | Create empty MIDI item |
| `get_midi_item(track, item)` | Get MIDI item info |
| `add_midi_note(track, item, pitch, vel, start, end, chan)` | Add single note |
| `add_midi_notes_batch(track, item, notes)` | Add multiple notes |
| `get_midi_notes(track, item)` | Get all notes |
| `delete_midi_note(track, item, note)` | Delete a note |
| `clear_midi_item(track, item)` | Delete all notes |
| `set_midi_note_velocity(track, item, note, vel)` | Change note velocity |

### Audio Items (17 tools)

| Tool | Description |
|------|-------------|
| `insert_audio_file(track, path, pos)` | Import audio file |
| `get_track_items(track)` | List all items on track |
| `get_item_info(track, item)` | Get item details |
| `set_item_position(track, item, pos)` | Move item |
| `set_item_length(track, item, length)` | Change item length |
| `delete_item(track, item)` | Delete item |
| `duplicate_item(track, item)` | Duplicate item |
| `split_item(track, item, pos)` | Split item at position |
| `set_item_mute(track, item, mute)` | Mute/unmute item |
| `set_item_volume(track, item, db)` | Set item volume |
| `set_item_fade_in(track, item, length)` | Set fade-in |
| `set_item_fade_out(track, item, length)` | Set fade-out |
| `select_all_items()` | Select all items |
| `unselect_all_items()` | Deselect all items |
| `get_selected_items()` | Get selected items |
| `copy_selected_items()` | Copy to clipboard |
| `paste_items()` | Paste from clipboard |

### Markers & Regions (8 tools)

| Tool | Description |
|------|-------------|
| `add_marker(pos, name, color)` | Add marker |
| `add_region(start, end, name, color)` | Add region |
| `get_markers()` | Get all markers |
| `get_regions()` | Get all regions |
| `delete_marker(index)` | Delete marker |
| `delete_region(index)` | Delete region |
| `go_to_marker(index)` | Jump to marker |
| `go_to_region(index)` | Jump to region start |

### Automation (8 tools)

| Tool | Description |
|------|-------------|
| `get_track_envelope(track, name)` | Get envelope by name |
| `get_envelope_point_count(track, name)` | Count envelope points |
| `add_envelope_point(track, name, time, value, shape)` | Add automation point |
| `get_envelope_points(track, name)` | Get all points |
| `delete_envelope_point(track, name, index)` | Delete point |
| `clear_envelope(track, name)` | Clear all points |
| `set_track_automation_mode(track, mode)` | Set automation mode |
| `arm_track_envelope(track, name, arm)` | Arm envelope for recording |

### Selection & Editing (11 tools)

| Tool | Description |
|------|-------------|
| `undo()` | Undo last action |
| `redo()` | Redo last undone action |
| `get_undo_state()` | Get undo/redo state |
| `select_track(index, exclusive)` | Select a track |
| `select_all_tracks()` | Select all tracks |
| `unselect_all_tracks()` | Deselect all tracks |
| `get_selected_tracks()` | Get selected track indices |
| `set_time_selection(start, end)` | Set time selection |
| `get_time_selection()` | Get time selection |
| `clear_time_selection()` | Clear time selection |
| `delete_selected_items()` | Delete selected items |

### Mixing Helpers (6 tools)

| Tool | Description |
|------|-------------|
| `add_mastering_chain()` | Add EQ→Comp→EQ→Limiter to master |
| `add_parallel_compression(track, db)` | Set up NY compression |
| `create_bus(name, tracks)` | Create submix bus |
| `add_eq(track)` | Add ReaEQ |
| `add_compressor(track)` | Add ReaComp |
| `add_limiter(track)` | Add ReaLimit |

### Advanced (4 tools)

| Tool | Description |
|------|-------------|
| `run_action(action_id)` | Run REAPER action by ID |
| `run_action_by_name(name)` | Run action by name |
| `get_track_fx_chunk(track, fx)` | Get raw FX state data |
| `cut_selected_items()` | Cut items to clipboard |

## Track Indexing

- **Regular tracks:** 0-based index (first track = 0)
- **Master track:** Use index `-1`

```
"Set the master track volume to -3dB"  → track_index = -1
"Mute track 1"                          → track_index = 1 (second track)
```

## Common Plugin Names

Use these names with `track_fx_add_by_name()`:

| Plugin | Name |
|--------|------|
| EQ | `ReaEQ` |
| Compressor | `ReaComp` |
| Limiter | `ReaLimit` |
| Gate | `ReaGate` |
| Delay | `ReaDelay` |
| Reverb | `ReaVerbate` or `ReaVerb` |

Third-party plugins use their full name as shown in REAPER's FX browser.

## Troubleshooting

### "Cannot connect to REAPER"
1. Ensure REAPER is running
2. Ensure the bridge script is running (check REAPER's console)
3. For file mode: verify the bridge directory exists
4. For HTTP mode: check port 9000 isn't blocked

### "Track not found"
- Track indices are 0-based
- Use `-1` for master track
- Check track count with `get_track_count()`

### Bridge script won't load
- **Lua:** Ensure LuaSocket is installed (ReaPack → "sockmonkey")
- **Python:** Enable Python in REAPER preferences

### Slow response
- File-based mode has ~50ms latency per call
- Batch operations when possible (e.g., `add_midi_notes_batch`)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REAPER_COMM_MODE` | `file` | Communication mode (`file` or `http`) |
| `REAPER_BRIDGE_DIR` | `%APPDATA%\REAPER\Scripts\mcp_bridge_data` | File bridge directory |
| `REAPER_HOST` | `localhost` | HTTP bridge host |
| `REAPER_PORT` | `9000` | HTTP bridge port |

## License

MIT License - see [LICENSE](LICENSE)

---

**TwelveTake Studios LLC**
Website: [twelvetake.com](https://twelvetake.com)
Contact: contact@twelvetake.com
