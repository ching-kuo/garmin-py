# Changelog

## [Unreleased]

## [2.1.0] - 2026-05-11

### Added
- Sport-aware activity detail: `activity get --detail` and MCP `activity_get(detail=True)` now project metrics scoped by the activity's `activityType.typeKey`. Cycling activities surface the full power suite (avg/max/normalized power, TSS, intensity factor); running activities surface running dynamics (ground contact time, vertical oscillation, vertical ratio, stride length); pool-swim activities surface SWOLF, total strokes, average stroke rate, and distance per stroke. Run/bike training response (aerobic/anaerobic training effect, vO2max, recovery time) surfaces for both.
- `activity laps <id>` CLI subcommand and MCP `activity_laps` tool: return lap-by-lap rows for run/bike activities, per-pool-length rows for pool-swim activities. Pool swim auto-routes to the typed `get_activity_typed_splits` backend method; everything else uses the existing splits endpoint. Multisport parents (triathlon etc.) fan out across child legs and stamp a 0-based `leg_index` on every returned row.
- `--laps` flag on `activity get` for combining detail + laps in a single envelope.
- `activity zones <id>` CLI subcommand and MCP `activity_hr_zones` tool: return per-zone time-in-zone breakdown using the typed `get_activity_hr_in_timezones` backend method.
- MCP `activity_metrics_describe` tool: returns the dynamic metric descriptor schema (key, unit, metricsIndex) of an activity's detail stream via the typed `get_activity_details` backend method. Useful for LLM agents that want to inspect what a watch recorded before requesting samples.
- Capability manifest (`unavailable` field on `activity_get(detail=True)` JSON envelope and MCP response): annotates registry-known metrics with one of two reasons — `not_applicable_to_sport` (the metric is not meaningful for the activity's sport) or `absent_in_response` (the metric is sport-applicable but missing from the upstream payload). Multisport parent envelopes union per-child manifests with `leg_index` attached to each entry. Empty manifests are omitted; tables print a counts-only footnote.
- Metric registry foundation (`src/garmin_cli/metrics/`): single declarative source of truth for metric keys, source paths, sport applicability, formatting, and detail level. CLI columns, MCP responses, and capability manifests all derive from registry entries.
- New typed backend-adapter wrappers: `get_activity_typed_splits`, `get_activity_hr_in_timezones`, `get_activity_details`. These call typed methods on the python-garminconnect adapter rather than raw URL strings, eliminating URL-casing risk.
- E2E coverage for the new surfaces (`tests/e2e/test_activities_e2e.py`, `tests/e2e/test_mcp_e2e.py`): `activity get --detail/--laps`, `activity laps`, `activity zones`, MCP `activity_get(detail=True)` manifest, `activity_laps`, `activity_hr_zones`, `activity_metrics_describe`, plus multisport laps fan-out (asserts ≥2 distinct `leg_index` values).

### Changed
- `activity get --detail` JSON output is now sport-aware: every union-schema key is present with `null` for sport-inapplicable metrics so consumers see a stable shape regardless of activity type. CSV output uses a stable union-schema header — every cycling key from the legacy `COLUMNS_ACTIVITY_DETAIL` order is preserved in the same position; running and swim columns are appended additively. Table output is sport-aware and shows only sport-applicable columns to keep tables dense.
- `COLUMNS_ACTIVITY_DETAIL` is regenerated from the metric registry's union schema. Legacy cycling-leaning keys keep their relative positions; new sport-specific keys are appended.
- Internal cleanup: trimmed unused `MetricEntry` fields (`label`, `unit`, `detail_level`, `available_in`), unused `SportProfile` fields (`is_pace_sport`, `deep_metrics`), test-only registry helpers (`lookup`, `at_detail`, `project`), and dead serializer constants. Consolidated duplicated `activity_type_key` helpers behind a shared public function in `endpoints/activities.py`. No user-facing surface changed.

### Deferred
- `activity_swim_lengths` MCP tool — `activity_laps` already routes pool-swim activities to per-pool-length rows; a dedicated swim-only tool will ship if a use case differentiates it.
- `activity_metrics_series` MCP tool — down-sampling policy and `max_samples` defaults need real-payload profiling first; `activity_metrics_describe` ships as the descriptor-only subset.
- Hardware-detection and profile-config manifest reasons (`requires_hardware`, `requires_profile_config`) — gated on a future profile/threshold fetch.
- FIT-file download path for L/R balance, torque effectiveness, pedal smoothness, and per-length swim stroke detail.
- Computed NP/IF/TSS client-side fallback when FTP is unset.

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
