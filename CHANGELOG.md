# Changelog

All notable changes to TwelveTake REAPER MCP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.2] - 2026-08-04

**Install-breaking fix. If you installed 1.6.1, upgrade.**

### Fixed
- **A fresh install of 1.6.1 could not start.** The `mcp` dependency was declared as
  `mcp>=1.2.0` with no upper bound. `mcp` 2.0.0 was published, it moved or removed
  `mcp.server.fastmcp`, and this server imports that at module scope, so any new install
  resolved to a version that raised `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`
  before doing anything at all. Existing installs with an older `mcp` already present were
  unaffected, which is exactly why it was not noticed: the development environment had 1.28.0
  pinned. Now capped at `mcp>=1.2.0,<2.0`. *(Lee Saenz ([@fadelabs](https://github.com/fadelabs))
  capped this in his fork on 2026-07-30, before it broke anything here.)*

## [1.6.1] - 2026-08-04

Reliability and reach. No new tools; 176 total. **The bridge changed - reinstall
`reaper_mcp_bridge.lua` in REAPER**, and this release will tell you so instead of failing
in obscure ways: the server now checks the deployed bridge's version and refuses to run
against a stale one. `twelvetake-reaper-mcp --install-bridge` does the deploying for you.

**With thanks to [@SNChicago](https://github.com/SNChicago), whose
[PR #9](https://github.com/TwelveTake-Studios/reaper-mcp/pull/9) diagnosed and fixed two
contract bugs ported here, and whose report prompted the wider audit behind this release.**

**And to Lee Saenz ([@fadelabs](https://github.com/fadelabs)), whose independent audit in the
MIT-licensed [fadelabs/reaper-mcp](https://github.com/fadelabs/reaper-mcp) fork found four of
the bugs fixed below before this project did**, and specified the fixes: `track_fx_get_list`
returning track info instead of an FX list (naming `GetTrackFXList` and the exact
`TrackFX_GetCount` + `TrackFX_GetFXName` + `TrackFX_GetEnabled` shape shipped here);
`create_project`'s `name` parameter being inert, with the recommendation to remove it;
`insert_audio_file` needing a real bridge handler, which his fork calls `InsertAudioFile` as
this one now does; and the shifted-argument track naming bug whose remaining cases were
`create_bus` and `add_parallel_compression`. @SNChicago credited that fork in PR #9, which is
how it was found. The implementations here were written independently, but the diagnoses were
his first, and he had never opened an issue or PR here to say so.

**And to Caio Lins ([@caio-soundraw](https://github.com/caio-soundraw)), who identified the
macOS bridge-path failure in February 2026**, six months before the fix below, working around
it with a wrapper that resolved `~/Library/Application Support/REAPER/Scripts/mcp_bridge_data`
and logged the resolved directory, which is the same path and the same diagnostic this release
builds in. He also independently fixed the MIDI call-path bugs in his fork.

**Breaking:** `create_project`'s `name` parameter is removed. It never had any effect, and
callers still passing it are ignored rather than errored, but the published input schema
changes.

### Fixed
- **macOS and Linux users could not connect at all.** The bridge directory was built from a
  Windows-only `%APPDATA%` string, which does not expand on POSIX. It collapsed into a single
  relative directory name, got created in whatever folder the MCP client happened to be in,
  and the server spent every call talking to a directory REAPER had never heard of. Every
  call timed out after 5 seconds and the error blamed the bridge script, which was the one
  thing that was fine. The path is now resolved per platform, mirroring the bridge's own
  `GetResourcePath()`. The Windows path is byte-identical to before, so existing installs
  see no change. *(Identified by @caio-soundraw in February 2026, six months before this fix.)*
- **The wheel did not contain the bridge script.** `uvx twelvetake-reaper-mcp`, the install
  in the README, handed you a server and no bridge, unpacked into a throwaway cache with no
  path to dig it out of. Step 1 of the documented install could not be performed by the
  documented install method.
- **`track_fx_get_list` did not return an FX list.** It documented an `fx` array of index,
  name and enabled state, but called `GetTrackInfo`, whose payload carries only `fx_names`:
  bare strings, no index, no bypass state. Read-before-write on an FX chain was impossible,
  and a bypassed plugin was indistinguishable from an active one. It now has its own handler
  returning `fx[{index, name, enabled, offline}]` plus `fx_count`. *(Diagnosed and fixed by
  @SNChicago in PR #9, who credited @fadelabs' audit, which had named both the bug and this
  exact fix first.)*
- **`create_project(name)` ignored the name and saved your project instead.** The name was
  never sent to REAPER. Worse, passing one triggered a stray `Main_SaveProject`, which is a
  plain Ctrl+S: on a brand-new untitled project REAPER either raises a modal Save dialog,
  which blocks the bridge until a human clicks it, or writes a file nobody asked for. The
  save is gone. *(Diagnosed by @SNChicago in PR #9; @fadelabs' audit independently reached the
  same recommendation to remove the parameter.)*
- **`create_bus` and `add_parallel_compression` never named the bus.** A spurious leading
  argument shifted every other argument along, landing the name where the write flag belongs,
  where it coerced to false. The call became a silent read: the bus was created, kept its
  default name, and the tool reported success. Both now report an error if naming fails,
  including the index of the track they left behind. *(The remaining cases of the shifted-argument
  bug @fadelabs' audit reported against `insert_track`.)*
- **`insert_audio_file` ignored `track_index` and `position` entirely.** It called ReaScript's
  `InsertMedia(file, mode)`, which takes two arguments, with four, so both simply fell off the
  end. Audio landed on whatever track happened to be selected, at the edit cursor, and the tool
  reported success. It now has a bridge handler that aims the track and position deliberately
  and then restores your selection and cursor. *(Diagnosed by @fadelabs, whose fork added an
  `InsertAudioFile` handler under that same name six weeks before this one.)*
- **`get_project_name` always returned an empty string.** The bridge read the name out of the
  second return value, but the underlying call writes into a buffer and returns the name as the
  first, so both the `ret` and `name` fields were empty for every caller since the tool existed.
  The `get_project_path` handler two doors down had always done this correctly.
- **`get_track` never returned the `volume_db` and `pan` it has documented since 1.0.** They
  were simply absent from the payload, and nothing else exposed single-track volume or pan
  either: the only way to read them was `get_project_summary`, for the whole project at once.
  Both are now returned, along with `volume` in linear form.
- **`add_fx_envelope_point` returned a boolean in a field called `point_index`.** Feeding that
  into `delete_fx_envelope_point` coerced `true` to `1`, so you deleted envelope point 1 rather
  than the point you had just added. It now resolves and returns the real index, and reports
  failure instead of claiming success.
- **A small number could silently shorten a call.** The bridge's JSON decoder rejected
  scientific notation, so `1.2e-05` (which is what a -100 dB gain becomes) decoded to nothing,
  punched a hole in the argument array, and Lua's length operator stopped at the hole. The
  call arrived with arguments missing rather than failing.
- **A comma inside a name split one argument into two.** The array scanner was not
  string-aware, so a track called `Gtr, DI` shifted every argument after it.
- **A request the bridge could not parse produced silence.** No response was written at all,
  so the server sat out its full timeout and then reported the wrong cause. Malformed requests
  now get an immediate, named error.
- **The bridge stole focus from the arrange view on every call.** `ShowConsoleMsg` raises the
  console window. Per-call logging is now off by default; errors and the startup banner still
  print. Set `REAPER_MCP_DEBUG=1` to get it back.

### Known, not fixed
- The bridge still probes 1000 files per timer tick while idle, roughly 30,000 failed file
  opens per second on REAPER's UI thread. A directory-enumeration fix was written and then
  reverted during live testing: it makes the per-tick cost scale with the number of files in
  the bridge directory, and orphaned `response_N.json` files accumulate there (a timed-out
  call leaves its response behind until that slot recycles), so round-trip time degraded from
  0.07s to 0.53s with only 60 stale files present and got worse from there. Fixing this
  properly means bounding that directory or changing the request-file protocol, and a protocol
  change has to ship on both halves at once.

### Added
- `twelvetake-reaper-mcp --install-bridge [DIR]` copies the bridge script into REAPER's
  Scripts folder, backing up any existing copy. Explicit and opt-in: the server never writes
  into your REAPER installation on its own. `--version` and `--help` also added.
- A bridge version handshake. The server probes the deployed script once per session and
  refuses to run against one older than it needs, naming the fix, rather than failing later
  with a confusing per-tool error. REAPER being closed is not mistaken for a stale bridge.
- Timeout errors now include the resolved bridge directory, which turns "it just times out"
  into a one-look diagnosis.
- The server refuses to start against a bridge directory that cannot work, and logs the
  directory it resolved to stderr at startup.

### Changed
- `requires-python` is now `>=3.10`, and the 3.8/3.9 classifiers are gone. CI has only ever
  tested 3.10 and up; the old claim gave 3.8 users a clean install and a broken runtime.
- Platform path resolution is now covered by tests that run everywhere, so a `%APPDATA%`-class
  regression fails a test rather than waiting for a user to report it. A macOS and Windows CI
  matrix that exercises this on each platform, plus a job asserting the wheel contains the
  bridge script, is written but not yet enabled on the public repo.
- The bridge's JSON decoder, the FX list response shape, and the tools/list payload size are
  now covered by tests that run without REAPER.

### Removed
- `create_project`'s `name` parameter. See the breaking note above.

## [1.6.0] - 2026-07-17

MIDI Utilities: 13 tools for editing notes that already exist. **The bridge changed — reinstall
`reaper_mcp_bridge.lua` in REAPER.**

Every new tool takes the same optional filter — a pitch range, an onset window in beats from the
item start, and a channel — so you can target a phrase without selecting anything by hand. Timing
is in beats, pitch in semitones, and each tool is a single undo step.

### Added
- `transpose_midi_notes` — shift pitch. A note pushed outside 0-127 is left where it is and
  reported in `skipped`; it is never wrapped to another octave or dropped.
- `snap_midi_notes_to_scale` — snap off-key notes onto a scale. 14 named scales (plus `ionian` /
  `aeolian` / `natural_minor` aliases) or a custom list of intervals. `nearest` breaks a tie
  toward the middle of the selection, so a line does not drift; `up`/`down` skip rather than
  fall back to the other direction.
- `quantize_midi_notes` — snap onsets to the **project** bar/beat grid, so notes land where the
  ruler says a 16th is. `strength` tightens partway; `swing` pushes the off-beats late.
- `nudge_midi_notes` — shift notes in time; lengths preserved.
- `stretch_midi_notes` — scale timing about a fixed pivot (half-time, double-time, any ratio);
  the phrase keeps its rhythm while changing speed.
- `legato_midi_notes` — run each note's end to the next onset, or set every note to one length.
  Never shortens in `connect` mode, and leaves gaps wider than `max_gap_beats` as rests.
- `humanize_midi_notes` — seeded gaussian timing + velocity jitter. The RNG runs on the server,
  not in REAPER, so the same take with the same seed is byte-identical every time.
- `strum_midi_notes` — roll a chord out into a strum; invents no notes.
- `ramp_midi_note_velocities` — linear velocity ramp across a phrase; notes sharing an onset get
  one velocity, so a chord stays a chord.
- `scale_midi_note_velocities` — multiply, set, or compress velocities toward a pivot.
- `set_midi_note` — edit one note's pitch, velocity, timing or channel.
- `get_selected_midi_notes` — read the notes selected in REAPER's editor.
- `remove_overlapping_midi_notes` — trim or delete overlapping same-pitch notes. The only tool
  here that removes notes, and the only one flagged `destructive`. Chords, the same pitch on
  another channel, and notes that merely touch are never treated as overlaps.

### Changed
- Every MIDI note returned by the server now carries **`start_beat` / `end_beat`** — the note's
  position in beats from its item's start — alongside the existing `start_time` / `end_time`
  seconds. These feed the new tools' beat filters exactly, so a position you read back can be
  passed straight into a filter. Added to `get_midi_notes` too; no existing field was removed.
- Timing throughout is computed in quarter-notes rather than seconds, so the tools behave
  correctly on tempo-mapped projects.

### Removed
- Five dead MIDI handlers that no tool could reach (`QuantizeItem`, `TransposeMIDINotes`,
  `QuantizeMIDINotes`, `HumanizeMIDITiming`, `AnalyzeMIDIPattern`). They were unreachable from
  every public entry point, so no shipped behaviour changes. Among them: a "quantize" that
  returned `ok` without touching a note, and a humanize with a hardcoded PPQ that silently
  restretched notes.

## [1.5.1] - 2026-07-05

Documentation release. No changes to the server, tools, or bridge — you do **not** need to
reinstall `reaper_mcp_bridge.lua`.

### Changed
- README: removed a non-technical credential sentence from the introduction, and fixed the
  tools badge link (`TwelveTake` → `TwelveTake-Studios`).

## [1.5.0] - 2026-06-22

Wire-contract fix. **The bridge changed; reinstall `reaper_mcp_bridge.lua` in REAPER** so empty
list responses serialize correctly. Shipped as a minor (not a patch) because it changes the JSON
shape of responses.

### Fixed
- Empty list fields serialized as `{}` (a JSON object) instead of `[]`. The bridge JSON encoder
  inferred array-ness from `#v > 0`, which is false for an empty table, so any empty list response
  came back as an object — affecting `fx_names`, `tracks`, `items`, `markers`, `regions`, `takes`,
  MIDI `notes`, envelope `points`, MIDI `distribution`, and the empty results of `get_markers` /
  `get_regions` / `get_selected_tracks` / `get_selected_items`. Strict consumers that type-check or
  compare `== []` broke on the wrong shape. Fixed with an array-marker metatable (`as_array`) so
  tagged tables always encode as arrays even when empty; all 20 array-construction sites that can
  reach the client empty are tagged. The change is additive — unmarked empty tables still encode as
  `{}`, so genuine objects are unaffected. Covered by a new headless encoder regression test.

## [1.4.2] - 2026-06-19

Bug-fix release. **The bridge changed; reinstall `reaper_mcp_bridge.lua` in REAPER for the
`get_track_items` fix.**

### Fixed
- `get_track_items` / `get_selected_items` crashed (bridge error: `GetTakeName` "MediaItem_Take
  expected") on any item with no active take — they passed the *item* to `GetTakeName`, which only
  accepts a take. Now guarded: empty-take items return a blank name instead of erroring. Found by
  exercising `explode_takes` against a real multi-take project.
- `run_action_by_name` did not resolve named commands: it passed the name straight to
  `Main_OnCommandEx` (which expects a numeric id), so named commands (`_RS...`, SWS `_SWS_...`)
  silently did nothing. Now resolves via `NamedCommandLookup` first and returns a clean "not found"
  error if unknown; numeric command-id strings run directly.

## [1.4.1] - 2026-06-19

Bug-fix release: four pre-existing tool bugs surfaced by a new live-REAPER regression suite,
including a `delete_track` data-loss bug. **The bridge changed — reinstall
`reaper_mcp_bridge.lua` in REAPER to pick up the `track_fx_get_name` and
`set_midi_note_velocity` fixes.**

### Fixed
- **`delete_track` deleted the wrong track (data loss).** It sent a spurious leading `0` to the
  bridge `DeleteTrack` handler, which reads its first argument as the track index — so it always
  deleted **track 0**, ignoring the index passed. Now sends the index directly. Found by the
  live-REAPER test suite.
- `insert_track`'s `name` argument silently did nothing (the same leading-`0` mistake in its
  `GetSetMediaTrackInfo_String` call named track 0 with a bogus field). Now names the inserted
  track correctly.
- `track_fx_get_name` returned an error instead of the FX name. Its bridge handler required 4
  arguments while the tool sends 3 (the 4th, buffer size, is optional and defaults to 256); the
  handler now requires 2 (track + fx index), matching its own error message and the take-FX
  equivalent. Found by the new live-REAPER test suite.
- `set_midi_note_velocity` never worked: it sent raw indices through `MIDI_SetNote` (which the
  bridge passed straight to an API expecting a take pointer) and its five `None` placeholder
  arguments collapsed below the handler's arg-count guard. Now routes through a new
  `SetMIDINoteVelocity` bridge handler that resolves the MIDI take and sets only the velocity.

## [1.4.0] - 2026-06-16

### Added — ReaEQ band control (5 tools)
Dedicated ReaEQ control: `find_eq`, `get_eq_bands`, `set_eq_band`, `get_eq_band_enabled`,
`set_eq_band_enabled`. Read and set EQ bands in real units — frequency in Hz, gain in dB, Q —
with REAPER-formatted values returned for readability.

Band API and tool design from [@nuxero](https://github.com/nuxero)'s
[PR #6](https://github.com/TwelveTake-Studios/reaper-mcp/pull/6). The bridge had no EQ
handlers, so those were added (`TrackFX_GetEQParam`, `TrackFX_SetEQParam`, `TrackFX_GetEQ`,
`TrackFX_GetEQBandEnabled`, `TrackFX_SetEQBandEnabled`, `TrackFX_GetFormattedParamValue`), and
the gain dB↔normalized mapping was extended against live REAPER 7.x to span ReaEQ's full
boost/cut range. Live-verified end to end.

### Added — Nix flake dev shell
A flake-based development shell (`nix develop`, or auto-activated via direnv) that pins
Python 3.12 and manages a virtualenv. From [@nuxero](https://github.com/nuxero)'s
[PR #7](https://github.com/TwelveTake-Studios/reaper-mcp/pull/7), broadened to all four default
systems with the venv tooling aligned to Python 3.12. Verified on **x86_64-linux** (the shell
builds; Python 3.12, pip, virtualenv, and the venv hook all work). The macOS (**Darwin**) shells
evaluate but have **not** been tested — no macOS host was available.

## [1.3.2] - 2026-06-12

Bug-fix release completing the generic-fallback sweep started in v1.3.1: a systematic audit
of every tool's bridge call path found 16 more silently broken tools (calling nonexistent
API names, or pointer-requiring APIs the generic fallback cannot service). 158 tools.

### Fixed
- **Bridge JSON decoder corrupted Windows paths.** Escape sequences were unescaped with
  sequential replacements and no `\\` handling, so any path segment starting with
  `r`, `n`, `t`, `b`, or `f` after a backslash was mangled (e.g. `...\Temp\reaper.wav`
  rendered to `...\Temp\_eaper.wav` via a stray carriage return). Now a single-pass
  decoder that consumes `\\` atomically. Affected every string argument crossing the
  bridge on Windows.
- **MIDI:** `delete_midi_note`, `clear_midi_item`, `get_midi_item`.
- **Item editing:** `split_item` (returns the new right-half item index),
  `duplicate_item` (via action 41295).
- **Envelopes:** `add_envelope_point` (its handler only accepted a raw envelope pointer,
  which the server never sends — it never worked), `get_envelope_point_count`,
  `get_envelope_points`, `delete_envelope_point`, `clear_envelope`,
  `arm_track_envelope` (ARM via state chunk — REAPER has no direct API).
- **Project:** `get_undo_state` (via `Undo_CanUndo2`/`Undo_CanRedo2`),
  `set_time_signature` (tempo/time-sig marker at project start),
  `render_project` (sets render file/bounds/format, renders dialog-free via action 42230;
  `.wav` extension selects WAV output). New explicit `overwrite` parameter: an existing
  target file returns a clean error unless `overwrite=True` — REAPER's own behavior on
  existing files (prompt vs auto-increment) is a user preference, and its overwrite
  prompt blocks unattended rendering.
- `get_fx_presets` now returns the preset count + current preset (REAPER's API cannot
  enumerate preset names — documented in the response).

### Changed
- `save_fx_preset` and `render_region` now return **clear documented errors** instead of
  silent failures: REAPER's API cannot save named FX presets (workaround suggested), and
  region rendering is deferred to the v1.9 render suite (workaround: `render_project`
  with explicit bounds).

## [1.3.1] - 2026-06-10

Bug-fix release — **with thanks to Héctor Zelaya ([@nuxero](https://github.com/nuxero)),
whose [PR #1](https://github.com/TwelveTake-Studios/reaper-mcp/pull/1) diagnosed the broken
call paths and contributed several of the fixes and tools ported here, and to
[@freke70](https://github.com/freke70), whose
[issue #3](https://github.com/TwelveTake-Studios/reaper-mcp/issues/3) independently diagnosed
the same MIDI call-path bugs and the startup `__name__` override.** 158 tools total.

### Fixed
- `create_midi_item`, `add_midi_note`, `add_midi_notes_batch`, `get_midi_notes`,
  `get_item_info`, all six `set_item_*` tools, and `get_track_peak` were silently broken:
  they called raw REAPER API names that fell through to the bridge's generic fallback,
  which cannot resolve track/item/take pointers from indices. All now route through
  explicit bridge handlers. *(Diagnosis and several fixes from @nuxero's PR #1; the MIDI
  call-path bugs were also reported independently by @freke70 in issue #3.)*
- `add_midi_note` / `add_midi_notes_batch` now use **musical timing in beats**
  (`start_beat`, `length_beats`) instead of the former PPQ arguments — clearer for AI use
  and matching the bridge's actual time-based semantics. (Signature change is treated as a
  fix: the previous tools never worked.)
- Removed the module-level `__name__` override that prevented
  `python reaper_mcp_server.py` from starting (the `if __name__ == "__main__"` guard could
  never fire; only the pip console script worked). *(Independently reported by @freke70 in
  issue #3.)*

### Added *(from PR #1, @nuxero)*
- `track_fx_add_by_name` optional `position` argument (insert anywhere in the chain).
- `track_fx_move` — reorder FX within a track's chain.
- `get_track_peak_hold` / `clear_all_peak_indicators` — peak-hold metering for gain staging.
- `get_track_master_send` / `set_track_master_send` — control the master/parent send.

## [1.3.0] - 2026-06-10

**Takes & Take FX** — 18 new tools (135 → 153), fully backward compatible. The multi-take
release: per-take FX control and take management/comping. All tools live-verified against
REAPER 7.74.

### Added — Takes & comping (Phase B, 7 tools)
- `get_takes`, `get_active_take`, `set_active_take` — list and switch takes by
  `(track_index, item_index, take_index)`.
- `explode_takes` (action 40642, in place), `crop_to_active_take` (40131),
  `delete_take` (40129) — action IDs verified against live REAPER 7.74.
- `select_comp_lane` — REAPER 7 fixed-lane comping via the `C_LANEPLAYS` track attribute
  (no mouse-dependent actions); errors clearly if the track is not in fixed-lane mode.

### Added — Take FX (Phase A, 11 tools)
- Per-take (per-item) FX control mirroring the `track_fx_*` tools, using REAPER's `TakeFX_*`
  API. Every take is addressed by `(track_index, item_index, take_index)`:
  `take_fx_get_count`, `take_fx_get_list`, `take_fx_add_by_name`, `take_fx_delete`,
  `take_fx_get_name`, `take_fx_get_enabled`, `take_fx_set_enabled`, `take_fx_get_num_params`,
  `take_fx_get_param_name`, `take_fx_get_param`, `take_fx_set_param`.
- New conventions for new tools (from v1.3.0 onward): tool annotations
  (read-only / destructive / idempotent hints) and input validation on index arguments.

### Changed
- `pyproject.toml`: bumped `mcp` floor to `>=1.2.0` (guarantees the `ToolAnnotations` API).

## [1.2.1] - 2026-06-09

Infrastructure release — no tool contract changes.

### Added
- Mocked pytest suite (`tests/`) that exercises tools without REAPER running.
- GitHub Actions CI (ruff + pytest on Python 3.10–3.13).
- `dev` optional-dependency group and `ruff` configuration in `pyproject.toml`.

### Changed
- Rewrote `test_connection.py` to test the **file bridge** (the supported path) instead
  of the deprecated HTTP server. Now pure standard library — no `httpx` needed to smoke-test.
- Documented the file-based Lua bridge as the only supported communication path.

### Deprecated
- HTTP bridges (`reaper_web_server.lua` / `reaper_web_server.py`). Kept for existing users
  but no longer maintained; they will not receive new tools and may be removed in v2.0.

## [1.2.0] - 2026-06-09

### Added
- FX parameter automation tools (5): `get_fx_envelope`, `get_fx_envelope_points`,
  `add_fx_envelope_point`, `delete_fx_envelope_point`, `clear_fx_envelope` — read and write
  automation envelopes for individual FX parameters.
- `.github/PULL_REQUEST_TEMPLATE.md` for contributors.

### Changed
- Updated `reaper_mcp_bridge.lua` with handlers for the new FX envelope tools.
- Hardened `.gitignore` (ignores `.claude/` and local tooling artifacts).

Total tools: **135**.

## [1.1.0] - 2025-12-14

### Added
- `get_project_summary()` — one-call overview of project state (tracks, tempo, markers, length).
- GitHub sponsorship links (Buy Me a Coffee, Ko-fi).
- README "highlights" section.

Total tools: **130**.

## [1.0.0] - 2025-12

### Added
- Initial public release: **129 MCP tools** for controlling REAPER DAW.
- Track operations, FX control, routing/sidechain, transport, project management,
  MIDI composition, audio item editing, markers/regions, automation, selection/editing,
  and mixing/mastering helpers.
- File-based communication bridge (default) plus optional HTTP mode
  (Lua and Python in-REAPER servers).

[1.6.2]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.6.2
[1.6.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.6.1
[1.6.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.6.0
[1.5.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.5.1
[1.5.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.5.0
[1.4.2]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.4.2
[1.4.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.4.1
[1.4.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.4.0
[1.3.2]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.3.2
[1.3.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.3.1
[1.3.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.3.0
[1.2.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.2.1
[1.2.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.2.0
[1.1.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.0.0
