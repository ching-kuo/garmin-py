# garmin-py

Garmin Connect for AI assistants and the command line. garmin-py exposes your health, activity, workout, and performance data as an **MCP server** (Claude Desktop, Claude Code, and any other MCP client) and as a **CLI** (`garmin-cli`) with table, JSON, and CSV output.

Read tools cover sleep, HRV, stress, body battery, training status/load, activities (including raw per-sample streams), planned workouts, race predictions, and personal records; write tools create and schedule structured workouts and manage activities. `coach_snapshot` assembles bounded recovery, load, execution, and calendar facts for AI coaching, while `training_plan_reconcile` links prescribed workouts to completed activities. The existing `report_snapshot` remains available for fixed morning, evening, and weekly reports.

## Quick Start: Claude Desktop (one-click)

1. Download `garmin-py-<version>.mcpb` from the [latest release](https://github.com/ching-kuo/garmin-py/releases/latest).
2. Open it with Claude Desktop (or drag it into Settings → Extensions).
3. Enter your Garmin Connect email and password when prompted — they are stored in the operating system keychain, never in the conversation.

On first launch the bundle creates a private virtual environment under `~/.garmin-py/mcpb/` and installs the matching `garmin-py` release from PyPI (internet required once). Requirements: Python 3.10+ on `PATH` (macOS ships 3.9 — install from [python.org](https://www.python.org/downloads/) or Homebrew).

If your account uses multi-factor authentication, the first tool call reports `MFA_REQUIRED`; Claude asks for the one-time code and completes the login with the `submit_mfa_code` tool. The session is saved, so this normally happens once.

## Quick Start: Claude Code

```bash
uv tool install "garmin-py[mcp]"
garmin-cli login
claude mcp add --transport stdio garmin -- garmin-cli mcp-server
```

See [MCP Server](#mcp-server) for other clients, HTTP transports, and the manual Claude Desktop config, and [SKILL.md](SKILL.md) for the full tool reference.

## CLI Installation

From PyPI (the distribution is `garmin-py`; the installed command is `garmin-cli`):

```bash
pip install garmin-py
```

Or from a local checkout:

```bash
pip install .
```

Verify the installation:

```bash
garmin-cli --version
```

## Authentication

`garmin-cli` authenticates via the maintained [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) backend. The primary session-home surface is now `GARMIN_HOME` / `--garmin-home`; `GARTH_HOME` / `--garth-home` remains as a deprecated compatibility alias.

### Interactive login (recommended)

```bash
garmin-cli login
# Email: your@email.com
# Password: (hidden)
# Login successful. Token store saved at: ~/.garminconnect/garmin_tokens.json
```

Use `--email` / `--password` to skip the prompts (useful for scripting):

```bash
garmin-cli login --email your@email.com --password yourpassword
```

Check login status at any time:

```bash
garmin-cli login status
# Logged in. Token store at: ~/.garminconnect/garmin_tokens.json

garmin-cli --json login status
# {"ok": true, "command": "login status", "count": 1, "data": [{"authenticated": true, "garmin_home": "..."}]}
```

### Environment variables (alternative)

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
garmin-cli health sleep --days 1
```

| Variable | Default | Description |
|----------|---------|-------------|
| `GARMIN_EMAIL` | — | Account email for credential-based login |
| `GARMIN_PASSWORD` | — | Account password for credential-based login |
| `GARMIN_CLI_HTTP_TIMEOUT` | `30` | HTTP request timeout in seconds (float); invalid or non-positive values fall back to `30` |
| `GARMIN_CLI_RETRY_DELAYS` | `2,4,8` | Comma-separated retry delay sequence in seconds (e.g. `1,2,4`); invalid values fall back to `2,4,8` |
| `GARMIN_CLI_AUTH_PROBE_TTL` | `600` | Seconds to cache a successful auth probe in the MCP server (float); `0` disables caching and probes on every call |
| `GARMIN_CLI_DAILY_CALL_DELAY` | `0.5` | Delay in seconds (float) between request submissions for endpoints that fan out one request per day (e.g. `daily-summary`); invalid or negative values fall back to `0.5` |
| `GARMIN_CLI_FETCH_CONCURRENCY` | `4` | Worker cap for concurrent fan-out fetches (per-day ranges, report snapshot sections, multisport children); invalid or non-positive values fall back to `4` |

### Custom session directory

```bash
garmin-cli --garmin-home /path/to/session login
garmin-cli --garmin-home /path/to/session health sleep --days 1
```

The default session directory is `~/.garminconnect`. It is created with `0o700` permissions. Symlinks are rejected. Do not share this directory.

New sessions are stored as `garmin_tokens.json` inside `GARMIN_HOME`. If you still have an existing `~/.garth/garmin_tokens.json`, the CLI will copy it into the new default home on first use. `GARTH_HOME` / `--garth-home` still work as deprecated aliases when you need to keep an older path explicitly.

## Output Formats

All commands default to table output. Use `--json` or `--format csv` to change:

```bash
garmin-cli health sleep --days 7              # table (default)
garmin-cli --json health sleep --days 7       # JSON envelope
garmin-cli --format csv health sleep --days 7 # CSV
```

**JSON envelope structure:**

```json
{
  "ok": true,
  "command": "health sleep",
  "date_range": {"from": "2026-03-05", "to": "2026-03-11"},
  "count": 7,
  "data": [
    {"date": "2026-03-05", "bedtime": "2026-03-04T23:10:00", "wake_time": "2026-03-05T06:25:00", "duration_hours": 7.2, "score": 78, ...}
  ]
}
```

**Error envelope:**

```json
{
  "ok": false,
  "command": "health sleep",
  "error": "Rate limited by Garmin. Try again later.",
  "error_code": "RATE_LIMITED"
}
```

Exit code is always `0` on success, `1` on error.

## Commands

### Health

```bash
garmin-cli health sleep            [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health hrv              [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health weight           [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health body-battery     [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health stress           [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health spo2             [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health resting-hr       [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health readiness        [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health status           [--date DATE]
garmin-cli health steps            [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health daily-summary    [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health intensity-minutes [--date DATE | --from DATE --to DATE | --days N]
```

`health daily-summary` makes one API call per day — large date ranges may be slow.

`health status` returns Garmin's full training-load picture for the day: training status, acute/chronic load, acute:chronic workload ratio (ACWR), the chronic-load "tunnel", monthly load-focus buckets with their targets, and load-balance status.

### AI coach

```bash
garmin-cli --json coach snapshot [--date DATE] [--baseline-days N] [--recent-daily-days N]
                                  [--include-extended-daily-baselines] [--sport TYPE]...
```

The default snapshot uses the 28 prior days for ranged signals and activities, nine prior days plus the current date for daily resting-HR and stress calls (leaving slack over the seven-sample baseline minimum for days without data), and at most 30 upstream requests. Baseline medians exclude the current date and require seven valid samples; the resting-HR and stress signals report the shorter daily window they were actually fetched over. Missing and stale values remain explicit in `data_quality`; the server returns neutral facts and does not assign a proprietary readiness score or decide whether a workout is safe.

Extended daily baselines are rejected if their estimated cost exceeds the 30-request cap. A terminal rate limit stops further Garmin calls while preserving completed sections with `complete: false` and `aborted: true`.

### Activities

```bash
garmin-cli activity list             [--limit N] [--type TYPE] [--search TEXT] [--date DATE | --from DATE --to DATE | --days N]
garmin-cli activity get              ACTIVITY_ID [--detail] [--laps]  # --detail/-d shows sport-aware metrics; --laps appends lap data
garmin-cli activity laps             ACTIVITY_ID  # per-lap rows (run/bike: HR, power, cadence, start_time_gmt/local) or per-pool-length rows (lap_swimming)
garmin-cli activity zones            ACTIVITY_ID  # HR time-in-zone breakdown
garmin-cli activity weather          ACTIVITY_ID  # temperature, apparent temp, dew point, humidity, wind, condition
garmin-cli activity metrics-describe ACTIVITY_ID  # metric descriptors: key, unit, metricsIndex
garmin-cli activity detail-metrics   ACTIVITY_ID [--metric KEY]...  # raw per-sample time series (one row per sample)
garmin-cli activity download         ACTIVITY_ID [--fmt original|tcx|gpx|kml|csv] [--output PATH] [--force]
garmin-cli activity upload           FILE         # .fit / .gpx / .tcx
garmin-cli activity delete           ACTIVITY_ID [--confirm]
garmin-cli activity rename           ACTIVITY_ID NEW_NAME
garmin-cli activity set-type         ACTIVITY_ID TYPE_KEY  # e.g. running, cycling
```

`--limit` defaults to 20, max 100. `--type` filters by activity type key (e.g., `running`, `cycling`).

`activity detail-metrics` returns the raw recorded sample stream (~2000 rows for a typical activity; columns are the watch's metric keys such as `directTimestamp`, `directHeartRate`, `directPower`). Use repeatable `--metric` flags to select columns — `activity metrics-describe` lists what a given activity recorded. This is the data for intra-activity analyses such as first-half vs second-half aerobic decoupling.

`activity download` writes the activity file to disk (it never prints binary to stdout). `--fmt` defaults to `original` (the FIT file inside a ZIP archive); the default output name is `activity_<id><ext>` in the current directory, and an existing file is not overwritten unless `--force` is given. `activity delete` prompts for confirmation unless `--confirm` is passed. `activity set-type` accepts any `typeKey` from Garmin's live sport-type table (an unknown key is rejected before any write).

#### Detailed sport-specific metrics

`activity get --detail` projects metrics scoped by the activity's sport:

| Sport | Detail-mode metrics (in addition to base summary, HR, calories, elevation, speed, elapsed time) |
|-------|-----------------------------------------------------------------------------------|
| Cycling | avg/max/normalized power, cadence (rpm), TSS, intensity factor, training effect, vO2max, recovery time |
| Running | cadence (spm), ground contact time, vertical oscillation/ratio, stride length, training effect, vO2max, recovery time |
| Lap swimming | SWOLF, total strokes, average stroke rate, distance per stroke, training effect |
| Open water swimming | universal extras + training effect (no per-length stroke metrics) |

Every sport also carries the universal training-response fields: `training_effect_label` (Garmin's primary-benefit label such as `TEMPO`), `training_load` (per-activity EPOC-based load), and `workout_id` (the structured workout the activity executed, linking plan to execution). `training_load` also appears in `activity list` rows.

`duration_min` is moving time; `elapsed_time_min` is total wall-clock time, so `elapsed - moving` is the time stopped.

JSON and CSV output use a stable union schema — every key is present (with `null` for sport-inapplicable metrics) so downstream parsers see a stable shape. Table output is sport-aware: only sport-applicable columns appear, keeping tables dense.

When `--detail` is set, JSON also carries an `unavailable` array describing which registry-known metrics are not produced for this activity. Each entry has `field`, `reason` (`not_applicable_to_sport` or `absent_in_response`), and `leg_index` (set on multisport child contributions). Table output prints a single counts-only footnote; CSV output stays a flat tabular format and does not carry the manifest.

```bash
# Cycling detail
garmin-cli activity get 12345678 --detail

# Running detail with HR zones
garmin-cli activity get 12345678 --detail
garmin-cli activity zones 12345678

# Pool-swim per-length rows (auto-routes to typed_splits)
garmin-cli activity laps 12345678

# Cycling detail + lap power suite in one envelope
garmin-cli --json activity get 12345678 --detail --laps
```

### Workouts

```bash
# Read
garmin-cli workout list     [--limit N]
garmin-cli workout get      WORKOUT_ID
garmin-cli workout calendar [--from DATE --to DATE | --days N | --ahead N]

# Write
garmin-cli workout create   FILE                   # JSON or YAML file
garmin-cli workout create   --stdin                # read JSON from stdin
garmin-cli workout update   WORKOUT_ID FILE        # partial update (only fields provided change)
garmin-cli workout delete   WORKOUT_ID [--confirm] # --confirm skips interactive prompt
garmin-cli workout schedule WORKOUT_ID DATE        # DATE = YYYY-MM-DD
garmin-cli workout unschedule SCHEDULE_ID [--confirm] # removes a calendar entry; SCHEDULE_ID is the workoutScheduleId returned by schedule
```

`--ahead N` shows the next N days of planned workouts (future-facing). `--days N` shows past N days.

YAML input is supported out of the box. See [SKILL.md](SKILL.md) for the full workout JSON schema reference and step/target types.

### Performance

```bash
garmin-cli performance thresholds
garmin-cli performance zones
garmin-cli performance vo2max
garmin-cli performance race-predictions
garmin-cli performance endurance-score [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance hill-score      [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance personal-records
```

`performance endurance-score` and `performance hill-score` make one API call per day — large date ranges may be slow.

`performance personal-records` returns all-time PRs (fastest 1 km through marathon, longest run/ride, biggest climb, best 20-min power, step records) with a human-readable `label`; typeIds Garmin has not documented publicly carry `label: null` with the raw value.

### Devices

```bash
garmin-cli device list  # registered devices: device_id, display_name, device_type, last_sync_time
```

## Normalized JSON Schemas

Recent fixes normalized several JSON payloads for agent-safe output:

- `performance vo2max` returns `date`, `vo2max`, `sport`
- `performance zones` returns `sport`, `lt_hr_bpm`, `lt_pace`
- `workout calendar` includes compatibility `id` plus explicit `workout_id` and `workout_schedule_id`
- `workout get` includes recursive `segments`, compatibility `steps`/`steps_summary`, and a `write_projection` only when the workout fits the simplified write schema
- `health hrv` reads `lastNightAvg` and still falls back to legacy `lastNight`

## Date Range Options

| Option | Meaning | Example |
|--------|---------|---------|
| `--date DATE` | Single day | `--date 2026-03-11` |
| `--days N` | Past N days (inclusive) | `--days 7` |
| `--from DATE --to DATE` | Explicit range (both inclusive) | `--from 2026-03-01 --to 2026-03-11` |
| `--ahead N` | Next N days (calendar only) | `--ahead 7` |

Maximum range: 90 days. Conflicting options (e.g., `--date` with `--days`) produce a clear error.

## Examples

```bash
# Last week of sleep data
garmin-cli health sleep --days 7

# HRV for a specific date range
garmin-cli health hrv --from 2026-03-01 --to 2026-03-10

# List recent running activities as CSV
garmin-cli --format csv activity list --limit 10 --type running

# Activities from a specific date range
garmin-cli activity list --from 2026-03-01 --to 2026-03-31

# Activities from the past 7 days
garmin-cli activity list --days 7

# Upcoming planned workouts
garmin-cli workout calendar --ahead 7

# Create a workout from a JSON file
garmin-cli --json workout create my_workout.json

# Create and schedule a workout via stdin
echo '{"name":"Easy Run","sport":"running","steps":[{"type":"interval","duration":{"type":"time","value":1800},"target":{"type":"heart.rate.zone","zone":2}}]}' \
  | garmin-cli --json workout create --stdin

# Schedule an existing workout
garmin-cli --json workout schedule 12345678901 2026-04-01

# All performance thresholds
garmin-cli performance thresholds

# Agent use: JSON output for scripting
garmin-cli --json health hrv --date 2026-03-11
garmin-cli --json activity list --limit 5
```

## Error Codes

| Code | Meaning |
|------|---------|
| `AUTH_MISSING` | No credentials found (no session and no env vars) |
| `AUTH_FAILED` | Credentials rejected by Garmin |
| `MFA_REQUIRED` | Garmin sent a one-time MFA code; submit it to finish the login (MCP: `submit_mfa_code` tool, CLI: `garmin-cli login`) |
| `NOT_FOUND` | API endpoint unavailable (404) |
| `RATE_LIMITED` | 429 after 3 retries |
| `SERVER_ERROR` | 5xx after 3 retries |
| `NETWORK_ERROR` | Connection or timeout failure |
| `INVALID_INPUT` | Bad arguments or conflicting options |
| `INTERNAL_ERROR` | Unexpected error |

## MCP Server

The MCP server exposes primitive health, activity, workout, performance, and device tools plus AI-coaching orchestration tools. `coach_snapshot` returns a bounded evidence packet, `training_plan_reconcile` compares the calendar with detailed activities, and `training_plan_preview` provides a no-write diff before the destructive `training_plan_apply` or `training_plan_reschedule` tools. Existing workout and activity write tools remain available. See [SKILL.md](SKILL.md) for complete contracts and limits.

### Synthetic Claude coaching workflow

1. Claude calls `coach_snapshot` and explains the recovery, load, plan, provenance, and any missing-data facts without inventing a readiness score.
2. Claude calls `training_plan_reconcile` in `summary` mode to separate exact workout associations from explicitly inferred or ambiguous matches.
3. If the user asks for a changed plan, Claude builds the strict plan object and calls `training_plan_preview`. Preview performs live reads only.
4. Claude shows the diff and asks for approval in the client. Only after approval should the client invoke `training_plan_apply`; the server does not treat an agent-supplied boolean as human approval.
5. Apply rechecks live state, creates and verifies destinations first, removes source schedules last, and reports `complete`, `compensated`, `partial`, or `unknown` truthfully.

`training_plan_reconcile(detail="targets")` currently preserves the bounded contract but reports target comparison as `insufficient_data`; interval/metric-stream target coverage remains pending. Apply tools can mutate the Garmin calendar and rely on the MCP client's destructive-tool approval UX.

### Installation

The package is published on PyPI as `garmin-py` (the CLI command remains `garmin-cli`). The recommended install method is `uv tool install`, which places the binary in `~/.local/bin` — a stable, venv-independent location that desktop applications can access without macOS sandbox issues:

```bash
uv tool install "garmin-py[mcp]"
```

Or from a source checkout:

```bash
uv tool install --editable "/path/to/garmin-py[mcp]"
```

To uninstall:

```bash
uv tool uninstall garmin-py
```

**Avoid pointing MCP clients at a binary inside a project virtualenv** (e.g. `.venv/bin/garmin-cli`). On macOS, desktop applications run in a sandbox and cannot read `pyvenv.cfg` inside directories they have not been granted access to, which causes a fatal Python startup error:

```
PermissionError: [Errno 1] Operation not permitted: '/path/to/.venv/pyvenv.cfg'
```

The `uv tool install` approach avoids this entirely. Alternatively, grant Claude Desktop Full Disk Access in System Settings → Privacy & Security → Full Disk Access.

### Claude Desktop

The one-click `.mcpb` bundle (see [Quick Start](#quick-start-claude-desktop-one-click)) is the recommended install. To configure manually instead, add to your Claude Desktop config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/Users/YOU/.local/bin/garmin-cli",
      "args": ["mcp-server"]
    }
  }
}
```

With a custom session directory:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/Users/YOU/.local/bin/garmin-cli",
      "args": ["--garmin-home", "/path/to/.garminconnect", "mcp-server"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add --transport stdio garmin -- garmin-cli mcp-server
```

### ChatGPT (via MCP bridge)

ChatGPT does not natively support MCP. To connect, run the server with an HTTP transport and use an MCP-to-OpenAI bridge such as [mcp-openai-bridge](https://github.com/nicobailey/mcp-openai-bridge) or a similar proxy:

```bash
# Start the MCP server with streamable HTTP
garmin-cli mcp-server --transport streamable-http --host 127.0.0.1 --port 8000
```

Then point the bridge at `http://127.0.0.1:8000/mcp` and configure it as a ChatGPT plugin or custom GPT action. Refer to the bridge project's documentation for setup details.

### HTTP Transports

SSE and streamable HTTP use the MCP SDK's built-in HTTP server. `--host` defaults to `127.0.0.1` (loopback only).

Streamable HTTP (recommended for remote clients):

```bash
garmin-cli mcp-server --transport streamable-http --port 8000
```

SSE (for clients that require it):

```bash
garmin-cli mcp-server --transport sse --port 8000
```

Optional HTTP flags: `--sse-path`, `--message-path` (SSE only), `--streamable-http-path`, `--stateless-http`, `--json-response` (streamable-http only).

#### Bearer-token gate on non-loopback binds

Binding to any non-loopback address (`--host 0.0.0.0` or an external interface) requires a bearer token. The server refuses to start otherwise.

```bash
export GARMIN_MCP_BEARER_TOKEN="<a-long-random-token>"
garmin-cli mcp-server --transport streamable-http --host 0.0.0.0 --port 8000
```

When the token is set and the bind is non-loopback, the MCP SDK gates every tool call (read **and** write) through `Authorization: Bearer <token>` at the transport layer. Loopback binds (`127.0.0.1`, `::1`, `localhost`) and the `stdio` transport are not gated -- they are trusted to the same degree as the shell user running the process.

TLS is expected to be terminated by a reverse proxy in front of the server; the built-in HTTP listener is plain HTTP.

For remote clients, prefer a dedicated session directory with `--garmin-home` rather than exporting credentials into another process.

See [SKILL.md](SKILL.md#mcp-server-alternative) for the full tool list and parameter reference.

## Development

```bash
pip install -e ".[dev]"
pytest tests/            # unit tests (1100+ tests)
pytest tests/ --e2e      # unit + e2e tests (requires GARMIN_HOME/garmin_tokens.json)
```

To run MCP server tests, also install the mcp extra:

```bash
pip install -e ".[dev,mcp]"
```

E2E tests make real Garmin Connect API calls. They require a valid `garmin_tokens.json` session in `~/.garminconnect` (or `GARMIN_HOME`; `GARTH_HOME` still works as an alias). Set `E2E_RATE_LIMIT_SECONDS` (default: 5) to adjust the inter-request delay.
