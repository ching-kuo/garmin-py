# Changelog

## [Unreleased]

### Added
- MCP activity write tools reaching parity with the CLI: `activity_download` (writes the file to disk and returns path/size/format -- never raw bytes; refuses to overwrite unless `overwrite=true`), `activity_upload` (reports `status: "rejected"` when Garmin declines an import, matching the CLI contract), and `activity_delete` (destructive-hint annotated). All three emit the same structured write-audit log line as the workout write tools, with file paths reduced to length-only integers.
- `workout unschedule SCHEDULE_ID` (CLI, with confirmation prompt / `--confirm`) and `workout_unschedule` (MCP, destructive-hint annotated): removes a calendar entry created by scheduling while preserving the workout template. Takes the `workoutScheduleId` returned by scheduling, not the workout id.
- `activity rename` / `activity set-type` (CLI) and `activity_rename` / `activity_set_type` (MCP, destructive-hint annotated). `set-type` resolves the sport `typeKey` against Garmin's live sport-type table (no hardcoded list); blank or unknown keys are rejected before any write. Backed by typed `set_activity_name` / `set_activity_type` / `get_activity_types` / `unschedule_workout` upstream methods -- no new raw fallbacks.

### Performance
- `report_snapshot` sections, per-day range reads (`daily-summary`, `body-battery`, `stress`, `spo2`, `resting-hr`, `readiness`, `endurance-score`, `hill-score`), and multisport child fetches now run on bounded thread pools instead of strictly serially. A weekly snapshot drops from ~30 sequential calls (10-20s) to a few seconds. Worker cap is tunable via `GARMIN_CLI_FETCH_CONCURRENCY` (default 4); `GARMIN_CLI_DAILY_CALL_DELAY` still throttles per-day request submission. Result ordering, error semantics (first failure in spec/date order wins; only NOT_FOUND degrades a snapshot section), and the one-auth-probe-per-snapshot behavior are unchanged.
- CLI startup no longer imports the network stack for `--version`/`--help`: command groups are lazy-loaded, cutting cold start from ~0.15s to ~0.06s.
- Token refresh is now serialized behind a process-wide lock (with a refresh-generation guard), preventing concurrent fan-out workers from corrupting the tokenstore or burning a rotated refresh token near expiry.
- The auth probe cache now also skips the per-call tokenstore permission check on cache hits.

### Changed
- Internal: the 917-line `mcp_server.py` god-module is now a thin composition root over a new `garmin_cli.mcp_tools` package (per-domain `register_*_tools` registrars for health, activities, workouts, performance, and misc; shared validation/envelope/auth plumbing in `mcp_tools/_shared.py`). The public entry point `create_mcp_server` and all 34 tool signatures, docstrings, and destructive-hint annotations are unchanged. CLI date-range commands now render through a shared `commands/_options.render_date_range` helper, and vo2max fetching is shared between CLI and MCP via `services/performance.py`.

### Fixed
- `activity zones` / `activity_hr_zones` rows carried a `seconds_in_zone` key that was missing from `COLUMNS_ACTIVITY_HR_ZONES`, so table and CSV output silently dropped it (JSON was unaffected). `seconds_in_zone` is now in the column tuple, ordered before `minutes_in_zone` to match the JSON row order.
- `activity get --detail --laps` on a multisport parent fetched the child-activity list twice -- once to build the `children` envelope, again inside the laps fan-out -- doubling the Garmin API round-trips for that leg of the request. The laps fetch now reuses the already-fetched children.
- `resting-hr` / `health_resting_hr` started failing with `AUTH_FAILED` (and, in `report_snapshot weekly`, failing the whole snapshot) because Garmin now 403s the bare `/wellness-service/wellness/dailyHeartRate/{day}` path. The endpoint now calls the displayName-scoped typed `Garmin.get_heart_rates` method; the response's resting-HR field also changed from `restingHeartRateValue` to `restingHeartRate` (the old key is kept as a fallback).
- Typed activity write calls (download, upload, delete, rename, set-type) previously used the read-path error map, so a Garmin 400 (payload rejection) or 409 (conflict) escaped the retry loop as a raw unclassified exception instead of a `GarminCliError` -- bypassing the MCP write audit and error translation. A new typed-write helper now maps 400/409 to `INVALID_INPUT`, matching the workout write path. A disk-level failure while writing a downloaded activity file is likewise classified (`INTERNAL_ERROR`) so the write audit always emits exactly one event.
- `performance_race_predictions` started 404ing because Garmin now requires the displayName-scoped race-predictions path. The endpoint now calls the typed `Garmin.get_race_predictions` method. The response shape also changed from a list of per-race objects to one flat dict keyed by distance (`time5K`, `time10K`, `timeHalfMarathon`, `timeMarathon`); the serializer now reshapes that into the existing `race_type` / `predicted_time_seconds` / `distance_meters` rows.

## [2.3.0] - 2026-06-16

### Added
- `activity get --detail` now reports `elapsed_time_min` (total wall-clock time, from Garmin's `elapsedDuration`) alongside the existing `duration_min` (moving time), so stopped time is recoverable as `elapsed - moving`. Present in the MCP `activity_get` tool, the CLI's sport-aware detail tables, and the CSV/JSON union schema (appended last to preserve positional CSV back-compat).
- `activity laps` rows now carry per-lap `start_time_gmt` (Garmin's lap `startTimeGMT`) and a derived `start_time_local` (the activity's GMT->local offset applied to each lap; a single offset is used, so rides crossing a DST transition shift post-transition laps by an hour), plus per-lap cadence (`avg_cadence_rpm` for cycling, `avg_cadence_spm` for running). Surfaced in both the CLI `activity laps` command and the MCP `activity_laps` tool.

### Fixed
- `garmin_cli.__version__` (and `garmin-cli --version`) now derives from installed package metadata (`importlib.metadata`) instead of a hardcoded literal, which had silently drifted to `1.2.0` across the 2.0.0/2.1.0/2.2.0 releases. `pyproject.toml` is now the single source of truth; packaging regression tests assert the metadata version, the `garmin-cli --version` output, and the `console_scripts` entry point all stay in lockstep with it.
- Cycling cadence (`avg_cadence_rpm`) was always `null`. The metric read only `averageBikingCadenceInRevPerMinute`, but Garmin emits cycling cadence under `averageBikeCadence` (both in the summary and on each lap). Both keys are now tried, so the activity summary and per-lap rows resolve cadence correctly.
- Sport type (`type`) returned `null` for activities whose top-level `activityType` is null and whose sport is carried only under `activityTypeDTO` (observed on road cycling). The `type` metric, `activity_type_key`, multisport-parent detection, and the capability manifest now fall back to `activityTypeDTO.typeKey`. This also fixes a cascade where the null `type` made the detail `unavailable` manifest mark populated cycling metrics (power, TSS, intensity factor, cadence) as `not_applicable_to_sport`.
- `activity weather` returned `null` for nearly every field. The output column names were being used directly as raw-payload lookup keys, but Garmin's weather feed uses `temp` / `relativeHumidity` / `windDirection` and nests the condition under `weatherTypeDTO`. Weather is now mapped from the real keys and exposes `temperature`, `apparent_temp`, `dew_point`, `humidity`, `wind_speed`, `wind_gust`, `wind_direction`, `wind_direction_compass`, and `condition`. The previously-listed `weatherIconCode` and `precipProbability` fields (absent from Garmin's feed) were removed. Temperature values are in the Garmin account's display unit (often Fahrenheit).

## [2.2.0] - 2026-06-13

### Added
- `report_snapshot` MCP tool: assembles a fixed-shape morning/evening/weekly report in a single call, fanning out the underlying health/activity/performance/workout reads server-side under one auth check. `morning` returns sleep, HRV, readiness, body battery, and today's planned workouts; `evening` returns steps, intensity minutes, stress, body battery, today's activities, and tomorrow's planned workouts; `weekly` returns 7-day sleep/HRV/stress/steps/resting-HR/body-battery trends plus the window's activities, endurance score, and race predictions. `date` defaults to today; the weekly window is the anchor day and the six prior days. Each section is always present in `sections`; a section with no data is an empty list and is noted in `unavailable` with a `reason` (`not_found` / `no_data`) so a report never silently drops a metric. Auth, rate-limit, and server/network failures fail the whole call rather than returning a partial snapshot.
- CLI commands reaching parity with the MCP tool surface: `health steps`, `health daily-summary`, `health intensity-minutes`, `performance race-predictions`, `performance endurance-score`, `performance hill-score`, `device list` (new `device` group), and `activity metrics-describe`. Each wires the same endpoint/serializer/columns the matching MCP tool already used, so CLI and MCP emit identical rows.
- Activity lifecycle commands: `activity download ACTIVITY_ID [--fmt original|tcx|gpx|kml|csv] [--output PATH] [--force]` writes the activity file to disk (never binary to stdout, refuses to overwrite without `--force`, default name `activity_<id><ext>`); `activity upload FILE` (.fit/.gpx/.tcx) surfaces the new activity id; `activity delete ACTIVITY_ID [--confirm]` mirrors `workout delete`'s confirmation UX. Backed by typed `download_activity` / `upload_activity` / `delete_activity` wrappers with format/extension/file validation.
- HTTP request timeouts on every Garmin API call (all verbs, login and resume paths), default 30s, overridable via `GARMIN_CLI_HTTP_TIMEOUT`. Retry backoff delays overridable via `GARMIN_CLI_RETRY_DELAYS`, and the per-day fan-out delay via `GARMIN_CLI_DAILY_CALL_DELAY`; all invalid values fall back to defaults.
- Auth probe caching for long-lived MCP sessions: a successful session probe is cached per `garth_home` and reused within `GARMIN_CLI_AUTH_PROBE_TTL` seconds (default 600, `0` restores per-call probing), removing the redundant disk-read + live probe on every tool call. Cache is invalidated on probe/auth failure, login, and home change.
- GitHub Actions CI (ruff + mypy + pytest across Python 3.10/3.11/3.12, plus an mcp-extra job) and `[tool.ruff]` / `[tool.mypy]` configuration.
- MCP write tools for workouts: `workout_create`, `workout_schedule`, `workout_update`, `workout_delete`. The schedule, update, and delete tools carry the SDK `destructive_hint=True` annotation so MCP clients know to confirm before invoking. Create and update accept `dry_run=True` to preview the resolved wire payload without writing -- `workout_create` dry-runs skip the Garmin API entirely; `workout_update` dry-runs perform one read (`get_workout`) to compute the merged payload but perform no write. Validation errors surface as a single envelope row `{ok: false, error_code: "INVALID_INPUT", errors: [...]}`. Each write invocation emits one structured stderr log line via `WriteLogEvent`; workout name and description are reduced to length-only integers so PII never lands in logs.
- `workout_update` MCP tool uses merge semantics (matching the existing `garmin-cli workout update` CLI behavior): pass only the fields you want to change; the existing record's read-only fields (`workoutId`, `ownerId`, `createdDate`, `atpPlanId`) are preserved via `merge_workout_payload`'s deepcopy.
- `mcp-server` subcommand now defaults `--host` to `127.0.0.1` for SSE and streamable-http transports. Non-loopback binds (`0.0.0.0`, any external interface) require the `GARMIN_MCP_BEARER_TOKEN` environment variable to be set; when set, the server wires the MCP SDK's `TokenVerifier` / `AuthSettings` middleware so all tools (read and write) require `Authorization: Bearer <token>` on every request. Empty / whitespace-only token values are rejected at startup with a clear error. Loopback binds and the `stdio` transport are unchanged -- no auth gating applies there.
- New module `garmin_cli.mcp_auth.StaticBearerTokenVerifier` implements the SDK's `TokenVerifier` protocol with `hmac.compare_digest` for constant-time comparison; the token value is read once at startup and never logged.

### Changed
- The backend singleton (`_backend` / `_garth_home`) is now guarded by an `RLock`. The MCP SDK dispatches synchronous tool functions to `anyio` worker threads, so shared client state is reachable from concurrent threads; the lock prevents a data race on `_set_backend`.
- `serializers.py` (~1000-line god-module) split into a `serializers/` package mirroring `endpoints/` (`health`, `activities`, `workouts`, `performance`, `devices`, `_common`). `serializers/__init__.py` re-exports the complete prior surface so every existing import keeps working unchanged.
- Health, performance, and device serializers migrated onto a declarative `FieldTable` projection (the pattern previously confined to activity metrics), with import-time validation guarding column/field-table drift. Output shapes are byte-identical; `body_battery`, `stress`, `vo2max`, and `zones` stay custom where their logic isn't a flat projection.
- Shared `services/activities.py` layer owns the multisport laps fan-out and capability-manifest assembly previously duplicated between the CLI and MCP front-ends; MCP read tools collapsed onto `_run_tool`/`_authenticated` helpers and write tools onto a `_write_audit` context manager (log events unchanged).
- MCP transport plumbing (the `mcp-server` command, transport options, auth resolution, validation) moved out of `cli.py` into `mcp_cli.py`; `cli.py` is again just the entrypoint (392 → 145 lines).
- Cross-layer imports cleaned up: pace/lactate helpers moved to a neutral `garmin_cli.units` module (endpoints no longer import private serializer helpers); `extract_status_code` moved to `garmin_cli.exceptions`. Duplicate unit converters deduplicated into `units` after byte-identical verification.
- Per-command Click option duplication collapsed behind a shared `date_range_options` decorator; `--limit` validation unified across `activity list` and `workout list`.
- Post-review consolidations (no behavior change): env-var float parsing (HTTP timeout, auth probe TTL, daily-call delay) shares a single `garmin_cli._env._env_float`; the 401/403/404 immediate-fail policy is a shared `_AUTH_NOT_FOUND_ERRORS` base map across the `_make_*` request helpers; and the `report_snapshot` fatal-code denylist became a one-entry `_SNAPSHOT_RECOVERABLE_CODES` allowlist so unknown error codes fail the snapshot safely.

### Removed
- The shadow top-level `garmin/` package (`api.py`, `auth.py`, `zones.py`, `extras.py`) -- a pre-v2.0.0 `garth`-based prototype superseded by `garmin_cli`, imported by nothing in the CLI or MCP server. `pyproject.toml` package discovery now scopes to `src/garmin_cli` only, so wheels ship only `garmin_cli`.
- The stale `workout_description_update` entry from `backend.RAW_FALLBACKS`; it documented the deleted prototype and duplicated the live `workout_update` raw-transport entry.

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
