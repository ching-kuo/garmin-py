# Implementation Plan: Garmin Connect CLI Data Extractor

## Overview

Build a standalone CLI tool (`garmin-cli`) that extracts health, activity, workout, and performance data from Garmin Connect. The tool wraps the `garth` library, reuses proven patterns from the existing `garmin/` codebase, and outputs data as JSON, table, or CSV. The project is structured as many small, focused modules (max 800 lines each) with immutable data patterns throughout.

## Requirements

- Extract health metrics: sleep, HRV, weight, training readiness, training status, resting HR, body battery, stress, SpO2
- Extract activity data: list with filters, details, weather
- Extract planned workout data: upcoming workouts from calendar, workout step details
- Extract performance/threshold data: lactate threshold, FTP, VO2max, training zones
- CLI with date range (`--from`, `--to`, `--days`), `--limit`, `--format` (json/table/csv), and `--json` shorthand options
- **Default output is table** (human-friendly); agents use `--json` or `--format json` to get machine-readable output
- Auth via env vars (`GARMIN_EMAIL`, `GARMIN_PASSWORD`) or saved garth session
- Python 3.10+, click for CLI, garth for API access
- **Primary consumer: LLM agents** -- this CLI is designed to be invoked as a SKILL by Claude Code and other LLM agents, so JSON output stability and machine-parseable error reporting are first-class concerns

## Project Structure

```
garmin-py/
  pyproject.toml                    # Project metadata, dependencies, entry point
  README.md                         # Usage documentation
  SKILL.md                          # SKILL definition for LLM agent consumers (versioned with CLI)
  src/
    garmin_cli/
      __init__.py                   # Package version
      __main__.py                   # python -m garmin_cli support
      cli.py                        # Top-level click group, global options, exception handler
      auth.py                       # Authentication (resume/login via garth)
      config.py                     # Configuration dataclass, env var loading
      output.py                     # Output formatting (JSON envelope, table, CSV)
      date_utils.py                 # Date range parsing, validation
      serializers.py                # Per-command output normalization/flattening
      endpoints/
        __init__.py
        health.py                   # Sleep, HRV, weight, body battery, stress, SpO2, resting HR, training readiness, training status
        activities.py               # List activities, activity details, weather
        workouts.py                 # Calendar workouts, workout details, list workouts
        performance.py              # Lactate threshold, FTP, VO2max, zones
      commands/
        __init__.py
        health.py                   # click commands for health metrics (incl. readiness, status)
        activities.py               # click commands for activities
        workouts.py                 # click commands for workouts
        performance.py              # click commands for performance/thresholds
  tests/
    __init__.py
    conftest.py                     # Shared fixtures (mock garth, sample data)
    test_auth.py
    test_config.py
    test_output.py
    test_date_utils.py
    test_serializers.py
    test_endpoints/
      __init__.py
      test_health.py
      test_activities.py
      test_workouts.py
      test_performance.py
    test_commands/
      __init__.py
      test_health_cmd.py
      test_activities_cmd.py
      test_workouts_cmd.py
      test_performance_cmd.py
```

Note: Training readiness and training status live inside `endpoints/health.py` and `commands/health.py`. There is no separate `training.py` module -- training metrics are health metrics exposed as `health readiness` and `health status` subcommands.

## CLI Command Structure

### Date Range Semantics

`--days N` always means **past N days** (historical). For future-oriented lookups (workout calendar), use `--ahead N` instead. This removes all ambiguity:

- `--days N` = from `today - (N-1)` to `today` inclusive (N days total, historical, all commands)
- `--ahead N` = from `today` to `today + (N-1)` inclusive (N days total, future, only on `workout calendar`)
- `--from DATE --to DATE` = explicit range (both inclusive)
- `--date DATE` = single day
- Conflicting combinations (`--date` with `--from/--to`, `--days` with `--ahead`, etc.) raise `click.UsageError`

```
garmin-cli [--format table|json|csv] [--json] [--garth-home PATH] COMMAND

  Health Commands:
    garmin-cli health sleep       [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health hrv         [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health weight      [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health body-battery [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health stress      [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health spo2        [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health resting-hr  [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health readiness   [--date DATE] [--from DATE --to DATE] [--days N]
    garmin-cli health status      [--date DATE]

  Activity Commands:
    garmin-cli activity list      [--limit N] [--type TYPE] [--search TEXT]
    garmin-cli activity get       ACTIVITY_ID
    garmin-cli activity weather   ACTIVITY_ID

  Workout Commands:
    garmin-cli workout list       [--limit N]
    garmin-cli workout get        WORKOUT_ID
    garmin-cli workout calendar   [--from DATE --to DATE] [--days N] [--ahead N]

  Performance Commands:
    garmin-cli performance thresholds    [--sport running|cycling|all]
    garmin-cli performance zones         [--sport running|cycling]
    garmin-cli performance vo2max
```

**Examples (human use -- table output by default):**
```bash
# Last 7 days of sleep data (table by default)
garmin-cli health sleep --days 7

# HRV for a specific date range
garmin-cli health hrv --from 2026-03-01 --to 2026-03-10

# List 10 recent running activities as CSV
garmin-cli --format csv activity list --limit 10 --type running

# Upcoming workouts for next 7 days
garmin-cli workout calendar --ahead 7

# All performance thresholds
garmin-cli performance thresholds

# --version and --help work without authentication
garmin-cli --version
garmin-cli health --help
```

**Examples (agent/script use -- explicit JSON):**
```bash
# Use --json shorthand for JSON envelope output
garmin-cli --json health sleep --days 7

# Or use --format json (equivalent)
garmin-cli --format json health hrv --days 7

```

## API Endpoint Mapping

### Health Metrics

| Metric | garth Built-in | Raw Endpoint (fallback) | Status |
|--------|---------------|------------------------|--------|
| Sleep | `garth.DailySleep.list(date, days)` | `/wellness-service/wellness/dailySleep` | Verified (garth docs) |
| HRV | `garth.HRVData.list(date, days)` | `/hrv-service/hrv/{date}` | Verified (garth docs) |
| Weight | `garth.WeightData.list(date, days)` | `/weight-service/weight/dateRange` | Verified (garth docs) |
| Body Battery | None (raw API) | `/wellness-service/wellness/bodyBattery/date/{date}` | UNVERIFIED -- validate at implementation time |
| Stress | None (raw API) | `/wellness-service/wellness/dailyStress/{date}` | UNVERIFIED -- validate at implementation time |
| SpO2 | None (raw API) | `/wellness-service/wellness/pulse-ox/dailySummary/{date}` | UNVERIFIED -- validate at implementation time |
| Resting HR | None (raw API) | `/wellness-service/wellness/dailyHeartRate/{date}` | UNVERIFIED -- validate at implementation time |
| Training Readiness | None (raw API) | `/metrics-service/metrics/trainingreadiness/{date}` | UNVERIFIED -- validate at implementation time |
| Training Status | None (raw API) | `/metrics-service/metrics/trainingstatus/aggregated/{date}` | UNVERIFIED -- validate at implementation time |

**Validation task**: During Phase 2 implementation, each unverified endpoint must be tested with a real Garmin account. If an endpoint returns 404 or unexpected data, document the finding and either fix the endpoint URL or mark the metric as unsupported with a clear error message.

### Activity Endpoints (from existing `extras.py`)

| Function | Endpoint | Notes |
|----------|----------|-------|
| List activities | `/activitylist-service/activities/search/activities` | Uses `limit`, `start`, `activityType`, `search` params only (verified from existing code) |
| Get activity | `/activity-service/activity/{activity_id}` | Verified |
| Activity weather | `/activity-service/activity/{activity_id}/weather` | Verified |

Note: Date filtering for activities is NOT a verified server-side feature. The `list` command does NOT expose `--from/--to` options. If date filtering is needed later, it should be implemented as client-side filtering after pagination, and verified against the Garmin API first.

### Workout/Calendar Endpoints (from existing `api.py` and `extras.py`)

| Function | Endpoint | Status |
|----------|----------|--------|
| List workouts | `/workout-service/workouts` | Verified |
| Get workout | `/workout-service/workout/{workout_id}` | Verified |
| Weekly calendar | `/calendar-service/year/{year}/month/{month}/day/{day}/start/{start}` | Verified |
| Monthly calendar | `/calendar-service/year/{year}/month/{month}` | Verified |

### Performance Endpoints (from existing `api.py`)

| Function | Endpoint | Status |
|----------|----------|--------|
| Lactate threshold | `/biometric-service/biometric/latestLactateThreshold` | Verified |
| Power to weight | `/biometric-service/biometric/powerToWeight/latest/{date}/` | Verified |
| VO2max | `/metrics-service/metrics/maxmet/daily/{date}` or `/fitnessAge-service/fitnessAge` | UNVERIFIED -- validate at implementation time |

## Implementation Phases

### Phase 1: Project Skeleton and Core Infrastructure (8 files)

**Goal:** A working CLI that can output `--version` and `--help` without authentication. All subsequent phases build on this.

1. **Create pyproject.toml**
   - Define project metadata, dependencies (`garth>=0.4`, `click>=8.0`, `tabulate>=0.9`, `python>=3.10`), and entry point `garmin-cli = "garmin_cli.cli:main"`

2. **Create config module** (`src/garmin_cli/config.py`)
   - Frozen `dataclass` `CliConfig` with fields: `email`, `password`, `garth_home` (default `~/.garth`), `output_format` (default `table`)
   - Factory function `load_config()` reads from env vars `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARTH_HOME`

3. **Create auth module** (`src/garmin_cli/auth.py`)
   - `ensure_authenticated(config: CliConfig) -> None` following the pattern from existing `garmin/auth.py`: try `garth.resume()`, fall back to `garth.login()` + `garth.save()`
   - Raise `GarminCliError(error_code="AUTH_FAILED")` or `GarminCliError(error_code="AUTH_MISSING")` (see exception handling section)
   - **NOT called at the group level** -- each command that hits the Garmin API calls `ensure_authenticated()` explicitly. This allows `--version`, `--help`, and all help subcommands to work without credentials
   - After successful `garth.save()`, secure the session directory (see Session Security)

4. **Create date_utils module** (`src/garmin_cli/date_utils.py`)
   - `resolve_date_range(date, from_date, to_date, days, ahead, default_days=1) -> tuple[date, date]`
   - `--days N` always means past N days: `(today - (N-1), today)` inclusive, N days total
   - `--ahead N` always means future N days: `(today, today + (N-1))` inclusive, N days total
   - `--from/--to` is explicit range
   - `--date` is single-day range
   - Conflicting combinations raise `click.UsageError` with a clear message
   - **Hard limit**: Maximum date span of 90 days to prevent request storms. Raise `click.UsageError` if exceeded

5. **Create output module** (`src/garmin_cli/output.py`)
   - `make_envelope(command, data, date_range=None) -> dict` wraps normalized data in the standard JSON envelope `{ok: true, command, date_range, count, data}`
   - `make_error_envelope(command, error, error_code) -> dict` wraps errors in `{ok: false, command, error, error_code}`
   - `echo_json(envelope) -> None` serializes envelope with `json.dumps(envelope, indent=2, default=str)` to stdout
   - `echo_table(data, columns) -> None` renders serialized data as table to stdout. Supports ANSI color/formatting when stdout is a TTY, plain text when piped
   - `echo_csv(data, columns) -> None` renders serialized data as CSV to stdout
   - All JSON output goes through the envelope -- there is NO raw passthrough mode
   - All log/progress messages go to stderr via `click.echo(..., err=True)`

6. **Create serializers module** (`src/garmin_cli/serializers.py`)
   - Per-command serializer functions that normalize Garmin API responses into `list[dict]` with consistent, documented snake_case keys
   - **All serializers return `list[dict]`** -- singleton responses (e.g., `activity get`) are wrapped in a single-element list for uniform handling
   - Each serializer defines a `COLUMNS: tuple[str, ...]` constant for table/CSV rendering
   - Nested objects are flattened with underscore-joined keys (e.g., `hrv_summary_weekly_avg`)
   - Unknown/missing keys produce `None` (rendered as empty in table/CSV)
   - **JSON mode uses serialized data, not raw API responses** -- this ensures snake_case consistency and field stability across versions

7. **Create CLI entry point** (`src/garmin_cli/cli.py`)
   - Top-level `click.Group` with `--format` (choice: table/json/csv, default table), `--json` (boolean flag, shorthand for `--format json`), `--garth-home`, `--version`
   - `--json` flag takes precedence if both `--json` and `--format` are provided
   - Store config in `click.Context.obj` but **do NOT authenticate here**
   - Register command sub-groups (health, activity, workout, performance)
   - **Top-level exception handler** (see Exception Handling section)

8. **Create `__main__.py` and `__init__.py`**
   - `__main__.py`: `from garmin_cli.cli import main; main()`
   - `__init__.py`: `__version__ = "0.1.0"`

### Phase 2: Health Data (2 files)

9. **Create health endpoints** (`src/garmin_cli/endpoints/health.py`)
   - Functions: `get_sleep()`, `get_hrv()`, `get_weight()`, `get_body_battery()`, `get_stress()`, `get_spo2()`, `get_resting_hr()`, `get_training_readiness()`, `get_training_status()`
   - Use garth built-ins where available, raw `garth.connectapi()` as fallback
   - For multi-day raw endpoints, iterate over date range in this layer
   - **Rate limiting**: 0.5s delay between API calls when iterating date ranges, with exponential backoff on 429/5xx (max 3 retries, base 2s)
   - **Endpoint validation**: Each unverified endpoint must be tested during implementation. If 404, investigate and update URL or mark as unsupported

10. **Create health commands** (`src/garmin_cli/commands/health.py`)
    - Subcommands: `sleep`, `hrv`, `weight`, `body-battery`, `stress`, `spo2`, `resting-hr`, `readiness`, `status`
    - Shared decorator for common date range options (`--date`, `--from`, `--to`, `--days`) used by all subcommands except `status`
    - `status` uses only `--date` (single-date, no range decorator)
    - Each command calls `ensure_authenticated()` before hitting the API
    - Each command passes data through the corresponding serializer, then through the output module

### Phase 3: Activity Data (2 files)

11. **Create activity endpoints** (`src/garmin_cli/endpoints/activities.py`)
    - Port from existing `garmin/extras.py`: `list_activities()`, `get_activity()`, `get_activity_weather()`
    - `list_activities()` uses only verified params: `limit`, `start`, `activityType`, `search`
    - **No date filtering** -- unverified server-side feature, not included

12. **Create activity commands** (`src/garmin_cli/commands/activities.py`)
    - Subcommands: `list`, `get`, `weather`
    - `list` accepts `--limit` (default 20, max 100), `--type`, `--search`
    - Each command calls `ensure_authenticated()` before hitting the API

### Phase 4: Workout/Calendar Data (2 files)

13. **Create workout endpoints** (`src/garmin_cli/endpoints/workouts.py`)
    - Port and extend: `list_workouts()`, `get_workout()`, `get_calendar_week()`, `get_calendar_range()`
    - `get_calendar_range()` iterates week-by-week, collects workout items
    - **Bounded pagination**: Max `ceil(span_days / 7) + 1` weekly requests per calendar range (handles partial-week overlap at boundaries). 0.5s delay between calls, exponential backoff on 429/5xx. With 90-day cap, this is at most 14 requests

14. **Create workout commands** (`src/garmin_cli/commands/workouts.py`)
    - Subcommands: `list`, `get`, `calendar`
    - `calendar` accepts `--from/--to`, `--days` (past), and `--ahead` (future)
    - Each command calls `ensure_authenticated()` before hitting the API

### Phase 5: Performance/Threshold Data (2 files)

15. **Create performance endpoints** (`src/garmin_cli/endpoints/performance.py`)
    - Port from existing code: `get_all_thresholds()`, `get_lactate_threshold()`, `get_ftp()`, `get_vo2max()`
    - Zone calculations delegated to pure functions (ported from existing `zones.py`)
    - Build result dicts immutably (no mutation of intermediate dicts)
    - **VO2max endpoint validation**: Unverified -- validate at implementation time

16. **Create performance commands** (`src/garmin_cli/commands/performance.py`)
    - Subcommands: `thresholds`, `zones`, `vo2max`
    - Each command calls `ensure_authenticated()` before hitting the API

### Phase 6: Testing (10+ files)

17. **Test fixtures** (`tests/conftest.py`) - mock garth, sample data, cli runner
18. **Unit tests** for config, auth, output, date_utils, serializers
19. **Endpoint tests** for all endpoint modules (mock `garth.connectapi`)
20. **CLI integration tests** using `click.testing.CliRunner`
21. **Coverage target**: 80%+

**Explicit edge cases to cover:**
- `--version` and `--help` work without authentication (no garth calls)
- Conflicting date options raise `UsageError` (all combinations: `--date` + `--from`, `--date` + `--days`, `--days` + `--ahead`, `--from` without `--to`, etc.)
- Date range exceeding 90 days raises `UsageError`
- CSV output escapes commas, quotes, and newlines in field values
- Table/CSV rendering of nested payloads (flattened correctly)
- Large payloads with many fields (serializer selects only relevant keys)
- API returning HTTP 404 vs empty 200 (different handling: error vs "no data")
- API returning 429 triggers backoff/retry up to 3 times, then fails with clear message
- API returning 5xx triggers backoff/retry, then fails
- Malformed API responses (missing expected keys) produce `None` fields, not crashes
- `--limit 0` or negative limit raises `BadParameter`
- Empty garth session directory (first-time user without credentials)
- JSON envelope structure: every successful command returns `{ok: true, command, data, count}`
- JSON error envelope: every failed command returns `{ok: false, command, error, error_code}`
- Exit code 0 for success (including empty data), exit code 1 for all errors (including usage errors -- no exit 2)
- stdout contains only data output (JSON envelope / table / CSV), stderr contains logs, warnings, progress messages, and error messages (in table/CSV mode)
- JSON and CSV output contains no ANSI escape codes
- Table output uses ANSI color when TTY detected, plain text when piped
- `count` field matches `len(data)` for all responses (data is always a list)
- Singleton responses (activity get, workout get) wrap result in single-element list
- Top-level exception handler catches all exceptions and produces JSON error envelope in JSON mode
- `UsageError` and `BadParameter` produce `INVALID_INPUT` error code and exit 1 (not Click's default exit 2)

### Phase 7: Documentation and SKILL Spec (2 files)

22. **README.md** - Installation, auth setup, command reference, examples
23. **SKILL.md** - Versioned SKILL definition file for LLM agent consumers (see SKILL Integration section). This file lives in the repo root and is updated whenever the CLI command surface or JSON schema changes

## Authentication Flow

```
CLI invoked
  -> cli.py reads --garth-home, stores in Context.obj
  -> --version / --help: responds immediately, NO auth
  -> Any API command (e.g., health sleep):
       1. Command calls ensure_authenticated(config)
       2. Try garth.resume(garth_home)
       3. If fails: check GARMIN_EMAIL + GARMIN_PASSWORD env vars
       4. If present: garth.login(email, password), garth.save(garth_home)
       5. If missing: raise GarminCliError(error_code="AUTH_MISSING")
       6. Secure session directory permissions
       7. Command proceeds with authenticated garth session
```

## Session Security

The `garth_home` directory (default `~/.garth`) contains sensitive authentication tokens:
- **Before both `garth.resume()` and `garth.save()`**: Validate that `garth_home` is not a symlink (`os.path.islink()`). If it is a symlink, reject it with `GarminCliError("AUTH_FAILED", "garth_home path is a symlink -- refusing for security")`
- **Before both `garth.resume()` and `garth.save()`**: If the path exists, verify ownership (`os.stat().st_uid == os.getuid()`) -- refuse if not owned by current user. Check directory has no group/other permission bits (not just read -- any g/o bits are rejected). Attempt to repair to `0o700` with `os.chmod()`. If repair fails, refuse with `GarminCliError("AUTH_FAILED", "garth_home directory has insecure permissions and cannot be repaired")`
- **Before `garth.resume()`**: Also scan session files inside `garth_home`: reject any that are symlinks (`os.path.islink()`), verify ownership matches current user (`st_uid == os.getuid()`), and check no group/other permission bits. Attempt to repair file permissions to `0o600`. If any file fails symlink/ownership checks or permission repair, refuse with `GarminCliError`
- **Before `garth.save()` (new path)**: Create the directory with `os.makedirs(garth_home, mode=0o700, exist_ok=True)` to ensure secure permissions from creation (no race window)
- After `garth.save()`, verify that newly written files have `0o600` permissions. Fix if not
- Never log or echo session file paths in error messages that include token content
- Document in README that `~/.garth` contains sensitive session data

## Exception Handling Strategy

### Custom Exception

Define `GarminCliError(Exception)` with attributes `error: str` and `error_code: str`. All internal error paths raise this exception instead of `click.ClickException`.

### Top-Level Exception Handler

`cli.py` uses `standalone_mode=False` on the Click group and wraps all invocations in an outer `main()` function. This ensures Click does NOT handle its own error printing or exit codes -- everything flows through our handler:

```python
# Pseudocode for cli.py exception handling

# Module-level state captured by the CLI group callback before any command runs
_resolved_format: str = "table"  # updated by cli group callback
_resolved_command: str = "unknown"  # updated by each command before API call

def main():
    try:
        cli(standalone_mode=False)
    except click.exceptions.Exit as e:
        # --help and --version go through here
        sys.exit(e.code)
    except SystemExit as e:
        # --version in some Click versions
        sys.exit(e.code)
    except click.UsageError as e:
        # Parse errors happen before invoke(), so _resolved_format may not be set.
        # Fall back to scanning sys.argv for --json / --format json
        fmt = _resolved_format if _resolved_format != "table" else _sniff_format_from_argv()
        cmd = _resolved_command
        if fmt == "json":
            echo_json(make_error_envelope(cmd, str(e), "INVALID_INPUT"))
        else:
            click.echo(f"Error: {e.format_message()}", err=True)
        sys.exit(1)
    except GarminCliError as e:
        if _resolved_format == "json":
            echo_json(make_error_envelope(_resolved_command, e.error, e.error_code))
        else:
            click.echo(f"Error: {e.error}", err=True)
        sys.exit(1)
    except Exception as e:
        if _resolved_format == "json":
            echo_json(make_error_envelope(_resolved_command, str(e), "INTERNAL_ERROR"))
        else:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)

def _sniff_format_from_argv() -> str:
    """Best-effort format detection from sys.argv for pre-invoke errors."""
    if "--json" in sys.argv:
        return "json"
    try:
        idx = sys.argv.index("--format")
        return sys.argv[idx + 1]
    except (ValueError, IndexError):
        return "table"
```

**Format and command resolution:**
- `_resolved_format` is set by the CLI group callback when `--format` / `--json` is parsed
- `_resolved_command` is set by each command function at entry (e.g., `_resolved_command = "health.sleep"`)
- For pre-invoke parse errors, `_sniff_format_from_argv()` provides best-effort detection
- `command` in error envelopes may be `"unknown"` if the error occurs before command dispatch -- this is the defined behavior for parse-time errors

**`--help` and `--version` behavior:**
- These bypass the exception handler via `click.exceptions.Exit` with code 0
- They always output plain text to stdout regardless of `--json` / `--format`
- This is intentional: `--help` is for humans; agents already know the commands via `SKILL.md`

### Key Behaviors

- **Click's default exit codes are overridden**: All errors exit 1, never 2. This simplifies agent consumption (0 = success, 1 = failure)
- **JSON mode**: Click's default error formatting is suppressed. The exception handler emits a JSON error envelope to stdout instead. stdout always contains exactly one JSON object (success or error)
- **Table/CSV mode**: Errors are printed to stderr as plain text (Click's standard behavior). stdout contains only data or nothing on error
- **stderr may contain log messages in all modes**: But agents should parse stdout only

### Error Code Mapping

| Exception Type | Error Code | When |
|---------------|-----------|------|
| `click.UsageError` | `INVALID_INPUT` | Bad arguments, conflicting options, range exceeded |
| `click.BadParameter` | `INVALID_INPUT` | Invalid param value (bad date format, negative limit) |
| `GarminCliError("AUTH_FAILED")` | `AUTH_FAILED` | Credentials rejected |
| `GarminCliError("AUTH_MISSING")` | `AUTH_MISSING` | No credentials available |
| `GarminCliError("RATE_LIMITED")` | `RATE_LIMITED` | 429 after 3 retries |
| `GarminCliError("SERVER_ERROR")` | `SERVER_ERROR` | 5xx after 3 retries |
| `GarminCliError("NOT_FOUND")` | `NOT_FOUND` | 404 (endpoint unavailable) |
| `GarminCliError("NETWORK_ERROR")` | `NETWORK_ERROR` | Connection/timeout failure |
| `Exception` (unexpected) | `INTERNAL_ERROR` | Bug or unhandled case |

## Rate Limiting and Request Bounds

- **Max date range**: 90 days (enforced in `date_utils.py`)
- **Max activity limit**: 100 per request
- **Inter-request delay**: 0.5s between sequential API calls in date-range iterations
- **Retry policy**: Exponential backoff on 429 and 5xx responses
  - Base delay: 2 seconds
  - Multiplier: 2x per retry
  - Max retries: 3 (delays: 2s, 4s, 8s)
  - Max single delay: 8 seconds
- **Fail-fast**: After max retries, raise `GarminCliError` with appropriate error code
- **Calendar pagination**: Max `ceil(span_days / 7) + 1` weekly requests per calendar range (at most 14 for a 90-day span, accounting for partial-week overlap at boundaries)

## JSON Output Contract (Machine-Readable)

JSON output is activated via `--json` or `--format json`. It is the primary format for LLM agents and scripts. Table is the default for human use.

### Envelope Structure

All JSON output follows a consistent envelope. Success:

```json
{
  "ok": true,
  "command": "health.sleep",
  "date_range": {"from": "2026-03-05", "to": "2026-03-11"},
  "count": 7,
  "data": [
    {"date": "2026-03-05", "duration_hours": 7.2, "deep_min": 45, ...},
    ...
  ]
}
```

Error:

```json
{
  "ok": false,
  "command": "health.sleep",
  "error": "Rate limited by Garmin. Try again later.",
  "error_code": "RATE_LIMITED"
}
```

### Envelope Fields

| Field | Type | Present | Description |
|-------|------|---------|-------------|
| `ok` | `bool` | Always | `true` if succeeded, `false` on error |
| `command` | `str` | Always | Dot-separated command path (e.g., `health.sleep`, `activity.list`). May be `"unknown"` for pre-dispatch parse errors where the command could not be determined |
| `date_range` | `{"from": str, "to": str} \| null` | Success only | Date range if used, `null` otherwise |
| `count` | `int` | Success only | `len(data)` -- always matches the list length |
| `data` | `list[dict]` | Success only | **Always a list**, even for singleton responses. Each dict has consistent snake_case keys |
| `error` | `str` | Error only | Human-readable error message |
| `error_code` | `str` | Error only | Machine-readable error code (see Error Code Mapping) |

### `data` is Always a List

To eliminate ambiguity for consumers:
- Multi-record responses (e.g., `health sleep --days 7`): `data` is a list of N dicts
- Singleton responses (e.g., `activity get 123`): `data` is a list with exactly 1 dict
- Empty responses: `data` is `[]`, `count` is `0`, `ok` is `true`

`count` always equals `len(data)`. There is no `NO_DATA` error code -- empty results are a successful response with `count: 0`.

### Data Normalization

All `data` dicts are produced by serializers, NOT raw API passthrough:
- All keys are snake_case
- Nested objects are flattened with underscore-joined keys
- Fields present in v0.1.0 will not be removed or renamed in minor versions
- New fields may be added in minor versions (additive only)
- The `data` schema for each command is documented in `SKILL.md` and must not change without a major version bump

### Stream Behavior (JSON mode)

- **stdout**: Exactly one JSON object (success or error envelope). No ANSI codes, no TTY detection, no color
- **stderr**: Logging, warnings, progress messages (e.g., "Fetching day 3/7..."). No ANSI codes on stderr either -- plain text only in JSON mode
- **Exit code 0**: Success (including empty data with `count: 0`)
- **Exit code 1**: Any error (auth, network, rate limit, invalid input, internal)

This separation ensures agents can reliably `json.loads(stdout)` without interference.

### Stream Behavior (table mode)

- **stdout**: Formatted table with ANSI color when stdout is a TTY, plain text when piped
- **stderr**: Logging, warnings, error messages. ANSI allowed when stderr is a TTY
- **Exit code 0**: Success (including empty data)
- **Exit code 1**: Any error
- **Empty data**: Prints "No data found for {date range}" to stderr, exit 0
- **Errors**: Prints human-readable error message to stderr, exit 1 (no JSON envelope)

### Stream Behavior (CSV mode)

- **stdout**: CSV data, never ANSI
- **stderr**: Logging, warnings, error messages. No ANSI -- plain text only (CSV is a machine format)
- **Exit code 0**: Success (including empty data)
- **Exit code 1**: Any error
- **Empty data**: Prints "No data found for {date range}" to stderr, exit 0
- **Errors**: Prints human-readable error message to stderr, exit 1 (no JSON envelope)

## Output Normalization Contract

Each command group has corresponding serializer functions in `serializers.py`:

- **JSON mode**: Data is serialized (normalized, flattened, snake_case), then wrapped in the envelope
- **Table mode**: Serialized data rendered with `tabulate`. ANSI color/formatting enabled when stdout is a TTY (headers, borders, etc.), plain text when piped or redirected
- **CSV mode**: Serialized data rendered with `csv.DictWriter` using `csv.QUOTE_MINIMAL`

All three modes use the same serializer output -- the difference is only the presentation format.

Each serializer defines `COLUMNS: tuple[str, ...]` listing fields for table/CSV. JSON mode includes all serialized fields regardless of `COLUMNS`.

Example serializer mapping:
| Command | Serializer | Key columns |
|---------|-----------|-------------|
| health sleep | `serialize_sleep()` | date, duration_hours, deep_min, light_min, rem_min, awake_min, score |
| health hrv | `serialize_hrv()` | date, weekly_avg, last_night, status |
| health weight | `serialize_weight()` | date, weight_kg, bmi, body_fat_pct |
| activity list | `serialize_activity_summary()` | id, date, name, type, distance_km, duration_min, avg_hr |
| workout calendar | `serialize_calendar_workout()` | date, name, type, duration_min, description |
| performance thresholds | `serialize_thresholds()` | sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg |

## LLM Agent / SKILL Integration

This CLI is designed as a tool that LLM agents (Claude Code, etc.) invoke via shell commands. Design decisions that support this:

### Why CLI as a SKILL

- Agents invoke skills via `Bash` tool -- a CLI is the natural interface
- No SDK/library import needed -- any agent that can run shell commands can use this
- JSON envelope means agents can parse output with `json.loads()` without heuristics
- Predictable exit codes let agents distinguish success from failure programmatically

### Agent-Friendly Design Principles

1. **Deterministic output**: Same inputs with `--json` always produce the same JSON structure. No interactive prompts. TTY detection only affects table mode color (not structure)
2. **No pagination in output**: All requested data is returned in a single JSON response. The CLI handles internal pagination (calendar week iteration, etc.) transparently
3. **Atomic commands**: Each command is a single request-response. No stateful workflows or multi-step interactions
4. **Self-describing errors**: Error responses include both human-readable `error` and machine-readable `error_code` so agents can branch on failure type
5. **No ANSI in machine modes**: JSON and CSV modes never include ANSI escape codes on either stdout or stderr. Table mode uses ANSI color when TTY detected (human-friendly) but strips it when piped

### Example SKILL Usage Patterns

An agent calling garmin-cli should always use `--json` to get structured output:

```bash
# Get today's training readiness to decide workout intensity
garmin-cli --json health readiness --date 2026-03-11

# Get last 7 days of HRV to analyze recovery trends
garmin-cli --json health hrv --days 7

# Get upcoming planned workouts to provide coaching advice
garmin-cli --json workout calendar --ahead 7

# Get recent activities for a training log summary
garmin-cli --json activity list --limit 10

# Get thresholds to calibrate zone-based training advice
garmin-cli --json performance thresholds
```

### SKILL Definition File (`SKILL.md`)

The SKILL definition file lives in the repo root at `SKILL.md` and is **versioned alongside the CLI**. It is updated whenever:
- A new command is added
- The JSON schema for any command's `data` changes
- Error codes are added or modified

The file documents:
- All available commands with argument syntax
- The JSON envelope contract
- The `data` schema for each command (field names, types, descriptions)
- Error codes and their meanings
- Example invocations and expected output shapes

This eliminates contract drift risk -- the spec and implementation are always in the same commit.

## Risks and Mitigations

- **garth API version changes**: Pin version in pyproject.toml; wrap built-in calls with raw API fallbacks
- **Undocumented endpoints**: Centralize as module-level constants; single-line fix if they break. Mark unverified endpoints explicitly and validate during implementation
- **Device-specific metrics**: Return empty `data: []` with `count: 0` and log a message to stderr ("this metric may require a compatible Garmin device")
- **Calendar API structure**: Build on existing proven `get_calendar()`, iterate incrementally
- **Rate limiting**: Hard cap at 90-day ranges, 0.5s inter-request delay, exponential backoff on 429/5xx
- **Session security**: Secure directory creation with 0o700, file permissions 0o600, symlink validation, no token content in logs
- **SKILL contract drift**: SKILL.md is versioned in the repo, updated alongside any CLI surface change

## Success Criteria

- [ ] `pip install -e .` works and `garmin-cli --version` prints version (no auth required)
- [ ] `garmin-cli --help` and all subcommand `--help` work without authentication
- [ ] All health subcommands return a valid success or error envelope for single date and date ranges (except `health status` which is single-date only). Unverified endpoints that return 404 produce a clear `NOT_FOUND` error rather than crashing
- [ ] `garmin-cli activity list --limit 5` returns recent activities
- [ ] `garmin-cli workout calendar --ahead 7` returns upcoming planned workouts
- [ ] `garmin-cli performance thresholds` returns LT, FTP, and weight data
- [ ] Default output is table (human-friendly)
- [ ] `--json` flag produces JSON envelope output
- [ ] `--format csv` produces CSV output with proper escaping
- [ ] No ANSI codes in JSON or CSV output
- [ ] Table output uses ANSI color/formatting when stdout is a TTY, plain text when piped
- [ ] Authentication works with both saved session and env vars
- [ ] Session files have secure permissions (dir: 0o700, files: 0o600)
- [ ] All tests pass with 80%+ coverage
- [ ] No file exceeds 800 lines
- [ ] No mutable data patterns
- [ ] Conflicting date options produce clear error messages
- [ ] Rate-limited responses trigger backoff, not infinite loops
- [ ] JSON output uses consistent envelope `{ok, command, data, count, date_range}`
- [ ] `data` is always a list (singletons wrapped in single-element list)
- [ ] `count` always equals `len(data)`
- [ ] Error output uses envelope `{ok: false, command, error, error_code}` in JSON mode
- [ ] stdout contains only data output (JSON envelope / table / CSV), stderr contains logs, warnings, progress, and error messages
- [ ] All errors exit 1, success exits 0 (no exit code 2)
- [ ] CLI is fully non-interactive (no prompts). TTY detection only affects table mode color
- [ ] Top-level exception handler catches all exceptions and produces JSON error envelope
- [ ] SKILL.md is present and documents all commands and data schemas
- [ ] Unverified endpoints are validated during implementation and documented
