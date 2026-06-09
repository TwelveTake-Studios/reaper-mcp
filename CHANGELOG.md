# Changelog

All notable changes to TwelveTake REAPER MCP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.2.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.2.0
[1.1.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/TwelveTake-Studios/reaper-mcp/releases/tag/v1.0.0
