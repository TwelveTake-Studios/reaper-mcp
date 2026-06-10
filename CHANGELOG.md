# Changelog

All notable changes to TwelveTake REAPER MCP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.3.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.3.0
[1.2.1]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.2.1
[1.2.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.2.0
[1.1.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.0.0
