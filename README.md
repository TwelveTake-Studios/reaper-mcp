# TwelveTake REAPER MCP

A [TwelveTake Studios](https://twelvetake.com) project.

[![Tools](https://img.shields.io/badge/tools-135-blue)](https://github.com/TwelveTake/reaper-mcp)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-yellow)](https://buymeacoffee.com/twelvetake)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-support-ff5e5b)](https://ko-fi.com/twelvetake)

A comprehensive Model Context Protocol (MCP) server that enables AI assistants to control REAPER DAW for mixing, mastering, MIDI composition, and full music production workflows.

Built by a working producer with 7+ albums released. These aren't theoretical tools—they're battle-tested in real sessions.

**Version:** 1.3.2

## Why This Server

### Workflow Automation, Not Just API Wrappers

Most MCP servers just wrap REAPER's API and call it a day. This one includes **production workflow helpers** that handle multi-step operations in a single call:

| Tool | What it does for you |
|------|---------------------|
| `setup_sidechain_compression()` | Creates send, routes to channels 3-4, configures ReaComp's detector input — complete sidechain setup in one call |
| `add_mastering_chain()` | Adds ReaEQ → ReaComp → ReaEQ → ReaLimit to master track with proper signal flow |
| `add_parallel_compression()` | Creates a bus track, sets up the send, adds compressor — NY-style compression ready to blend |
| `create_bus()` | Creates a submix track and routes your specified tracks to it |
| `get_project_summary()` | Returns track count, all track names/volumes/pans/FX, markers, regions, tempo, time signature — everything your AI needs in one call |

### Zero Configuration

- **File-based communication** works immediately — no network setup, no ports to configure
- **Stock REAPER Lua only** — the bridge script has no dependencies, nothing extra to install in REAPER
- Copy the script, run it, connect your AI assistant

### 158 Tools Covering Real Production Needs

- **Full FX control** — add/remove plugins, get/set any parameter by index, manage presets, bypass
- **FX parameter automation** — automate any plugin knob (flanger depth, filter cutoff, etc.)
- **Complete routing** — sends, receives, sidechain routing to specific channel pairs
- **Automation** — create envelopes, add/edit points, set automation modes
- **MIDI** — create items, add notes individually or in batches, edit velocities
- **Audio items** — import, split, duplicate, fade, position, mute
- **Markers & regions** — create, edit, navigate, render by region

## Requirements

- REAPER (any recent version)
- Python 3.8+ (for the MCP server)
- An MCP-compatible AI assistant

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

#### Alternative: Nix Flake (Optional)

If you use [Nix](https://nixos.org/), the project includes a flake-based dev shell that provides Python 3.12 and automatically creates/activates a virtual environment:

```bash
# Enter the dev shell manually
nix develop

# Or with direnv (recommended — auto-activates on cd):
direnv allow
```

Once inside the shell, install the Python dependencies as usual:
```bash
pip install -r requirements.txt
```

This approach pins the Python version and keeps dependencies isolated without polluting your system.

### 3. Configure Your AI Assistant

Add to your MCP client's configuration (e.g., `.mcp.json`):

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

The **file-based bridge is the supported path** — it is reliable and needs no extra setup.
HTTP mode is **deprecated** (see below).

### File-Based (Default, Recommended)

Uses JSON files for communication. More reliable, no network configuration needed.
This is the only actively maintained path; all tools are guaranteed to work here.

```
MCP Server                    REAPER Bridge
    │                              │
    ├── writes request_N.json ────►│
    │                              ├── processes request
    │◄── reads response_N.json ────┤
```

**Bridge directory:** `%APPDATA%\REAPER\Scripts\mcp_bridge_data`

### HTTP Mode (Deprecated)

> **Deprecated as of v1.2.1.** The HTTP bridges (`reaper_web_server.lua` / `reaper_web_server.py`)
> are kept for existing users but are no longer maintained and will not receive new tools.
> They may be removed in a future major release (v2.0). Use the file bridge instead.

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

### Track Operations (23 tools)

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
| `get_track_peak(index, channel)` | Get current peak level (dB) |
| `get_track_peak_hold(index, channel)` | Get held peak since last reset (dB) |
| `clear_all_peak_indicators()` | Reset peak hold on all tracks |
| `get_track_master_send(index)` | Get master/parent send state |
| `set_track_master_send(index, enabled)` | Enable/disable master send |
| `set_track_as_folder(index, depth)` | Set as folder parent/child |
| `arm_track(index, arm)` | Arm for recording |
| `set_track_input(index, input)` | Set record input |
| `set_track_monitor(index, mode)` | Set monitor mode |

### FX Operations (16 tools)

| Tool | Description |
|------|-------------|
| `track_fx_get_count(index)` | Count FX on track |
| `track_fx_get_list(index)` | List all FX with details |
| `track_fx_add_by_name(index, name, position?)` | Add FX plugin (optionally at position) |
| `track_fx_move(index, fx_index, new_position)` | Reorder FX in the chain |
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

### Take FX Operations (11 tools)

Per-take (per-item) FX, mirroring the track FX tools. Every take is addressed by
`(track_index, item_index, take_index)`.

| Tool | Description |
|------|-------------|
| `take_fx_get_count(track, item, take)` | Count FX on a take |
| `take_fx_get_list(track, item, take)` | List all take FX with details |
| `take_fx_add_by_name(track, item, take, name)` | Add FX plugin to a take |
| `take_fx_delete(track, item, take, fx)` | Remove FX from a take |
| `take_fx_get_name(track, item, take, fx)` | Get take FX name |
| `take_fx_get_enabled(track, item, take, fx)` | Check if enabled |
| `take_fx_set_enabled(track, item, take, fx, enabled)` | Enable/bypass take FX |
| `take_fx_get_num_params(track, item, take, fx)` | Count parameters |
| `take_fx_get_param_name(track, item, take, fx, param)` | Get parameter name |
| `take_fx_get_param(track, item, take, fx, param)` | Get parameter value |
| `take_fx_set_param(track, item, take, fx, param, value)` | Set parameter value |

### Take Management & Comping (7 tools)

Multi-take workflows: list/switch/delete takes, explode/crop, REAPER 7 fixed-lane comping.

| Tool | Description |
|------|-------------|
| `get_takes(track, item)` | List all takes (name + active flag) |
| `get_active_take(track, item)` | Get the active take index |
| `set_active_take(track, item, take)` | Switch which take plays |
| `explode_takes(track, item)` | Explode takes to overlapping items (in place) |
| `crop_to_active_take(track, item)` | Keep only the active take |
| `delete_take(track, item, take)` | Delete a specific take |
| `select_comp_lane(track, lane)` | Play one fixed lane exclusively (lane comping) |

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

### Project (15 tools)

| Tool | Description |
|------|-------------|
| `get_project_summary()` | Get comprehensive project state in one call |
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
| `add_midi_note(track, item, pitch, vel, start_beat, length_beats, chan)` | Add single note (beats) |
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

### FX Parameter Automation (5 tools)

| Tool | Description |
|------|-------------|
| `get_fx_envelope(track, fx, param)` | Get/create envelope for any FX parameter |
| `add_fx_envelope_point(track, fx, param, time, value, shape)` | Add automation point to FX parameter |
| `get_fx_envelope_points(track, fx, param)` | Get all points from FX envelope |
| `delete_fx_envelope_point(track, fx, param, point)` | Delete point from FX envelope |
| `clear_fx_envelope(track, fx, param)` | Clear all points from FX envelope |

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
