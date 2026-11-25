# garmin-py

Garmin Connect for AI assistants and the command line. garmin-py exposes your health, activity, workout, and performance data as an **MCP server** (Claude Desktop, Claude Code, and any other MCP client) and as a **CLI** (`garmin-cli`) with table, JSON, and CSV output.

Read tools cover sleep, HRV, stress, body battery, training status/load, activities (including raw per-sample streams), planned workouts, race predictions, and personal records; write tools create and schedule structured workouts and manage activities. `coach_snapshot` assembles bounded recovery, load, execution, and calendar facts for AI coaching, while `training_plan_reconcile` links prescribed workouts to completed activities. The existing `report_snapshot` remains available for fixed morning, evening, and weekly reports.

## Quick Start: Claude Desktop (one-click)

1. Download `garmin-py-<version>.mcpb` from the [latest release](https://github.com/ching-kuo/garmin-py/releases/latest).
2. Open it with Claude Desktop (or drag it into Settings → Extensions).
3. Enter your Garmin Connect email and password when prompted — they are stored in the operating system keychain, never in the conversation.

On first launch the bundle creates a private virtual environment under `~/.garmin-py/mcpb/` and installs the matching `garmin-py` release from PyPI (internet required once). Requirements: Python 3.12+ on `PATH` (macOS ships 3.9 — install from [python.org](https://www.python.org/downloads/) or Homebrew).

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

Prompts go to stderr. For scripting, skip them: the email comes from `--email` or `GARMIN_EMAIL`, the password from `GARMIN_PASSWORD` or the first line of piped stdin with `--password-stdin` (an empty line fails with `AUTH_MISSING`; it never falls back to `GARMIN_PASSWORD`), and an MFA code from `--mfa-code` or `GARMIN_MFA_CODE`. `--password` still works but is deprecated (it shows up in shell history and process listings).

Each login starts a new MFA challenge, so `--mfa-code` / `GARMIN_MFA_CODE` only works for a code that is valid for that new challenge, such as one from an authenticator app. For emailed or SMS codes, run `garmin-cli login` in a terminal and enter the code when prompted, or use the MCP `submit_mfa_code` tool. At a terminal, `login` prompts for the code and ignores `GARMIN_MFA_CODE`; only an explicit `--mfa-code` skips the prompt.

```bash
printf '%s\n' "$GARMIN_PW" | garmin-cli --json login --email your@email.com --password-stdin
```

Under `--json` or `--format csv`, or when stdin is not a terminal, `login` never prompts: missing credentials fail with `AUTH_MISSING`, and an MFA challenge without a supplied code fails with `MFA_REQUIRED` (exit 1).

In the MCP server, a login that Garmin rejects (bad credentials, 401/403) or throttles (429/427) pauses new login attempts for 60 seconds, doubling per consecutive failure up to 15 minutes; every such error, including the first, carries `retry_after_seconds`. The pause resets after a successful login or session resume, or when `GARMIN_EMAIL` / `GARMIN_PASSWORD` change. A rejected MFA code pauses logins too, so the next call does not immediately send a fresh code; after a 429 on `submit_mfa_code` the challenge is kept, but resubmitting waits out the pause (after a 5xx or network failure it is kept with no pause). Network errors, timeouts and Garmin 5xx responses during login never pause logins: a 5xx reports `SERVER_ERROR`, and an unreachable Garmin reports `NETWORK_ERROR` instead of blaming the credentials. The same applies when validating a saved session: a throttle, 5xx, or network failure reports `RATE_LIMITED` / `SERVER_ERROR` / `NETWORK_ERROR` rather than `AUTH_FAILED`, and does not trigger a new login.

Check login status at any time:

```bash
garmin-cli login status
# Logged in. Token store at: ~/.garminconnect/garmin_tokens.json

garmin-cli --json login status
# {"ok": true, "command": "login status", "count": 1, "data": [{"authenticated": true, "garmin_home": "..."}]}
```

`login status` exits 0 with `"authenticated": false` when no session is saved or Garmin rejects it, and exits 1 with `RATE_LIMITED`, `SERVER_ERROR`, or `NETWORK_ERROR` when Garmin throttles, fails, or is unreachable (or `AUTH_FAILED` for an unusable Garmin home path). MCP `login_status` reports those three codes in optional `error_code` / `detail` fields. `login status` never repairs permissions or migrates legacy tokens. Status checks (`login status`, `doctor`, MCP `login_status`) may still refresh the session tokens on disk, as any authenticated request can.

Log out by deleting the saved token file (`garmin_tokens.json` in the Garmin home). Symlinked token files and Garmin homes reached through a symlink are refused. For the default home it also deletes a legacy `~/.garth/garmin_tokens.json`, which would otherwise be migrated back on the next command:

```bash
garmin-cli --json login logout
# {"ok": true, "command": "login logout", "count": 1, "data": [{"logged_out": true, "legacy_token_removed": false}]}
```

`logged_out` is `false`, still with exit code 0, when there was nothing to delete. The plain-text output lists every file it deleted. A running MCP server keeps the session it already loaded and may save refreshed tokens again after `login logout`, so stop the server before logging out. A legacy `~/.garth` that is a symlink or not a directory is left alone (migration ignores it too).

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
| `GARMIN_MFA_CODE` | — | MFA code for a non-interactive `garmin-cli login`; must be valid for the new challenge (authenticator app), so emailed/SMS codes need an interactive login |
| `GARMIN_CLI_HTTP_TIMEOUT` | `30` | HTTP request timeout in seconds (float); invalid or non-positive values fall back to `30` |
| `GARMIN_CLI_RETRY_DELAYS` | `2,4,8` | Comma-separated retry delay sequence in seconds (e.g. `1,2,4`); invalid values fall back to `2,4,8` |
| `GARMIN_CLI_AUTH_PROBE_TTL` | `600` | Seconds to cache a successful auth probe in the MCP server (float); `0` disables caching and probes on every call |
| `GARMIN_CLI_DAILY_CALL_DELAY` | `0.5` | Delay in seconds (float) between request submissions for endpoints that fan out one request per day (e.g. `endurance-score`); invalid or negative values fall back to `0.5` |
| `GARMIN_MCP_READ_ONLY` | unset | `1`/`true` starts `mcp-server` without write tools (same as `--read-only`) |
| `GARMIN_CLI_FETCH_CONCURRENCY` | `4` | Worker cap for concurrent fan-out fetches (per-day ranges, report snapshot sections, multisport children); invalid or non-positive values fall back to `4` |

### Custom session directory

```bash
garmin-cli --garmin-home /path/to/session login
garmin-cli --garmin-home /path/to/session health sleep --days 1
```

The default session directory is `~/.garminconnect`. It is created with `0o700` permissions. A home reached through a symlink is rejected (root-owned system links such as macOS `/tmp` are allowed), and `GARMIN_HOME` must be a directory: a `.json` file path fails with `INVALID_INPUT`. Do not share this directory.

New sessions are stored as `garmin_tokens.json` inside `GARMIN_HOME`. If you still have an existing `~/.garth/garmin_tokens.json`, the CLI will copy it into the new default home on first use (created 0600 from the start; a symlinked `~/.garth` or legacy token file is not copied). `GARTH_HOME` / `--garth-home` still work as deprecated aliases when you need to keep an older path explicitly.

## Troubleshooting

Run the diagnostic command and paste its output when reporting an installation or authentication problem:

```bash
garmin-cli doctor
garmin-cli doctor --fast --format json  # skip the live session probe
```

The checks cover Python, the installed garmin-py and garminconnect versions, configuration, token-store layout and permissions (0700 directory; `garmin_tokens.json` a regular file, not a symlink, with mode 600), the optional MCP install (mcp >=2.2.0,<3), the authenticated session, and MCP write-surface binding. With `GARMIN_EMAIL` and `GARMIN_PASSWORD` set, a missing Garmin home, token store, or session passes (the credentials are not verified until a command signs in). Each failed check carries a specific recovery hint (for example the permission mode to set). Paths are home-relative where possible, and credentials are never included. MCP clients can run the same non-interactive checks with the read-only `server_doctor` tool.

## Output Formats

All commands default to table output. Use `--json` or `--format csv` to change, either before or after the subcommand (after wins when both are given):

```bash
garmin-cli health sleep --days 7              # table (default)
garmin-cli --json health sleep --days 7       # JSON envelope
garmin-cli health sleep --days 7 --json       # same
garmin-cli --format csv health sleep --days 7 # CSV
```

CSV output is always a single table. Output that does not fit one table rejects `--format csv` with `INVALID_INPUT`: `coach snapshot`, `workout create --dry-run` / `workout update --dry-run`, and `activity get --laps` (use `activity laps`); `login`, `login status`, and `login logout` print a one-row table. Text cells starting with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with a tab so spreadsheets do not run them as formulas; numbers (including negatives) are written as-is.

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

Exit code is `0` on success and `1` on error; an interrupted command (Ctrl-C, or end of input at a prompt) exits `130` with `INTERRUPTED`.

Destructive commands (`activity delete`, `workout delete`, `workout unschedule`) validate the id, then ask for confirmation on stderr. Any answer but `y`/`yes` prints `Aborted.` and exits 1 (`INVALID_INPUT`). Under `--json`, or when stdin is not a terminal, they never prompt: pass `--confirm` (alias `--yes`/`-y`), otherwise they fail with `INVALID_INPUT`.

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

`health daily-summary` fetches the whole range in one request.

`health status` returns Garmin's full training-load picture for the day: training status, acute/chronic load, acute:chronic workload ratio (ACWR), the chronic-load "tunnel", monthly load-focus buckets with their targets, and load-balance status.

### AI coach

```bash
garmin-cli --json coach snapshot [--date DATE] [--baseline-days N] [--recent-daily-days N]
                                  [--include-extended-daily-baselines] [--sport TYPE]...
```

The default snapshot uses the 28 prior days for ranged signals and activities, nine prior days plus the current date for daily resting-HR and stress calls (leaving slack over the seven-sample baseline minimum for days without data), and at most 32 upstream requests (the calendar costs up to three: the seven-day plan window can span two weekly pages, plus the by-period schedule lookup that catches Garmin Coach sessions). `--recent-daily-days` accepts 1-9, the most that fits the cap. The cap counts Garmin data requests only: the session check or login, the profile-timezone lookup, and retries are extra. `provenance.completed_requests` reports the data requests that completed sections actually made (one fewer calendar page when the window fits in one week). Baseline medians exclude the current date and require seven valid samples; the resting-HR and stress signals report the shorter daily window they were actually fetched over. Missing and stale values remain explicit in `data_quality`; the server returns neutral facts and does not assign a proprietary readiness score or decide whether a workout is safe.

`--json` wraps the snapshot in the standard envelope (`data[0]` is the snapshot). Table output shows the recovery signals only, with a note pointing to `--json` for the other sections; `--format csv` is rejected with `INVALID_INPUT`.

Extended daily baselines are rejected if their estimated cost exceeds the 32-request cap. A terminal rate limit stops further Garmin calls while preserving completed sections with `complete: false` and `aborted: true`.

### Activities

```bash
garmin-cli activity list             [--limit N] [--type TYPE] [--search TEXT] [--date DATE | --from DATE --to DATE | --days N]
garmin-cli activity get              ACTIVITY_ID [--detail] [--laps]  # --detail/-d shows sport-aware metrics; --laps appends lap data (table/JSON; for CSV use activity laps)
garmin-cli activity laps             ACTIVITY_ID  # per-lap rows (run/bike: HR, power, cadence, start_time_gmt/local) or per-pool-length rows (lap_swimming)
garmin-cli activity zones            ACTIVITY_ID  # HR time-in-zone breakdown
garmin-cli activity weather          ACTIVITY_ID  # temp_c, apparent_temp_c, dew_point_c (Celsius), humidity, wind, condition
garmin-cli activity metrics-describe ACTIVITY_ID  # metric descriptors: key, unit, metricsIndex
garmin-cli activity detail-metrics   ACTIVITY_ID [--metric KEY]...  # raw per-sample time series (one row per sample)
garmin-cli activity download         ACTIVITY_ID [--fmt original|tcx|gpx|kml|csv] [--output PATH] [--force]
garmin-cli activity upload           FILE         # .fit / .gpx / .tcx
garmin-cli activity delete           ACTIVITY_ID [--confirm | --yes | -y]
garmin-cli activity rename           ACTIVITY_ID NEW_NAME
garmin-cli activity set-type         ACTIVITY_ID TYPE_KEY  # e.g. running, cycling
```

`--limit` defaults to 20 and must be 1-100 (`activity list`, `workout list`). `--type` filters by activity type key (e.g., `running`, `cycling`).

`activity detail-metrics` returns the raw recorded sample stream (~2000 rows for a typical activity; columns are the watch's metric keys such as `directTimestamp`, `directHeartRate`, `directPower`). Use repeatable `--metric` flags to select columns — `activity metrics-describe` lists what a given activity recorded. This is the data for intra-activity analyses such as first-half vs second-half aerobic decoupling.

`activity download` writes the activity file to disk (it never prints binary to stdout). `--fmt` defaults to `original` (the FIT file inside a ZIP archive); the default output name is `activity_<id><ext>` in the current directory, and an existing file is not overwritten unless `--force` is given. `activity delete` prompts for confirmation unless `--confirm` (or `--yes`/`-y`) is passed. `activity set-type` accepts any `typeKey` from Garmin's live sport-type table (an unknown key is rejected before any write).

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
garmin-cli workout calendar [--date DATE | --from DATE --to DATE | --days N | --ahead N]

# Write
garmin-cli workout create   FILE [--dry-run]       # JSON or YAML file
garmin-cli workout create   --stdin                # read JSON from stdin
garmin-cli workout update   WORKOUT_ID FILE [--dry-run] # partial update (only fields provided change)
garmin-cli workout delete   WORKOUT_ID [--confirm] # --confirm (--yes/-y) skips interactive prompt
garmin-cli workout schedule WORKOUT_ID DATE        # DATE = YYYY-MM-DD
garmin-cli workout unschedule SCHEDULE_ID [--confirm] # removes a calendar entry; SCHEDULE_ID is the workout_schedule_id returned by schedule
```

`--ahead N` shows the next N days of planned workouts (future-facing; the default is the next 7 days). `--days N` shows past N days.

`--dry-run` validates the input and prints the Garmin payload without saving (`--json`: `data[0]` has `dry_run: true` and `wire_payload`). `workout create --dry-run` needs no login; `workout update --dry-run` still reads the existing workout to merge it. `workout schedule` reports the new entry as `workout_schedule_id`.

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
garmin-cli performance ftp-history     [--sport cycling|running] [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance acclimation     [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance cycling-ability [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance power-curve     [--sport cycling|rowing] [--date DATE | --from DATE --to DATE | --days N]
garmin-cli performance fastest-splits  [--sport running|cycling] [--bests N] [--date DATE | --from DATE --to DATE | --days N]
```

`ftp-history` returns daily FTP (`ftp_watts`); `acclimation` returns daily heat acclimation percentage and acclimated altitude with Garmin's trend labels; `cycling-ability` returns Garmin's daily aerobic endurance, aerobic capacity, and anaerobic capacity scores with the rider profile type; `power-curve` returns the best average power per duration (`duration_s`, `power_w`) and the activity that set it (Garmin supports cycling and rowing only); `fastest-splits` returns the fastest times per standard distance (running: 1 km, 1 mi, 5 km, 10 km, half marathon), up to `--bests` (1-10) efforts per distance. Each is one request for the whole range.

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
- `workout calendar` includes compatibility `id` plus explicit `workout_id` and `workout_schedule_id`, and also lists Garmin Coach (adaptive plan) sessions that Garmin's calendar pages omit
- `workout get` includes recursive `segments`, compatibility `steps`/`steps_summary`, and a `write_projection` only when the workout fits the simplified write schema
- `health hrv` reads `lastNightAvg` and still falls back to legacy `lastNight`

## Date Range Options

| Option | Meaning | Example |
|--------|---------|---------|
| `--date DATE` | Single day | `--date 2026-03-11` |
| `--days N` | Past N days (inclusive) | `--days 7` |
| `--from DATE --to DATE` | Explicit range (both inclusive) | `--from 2026-03-01 --to 2026-03-11` |
| `--ahead N` | Next N days (`workout calendar` only) | `--ahead 7` |

Maximum range: 90 days. Conflicting options (e.g., `--date` with `--days`) produce a clear error.

"Today" for `--days`, `--ahead` and the no-option default is the current date in your Garmin profile timezone (the same day the MCP server uses), falling back to the host date when the profile timezone is unavailable. Explicit `--date`/`--from`/`--to` dates are used as given.

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
| `AUTH_MISSING` | No credentials found (no session and no env vars). In MCP errors the recovery hint covers MCP login (Claude Desktop extension settings, then `submit_mfa_code` for a challenge pending in that server) and terminal login (`garmin-cli login`); when `retry_after_seconds` is set the hint starts with the wait. A rejected MFA code instead says to wait, retry the original call for a new code, and submit that |
| `AUTH_FAILED` | Credentials or session rejected by Garmin (MCP recovery hint as for `AUTH_MISSING`), or an unsafe or unusable Garmin home or token file (the hint then points at `GARMIN_HOME` and `garmin-cli doctor`, not at logging in) |
| `MFA_REQUIRED` | Garmin sent a one-time MFA code; submit it to finish the login (MCP: `submit_mfa_code` tool, CLI: `garmin-cli login` at a terminal; `--mfa-code` / `GARMIN_MFA_CODE` only for authenticator-app codes) |
| `NOT_FOUND` | API endpoint unavailable (404) |
| `RATE_LIMITED` | 429 (or SSO 427) after 3 retries |
| `SERVER_ERROR` | 5xx after 3 retries (creates such as workout create/schedule and activity upload are never retried on 5xx, since the first attempt may have succeeded) |
| `NETWORK_ERROR` | Connection or timeout failure after 3 retries ("Could not reach Garmin."); creates such as workout create/schedule and activity upload are never retried. A failed write may still have landed: verify remote state before repeating any write |
| `INVALID_INPUT` | Bad arguments or conflicting options, or another 4xx from Garmin (the message names the HTTP status) |
| `INTERRUPTED` | CLI only: interrupted by Ctrl-C or end of input at a prompt (exit 130) |
| `INTERNAL_ERROR` | Unexpected error |

## MCP Server

The MCP server exposes primitive health, activity, workout, performance, and device tools plus AI-coaching orchestration tools. `coach_snapshot` returns a bounded evidence packet, `training_plan_reconcile` compares the calendar with detailed activities, and `training_plan_preview` provides a no-write diff before the destructive `training_plan_apply` or `training_plan_reschedule` tools. Existing workout and activity write tools remain available. Tools that default a date to "today" (`coach_snapshot`, `report_snapshot`) use the athlete's Garmin profile timezone, so a server running in UTC still asks for the athlete's day. See [SKILL.md](SKILL.md) for complete contracts and limits.

### Synthetic Claude coaching workflow

1. Claude calls `coach_snapshot` and explains the recovery, load, plan, provenance, and any missing-data facts without inventing a readiness score.
2. Claude calls `training_plan_reconcile` in `summary` mode to separate exact workout associations from explicitly inferred or ambiguous matches.
3. If the user asks for a changed plan, Claude builds the strict plan object and calls `training_plan_preview`. Preview performs live reads only.
4. Claude shows the diff and asks for approval in the client. Only after approval should the client invoke `training_plan_apply`; the server does not treat an agent-supplied boolean as human approval.
5. Apply rechecks live state, creates and verifies destinations first, removes source schedules last (a schedule the plan vacates from a destination date, as in a swap, is removed just before that destination is written), and reports `complete`, `compensated`, `partial`, or `unknown` truthfully. A compensated apply restores removed schedules under new ids, so preview again and rebuild the plan before retrying.

`training_plan_reconcile(detail="targets")` adds HR, pace, power, and cadence target comparisons for matched running and cycling activities. It uses HR-zone and lap summaries first, fetches stride-downsampled streams only when required (at most 10 streams per call and 1000 samples per stream), and reports per-target coverage and data quality. Missing sensors and unsupported sports remain explicit `insufficient_data` states rather than failure verdicts. Apply tools can mutate the Garmin calendar and rely on the MCP client's destructive-tool approval UX.

### Resources and prompts

MCP clients can preload two resources:

- `garmin://server/manifest` describes the runtime tool inventory, annotations, error recovery contracts, envelopes, and response limits.
- `garmin://athlete/profile` returns a cached, bounded thresholds, latest VO2max, race-prediction, and 7/28-day load snapshot. An unauthenticated read returns a structured unauthenticated body. A snapshot with a rate-limited, server or network failure is not cached, and a new login drops the cached snapshot.

The server also publishes connection-time instructions with the authentication, response, error, limit, and write-approval contracts. To keep `tools/list` small, row-returning tools publish a plain `{"type": "object"}` `outputSchema`; only `activity_get`, `activity_detail_metrics`, `login_status`, and `submit_mfa_code` publish typed outer fields. Structured inputs are typed: `workout_create`/`workout_update` publish the workout schema (sport, steps, repeat steps, duration, target) and `training_plan_preview`/`training_plan_apply` publish the plan schema, so a wrong type or unknown key is rejected before the tool runs, with the failing field path in the error. Enum-like parameters (`report_snapshot.kind`, `training_plan_reconcile.detail`, `activity_download.fmt`) are published as enums.

Health and performance range tools accept `start_date` or `days` (1-90); `end_date` is optional and defaults to today in the athlete's Garmin profile timezone. `activity_list` pages with `offset` (the pre-3.0 `start` argument is rejected with an error) and returns `truncated` plus `next_offset` when a full page came back (Garmin reports no total).

Two URI templates expose the most-read entities without a tool round trip:

- `garmin://activity/{id}` returns the serialized `activity_get` envelope.
- `garmin://health/sleep/{date}` returns the serialized one-day `health_sleep` envelope for an ISO date.

Four content-only prompts guide common workflows: `weekly_training_review`, `recovery_check`, `compare_recent_activities`, and `plan_next_week`. The planning prompt explicitly requires human confirmation before invoking destructive apply tools.

Large MCP reads are bounded. `activity_laps(activity_id, offset=0)` returns at most 100 rows and supplies `total`, `truncated`, and `next_offset` paging metadata. `activity_detail_metrics(activity_id, metrics="", max_samples=0)` deterministically samples the whole stream by stride, reporting `samples_total`, `samples_returned`, and `stride`. Rows carry all requested metrics, so channels stay timestamp-aligned in a single call. The default `max_samples=0` auto-sizes the sample count to the channel count (a ~2400-value budget, clamped to 100–1000 samples) so multi-channel pulls fit MCP client response limits; pass an explicit 100–5000 to override.

### Read-only mode

`garmin-cli mcp-server --read-only` (or `GARMIN_MCP_READ_ONLY=1`, or the "Read-only mode" setting of the Claude Desktop extension) registers no write tools: `workout_create`, `workout_update`, `workout_delete`, `workout_schedule`, `workout_unschedule`, `activity_upload`, `activity_delete`, `activity_rename`, `activity_set_type`, `activity_download`, `training_plan_apply`, and `training_plan_reschedule` are left out of `tools/list`. Read tools, `training_plan_preview`, and `submit_mfa_code` stay; the server instructions and the `plan_next_week` prompt stop at the preview. `server_doctor` reports the server's mode under `write_surface`; `garmin-cli doctor` can only see `GARMIN_MCP_READ_ONLY` (not a `--read-only` flag on a running server) and fails the check for a value that is not a boolean such as `1`/`0` or `true`/`false`, which `mcp-server` also refuses at start-up. In the Claude Desktop extension, an unfilled setting placeholder is treated as off.

### Write audit log

Each MCP write tool call (including `training_plan_apply`, `training_plan_reschedule`, and `submit_mfa_code`) logs exactly one JSON object per line to stderr on the `garmin_cli.audit` logger at INFO, for example `{"activity_id": 5, "name_len": 11, "outcome": "success", "tool": "activity_rename"}`. Caller free text (names, descriptions, paths, MFA codes, an activity type key Garmin has not accepted) is never logged, only its length. `outcome` is `success`, `dry-run`, `conflict` (a plan result refused by conflicts or the live recheck before any write), `rejected` (Garmin declined an upload, e.g. a duplicate), `failed-validation` (including calls rejected by the input schema or id checks, which log only `tool` and `outcome`), `failed-auth`, or `failed-upstream` (also used for unexpected errors); plan tools add `plan_outcome`. Hosts can configure the `garmin_cli.audit` logger themselves (handlers, level, destination); if it has no handlers and the root logger has some, the lines propagate to the root handlers; only in an unconfigured process does the server add its own stderr handler (one line per event, no propagation). The MCP SDK's own logger is held at WARNING, so failed tool calls never log their error text (which can contain caller arguments) at INFO.

### File access

The MCP `activity_download` and `activity_upload` tools only touch files inside one directory: `GARMIN_MCP_FILE_ROOT` (default `~/Downloads/garmin-py`, created with 0700 permissions on the first download; a custom value must be an absolute path, `~` allowed). Relative paths are taken under that root; paths that escape it, contain `..`, or pass through any symlink (file or directory, even one pointing inside the root) are rejected, and every unavailable upload path returns the same `File not available under GARMIN_MCP_FILE_ROOT` error. `activity_download` is annotated destructive because `overwrite=true` replaces a file. The CLI `activity download` / `activity upload` commands are not confined. The root and every directory under it must not be writable by untrusted users: the checks inspect intermediate directories before the download starts and before an upload reopens the file by name, so someone who can swap one for a symlink in between could redirect a download's write or an upload's read.

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

Optional HTTP flags: `--sse-path`, `--message-path` (SSE only), `--streamable-http-path`, `--stateless-http`, `--json-response` (streamable-http only). `--read-only` works with every transport (see [Read-only mode](#read-only-mode)).

#### Bearer-token gate

Binding to any non-loopback address (`--host 0.0.0.0` or an external interface) requires a bearer token of at least 32 characters from the RFC 6750 token alphabet (`A-Z a-z 0-9 - . _ ~ + /`, optional trailing `=`; `secrets.token_urlsafe` output qualifies). The server refuses to start otherwise.

```bash
export GARMIN_MCP_BEARER_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
garmin-cli mcp-server --transport streamable-http --host 0.0.0.0 --port 8000
```

Whenever the variable is present, the MCP SDK gates every tool call (read **and** write) through `Authorization: Bearer <token>` at the transport layer on every HTTP bind, loopback included; a present-but-blank value refuses to start. Only `stdio` and loopback HTTP binds with the variable absent run unauthenticated. Loopback is not a trust boundary on a multi-user host or behind a local reverse proxy or tunnel: any local user or forwarded request can reach `127.0.0.1`, so set the token in those setups.

TLS is expected to be terminated by a reverse proxy in front of the server; the built-in HTTP listener is plain HTTP.

For remote clients, prefer a dedicated session directory with `--garmin-home` rather than exporting credentials into another process.

See [SKILL.md](SKILL.md#mcp-server-alternative) for the full tool list and parameter reference.

## Development

```bash
pip install -e ".[dev]"
pytest tests/                 # unit and offline contract tests
pytest tests/ --e2e           # add read-only live e2e tests
```

To run MCP server tests, also install the mcp extra:

```bash
pip install -e ".[dev,mcp]"
```

E2E tests make real Garmin Connect API calls. They require a valid `garmin_tokens.json` session in `~/.garminconnect` (or `GARMIN_HOME`; `GARTH_HOME` still works as an alias). Set `E2E_RATE_LIMIT_SECONDS` (default: 5) to adjust the inter-request delay.

### Contract tests and fixtures

The default suite includes offline CLI and MCP contract flows backed by sanitized JSON payloads under `tests/fixtures/backend/`:

```bash
pytest tests/test_contract/
```

To refresh read fixtures against an authenticated account, run:

```bash
pytest tests/ --e2e --record-fixtures
```

`--record-fixtures` is rejected unless `--e2e` is also present. Recording occurs at the backend function boundary and redacts identity (names, user/owner ids, coordinates), location, profile-image, token, password, and secret key fragments before deterministic, sorted JSON is written. Review every fixture diff before committing it.

Tests that write to Garmin require a second opt-in and are never part of the default or ordinary `--e2e` run:

```bash
pytest tests/e2e/test_calendar_probe_e2e.py --e2e --e2e-writes
```

That probe creates, schedules, unschedules, and deletes a temporary workout. It is intended for maintainer-run identifier verification only.
