# Changelog

## [2.0.0] - 2026-04-12

### Added
- MFA prompt support during interactive `garmin-cli login`
- Token store migration: existing `~/.garth/garmin_tokens.json` is copied into `~/.garminconnect` on first use
- Token file symlink rejection to prevent token material redirection

### Fixed
- `ensure_authenticated` now correctly surfaces non-401/403 probe failures as `AUTH_FAILED` instead of silently falling through to a fresh login attempt
- Symlink check in `ensure_secure_directory` now runs before legacy token migration to prevent writing into symlink targets
- Redundant `_secure_directory` calls removed from login and auth paths (already handled by `backend.save`)

### Changed
- **Breaking:** Replaced the unmaintained `garth` runtime dependency with [`python-garminconnect==0.3.2`](https://github.com/cyberjunky/python-garminconnect) behind a repo-owned compatibility boundary (`src/garmin_cli/backend.py`). `garth` is no longer maintained and had accumulated security debt; `python-garminconnect` provides a native OAuth implementation with active maintenance.
- **Breaking:** Renamed the primary session-home surface to `GARMIN_HOME` / `--garmin-home`; `GARTH_HOME` / `--garth-home` kept as deprecated aliases
- **Breaking:** Switched the default session home from `~/.garth` to `~/.garminconnect`; existing sessions are migrated automatically on first use
- Deduplicated VO2max latest-day filter into shared `select_latest_dated_rows` in serializers
- Moved test-only `CliRunner` compat shim from production `cli.py` to `tests/conftest.py`
- Replaced duplicate `_WEATHER_FIELDS` in MCP server with shared `COLUMNS_ACTIVITY_WEATHER`
- Consolidated `*_fixes*` test files into canonical test suites
- Added a governed raw-fallback registry for workout update paths and migrated workout read/create/delete/schedule helpers onto typed upstream methods where available

## [1.3.0] - 2026-04-09

### Added
- Detail view for activities: `activity get --detail` / `-d` shows extended metrics (max HR, calories, elevation gain/loss, avg/max speed, cadence, power, normalized power, TSS, intensity factor). MCP `activity_get` gains `detail: bool` parameter
- Multisport activity support: `activity get` now detects triathlon/multisport parents and fetches per-sport child activities with distance, duration, HR, pace, and calories
- Date filtering for `activity list`: `--date`, `--days`, `--from`/`--to` options and MCP `start_date`/`end_date` params
- `get_activity_splits` endpoint for activity split data

### Fixed
- `activity get` now displays data for child activities fetched directly (previously showed empty fields because summaryDTO fallback was missing)

### Changed
- Extracted shared `CLICK_DATE_TYPE` and `resolve_click_dates()` to `date_utils.py` (eliminates duplication between health and activity commands)
- Refactored `serialize_activity_summary` onto shared `_normalize_activity_base` / `_iter_activity_pairs` helpers

## [1.2.0] - 2026-04-07

### Added
- MCP server mode (`garmin-cli mcp-server`) exposing 26 read-only tools for Claude Code/Desktop integration
- Tier 1 MCP tools: `health_daily_summary`, `health_steps`, `health_intensity_minutes`, `performance_race_predictions`, `performance_endurance_score`, `performance_hill_score`, `device_list`
- Claude Desktop, Claude Code, and ChatGPT (via MCP bridge) setup instructions in README
- SSE and streamable-http transports for remote MCP clients (`--transport sse|streamable-http`)
- HTTP transport options: `--host`, `--port`, `--sse-path`, `--message-path`, `--streamable-http-path`, `--stateless-http`, `--json-response`
- Transport-aware option validation (rejects HTTP-only options on stdio, cross-transport options between SSE/streamable-http)
- Optional `mcp` dependency group (`pip install "garmin-cli[mcp]"`)
- `login_status` MCP tool for checking auth state without CLI
- MCP Server documentation in SKILL.md and README.md

### Changed
- Upgraded MCP SDK from v1 FastMCP to v2 MCPServer (pinned to pre-release commit until v2 is published on PyPI)
- Narrowed import error handling in `mcp-server` CLI command to only catch mcp-related failures

## [1.1.0] - 2026-03-22

### Added
- Estimated metrics, target validation, and fixed END_CONDITIONS IDs for workout builder

### Changed
- Refactored codebase: removed dead code, consolidated helpers, split cell formatting
- Removed 104 over-engineered tests (683 to 579)

## [1.0.0] - 2026-03-20

### Added
- Initial release with health, activity, workout, and performance commands
- Login command with session management and secure directory handling
- JSON, CSV, and table output formats
- Workout CRUD commands (create, update, delete, schedule)
- SKILL.md for agent/LLM tool integration
- E2E test suite against real Garmin Connect API
- MIT license
