# Contributors

People outside the project whose work is in the product. Listed by first contribution.

Because releases are published from a private working repo (see `CONTRIBUTING.md`), external
work is ported by hand rather than merged, and before v1.6.1 that left no trace in the commit
history at all. This file exists so the record is somewhere durable. From v1.6.1 onward
contributors are also added as co-authors on the published commit.

---

### Héctor Zelaya, [@nuxero](https://github.com/nuxero)

The largest external contribution to this project, across three releases.

- **[PR #1](https://github.com/TwelveTake-Studios/reaper-mcp/pull/1)** and
  [issue #2](https://github.com/TwelveTake-Studios/reaper-mcp/issues/2) - diagnosed the broken
  call paths behind `create_midi_item`, `add_midi_note`, `add_midi_notes_batch`,
  `get_midi_notes`, `get_item_info`, all six `set_item_*` tools and `get_track_peak`, which were
  calling raw REAPER API names that fell through to a generic fallback unable to resolve
  track/item/take pointers. Contributed several of the fixes and tools. Shipped in **v1.3.1**.
- **[PR #6](https://github.com/TwelveTake-Studios/reaper-mcp/pull/6)** - the ReaEQ band API and
  tool design behind `find_eq`, `get_eq_bands`, `set_eq_band`, `get_eq_band_enabled` and
  `set_eq_band_enabled`, including the dB to normalized gain mapping. Shipped in **v1.4.0**.
- **[PR #7](https://github.com/TwelveTake-Studios/reaper-mcp/pull/7)** - the Nix flake dev
  shell (`flake.nix`), pinning Python and managing a virtualenv via `nix develop` or direnv.

### [@freke70](https://github.com/freke70)

- **[Issue #3](https://github.com/TwelveTake-Studios/reaper-mcp/issues/3)** - independently
  diagnosed the same MIDI call-path bugs as PR #1, plus the module-level `__name__` override
  that stopped `python reaper_mcp_server.py` from starting at all. Shipped in **v1.3.1**.

### [@SNChicago](https://github.com/SNChicago)

- **[PR #9](https://github.com/TwelveTake-Studios/reaper-mcp/pull/9)** - found that
  `track_fx_get_list` returned a full track-info payload instead of the documented FX array, so
  callers had no FX index to address and no way to distinguish a bypassed plugin from an active
  one, and contributed the dedicated bridge handler that fixes it. Also found that
  `create_project`'s `name` parameter was never used, and that the call it gated saved an
  untitled project. Shipped in **v1.6.1**, along with a wider audit the report prompted.

---

## Work in forks that this project has benefited from

Nobody below opened a PR or an issue here. Their work was found by going and looking, which is
the only reason it is credited at all, and is a reason to keep looking.

### Lee Saenz, [@fadelabs](https://github.com/fadelabs)

An independent audit of this project in the MIT-licensed
[fadelabs/reaper-mcp](https://github.com/fadelabs/reaper-mcp) fork, written up in
`AUDIT-FIXES.md`. It found **four of the bugs fixed in v1.6.1 before this project did**, and
specified the fixes rather than only reporting symptoms:

- `track_fx_get_list` returning track info instead of an FX list, naming `GetTrackFXList` as the
  fix and the exact `TrackFX_GetCount` + `TrackFX_GetFXName` + `TrackFX_GetEnabled` per-FX shape
  that shipped here.
- `create_project`'s `name` parameter being inert, with the recommendation to remove it, which
  is what v1.6.1 did.
- `insert_audio_file` needing a real bridge handler. His fork's handler is called
  `InsertAudioFile`, the same name this one now uses, written six weeks earlier.
- The shifted-argument track naming bug, reported against `insert_track`, whose remaining
  unfixed cases here were `create_bus` and `add_parallel_compression`.

His fork also carries security work on the HTTP bridge, JSON decoder depth and size guards, and
request-id collisions. The v1.6.1 implementations were written independently, but the diagnoses
were his first. @SNChicago credited this fork in PR #9, which is how it was found.

### Caio Lins, [@caio-soundraw](https://github.com/caio-soundraw)

Identified the macOS bridge-path failure in **February 2026**, six months before v1.6.1 fixed
it. His fork works around it with a wrapper resolving
`~/Library/Application Support/REAPER/Scripts/mcp_bridge_data` and logging the resolved
directory and whether it exists, which is the same path and the same diagnostic v1.6.1 builds
into the server. He also independently diagnosed and fixed the MIDI call-path bugs, reaching
the same time-based `InsertMIDINote` and `CreateMIDIItem` routing that shipped in v1.3.1.
