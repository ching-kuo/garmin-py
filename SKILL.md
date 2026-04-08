---
name: garmin-cli
description: Extract health, activity, workout, and performance data from Garmin Connect. Use when users need Garmin fitness data including sleep, HRV, weight, stress, activities, workouts, and performance metrics.
argument-hint: [command] [options]
allowed-tools: Bash
---

# garmin-cli

Extract health, activity, workout, and performance data from Garmin Connect.

## Prerequisites

- Python 3.10+
- Install: `pip install .` (from repo root)
- Authentication: run `garmin-cli login`, or use a saved garth session at `~/.garth`, or set env vars `GARMIN_EMAIL` / `GARMIN_PASSWORD`

## Agent Usage

Always use `--json` for machine-readable output. The tool returns a JSON envelope on stdout with exit code 0 (success) or 1 (error).

### Success envelope

```json
{
  "ok": true,
  "command": "<group> <subcommand>",
  "date_range": null,
  "count": 7,
  "data": [...]
}
```

`date_range` is `null` for commands that are not scoped to a date range. When a command is date-scoped, it is an object with `from` and `to` ISO dates.

### Error envelope

```json
{
  "ok": false,
  "command": "<group> <subcommand>",
  "error": "Human-readable message",
  "error_code": "RATE_LIMITED"
}
```

### Error codes

| Code | Meaning | Retry? |
|------|---------|--------|
| `AUTH_MISSING` | No credentials or session found | No -- configure auth |
| `AUTH_FAILED` | Credentials rejected | No -- fix credentials |
| `NOT_FOUND` | Endpoint returned 404 | No |
| `RATE_LIMITED` | 429 after 3 retries | Yes -- wait and retry |
| `SERVER_ERROR` | 5xx after 3 retries | Yes -- wait and retry |
| `INVALID_INPUT` | Bad arguments or conflicting options | No -- fix arguments |
| `INTERNAL_ERROR` | Unexpected error, including uncategorized connection/timeout failures | Maybe |

## Commands

### Date range options (health range commands + workout calendar)

| Option | Effect | Example |
|--------|--------|---------|
| `--date YYYY-MM-DD` | Single day | `--date 2026-03-11` |
| `--days N` | Past N days (inclusive of today) | `--days 7` |
| `--from YYYY-MM-DD --to YYYY-MM-DD` | Explicit range (both inclusive) | `--from 2026-03-01 --to 2026-03-07` |
| `--ahead N` | Next N days (workout calendar only) | `--ahead 7` |
| *(none)* | Defaults to today | |

Max range: 90 days. Conflicting options produce `INVALID_INPUT`.

---

### Health

All health commands except `health status` accept the shared date range options. `health status` only accepts `--date` and defaults to today.

```bash
# Sleep -- fields: date, duration_hours, deep_min, light_min, rem_min, awake_min, score
garmin-cli --json health sleep --days 7

# HRV -- fields: date, weekly_avg, last_night, status
garmin-cli --json health hrv --date 2026-03-11

# Weight -- fields: date, weight_kg, bmi, body_fat_pct
garmin-cli --json health weight --days 30

# Body battery -- fields: date, start_level, end_level
garmin-cli --json health body-battery --days 7

# Stress -- fields: date, avg_stress, max_stress
garmin-cli --json health stress --days 7

# SpO2 -- fields: date, avg_spo2, lowest_spo2
garmin-cli --json health spo2 --days 7

# Resting heart rate -- fields: date, resting_hr
garmin-cli --json health resting-hr --days 7

# Training readiness -- fields: date, score, level
garmin-cli --json health readiness --days 7

# Training status (single day only) -- fields: date, training_status, load_type
garmin-cli --json health status --date 2026-03-11
```

### Activities

```bash
# List recent activities -- fields: id, date, name, type, distance_km, duration_min, avg_hr
garmin-cli --json activity list --limit 10
garmin-cli --json activity list --limit 10 --type running
garmin-cli --json activity list --limit 10 --search "morning run"

# Get a single activity by ID -- same fields as list
garmin-cli --json activity get 12345678901

# Weather for an activity -- fields: temperature, weatherIconCode, windSpeed, windDirectionDegrees, humidity, precipProbability
garmin-cli --json activity weather 12345678901
```

`--limit` defaults to 20, max 100. `--type` filters by Garmin activity type key (e.g., `running`, `cycling`, `swimming`).

### Workouts

```bash
# List saved workouts -- fields: id, name, sport, duration_min, description
garmin-cli --json workout list --limit 10

# Get workout detail -- fields: id, name, sport, duration_min, description, steps_summary, steps[]
garmin-cli --json workout get 12345678901

# Workout calendar (planned workouts) -- fields: date, id, name, type, duration_min, description
garmin-cli --json workout calendar --ahead 7
garmin-cli --json workout calendar --from 2026-03-01 --to 2026-03-14
garmin-cli --json workout calendar --days 7

# Create a workout from JSON file -- fields: id, name, sport, duration_min, status
garmin-cli --json workout create workout.json

# Create from stdin (pipe from LLM output)
echo '{"name":"Easy Run","sport":"running","steps":[{"type":"warmup","duration":{"type":"time","value":300},"target":{"type":"no.target"}}]}' | garmin-cli --json workout create --stdin

# Create from YAML file (requires: pip install pyyaml)
garmin-cli --json workout create workout.yaml

# Update an existing workout (partial -- only fields provided are changed)
garmin-cli --json workout update 12345678901 changes.json

# Delete a workout (--confirm skips interactive prompt)
garmin-cli --json workout delete 12345678901 --confirm

# Schedule a workout to a calendar date
garmin-cli --json workout schedule 12345678901 2026-04-01
```

`workout get` includes a `steps` array with structured step data (step_order, step_type, duration_type, duration_value, target_type, target_value_low, target_value_high) and a `steps_summary` string.

`workout create` / `workout update` output fields: `id, name, sport, duration_min, status`

`workout delete` output fields: `id, status`

`workout schedule` output fields: `workoutScheduleId, date, status`

---

## Workout JSON Schema Reference

The simplified input schema for `workout create` and `workout update`. All fields use human-readable string keys — no numeric IDs needed.

### Top-level structure

```json
{
  "name": "string (required on create, max 256 chars)",
  "sport": "string (required on create, see sport types)",
  "description": "string (optional)",
  "steps": [ "...step objects (required on create, non-empty)" ]
}
```

### Sport types

| Key | Description |
|-----|-------------|
| `running` | Running / jogging |
| `cycling` | Road / mountain cycling |
| `swimming` | Pool / open water swimming |
| `walking` | Walking |
| `hiking` | Hiking |
| `fitness_equipment` | Gym / strength / treadmill |
| `multi_sport` | Triathlon / duathlon |
| `other` | Any other sport |

### Step types

| Type | Purpose | Example |
|------|---------|---------|
| `warmup` | Warm-up period | `{"type":"warmup","duration":{"type":"time","value":600},"target":{"type":"heart.rate.zone","zone":1}}` |
| `interval` | High-intensity work | `{"type":"interval","duration":{"type":"distance","value":400},"target":{"type":"speed.zone","min":3.5,"max":4.0}}` |
| `recovery` | Low-intensity recovery | `{"type":"recovery","duration":{"type":"time","value":90},"target":{"type":"no.target"}}` |
| `rest` | Complete rest | `{"type":"rest","duration":{"type":"time","value":60}}` |
| `cooldown` | Cool-down | `{"type":"cooldown","duration":{"type":"time","value":300},"target":{"type":"open"}}` |
| `repeat` | Repeat group N times | `{"type":"repeat","count":4,"steps":[...]}` |

Max nesting: 2 levels (no repeats inside repeats).

### Duration types

| Type | Value unit | Example |
|------|-----------|---------|
| `time` | seconds | `{"type":"time","value":600}` — 600 = 10 min |
| `distance` | meters | `{"type":"distance","value":1000}` — 1000 = 1 km |

### Target types

| Type | Fields | Example |
|------|--------|---------|
| `no.target` | *(none)* | `{"type":"no.target"}` |
| `open` | *(none)* | `{"type":"open"}` |
| `heart.rate.zone` | `zone` (1-5) | `{"type":"heart.rate.zone","zone":3}` |
| `speed.zone` | `min`, `max` (m/s) | `{"type":"speed.zone","min":3.33,"max":4.17}` |
| `power.zone` | `zone` (1-7) | `{"type":"power.zone","zone":4}` |
| `cadence.zone` | `min`, `max` (spm) | `{"type":"cadence.zone","min":170,"max":180}` |

### Pace/speed reference (running)

| Pace (min/km) | Speed (m/s) | Use |
|---------------|-------------|-----|
| 7:00 | 2.38 | Easy / recovery |
| 6:00 | 2.78 | Easy / base |
| 5:30 | 3.03 | Tempo |
| 5:00 | 3.33 | Threshold |
| 4:30 | 3.70 | Interval / VO2max |
| 4:00 | 4.17 | Fast interval |
| 3:30 | 4.76 | Sprint |

Formula: `speed_ms = 1000 / (pace_min * 60)`

---

## Complete Workout Examples

### Easy 30-minute run

```json
{
  "name": "Easy 30min Run",
  "sport": "running",
  "description": "Recovery run at easy pace",
  "steps": [
    {"type":"warmup","duration":{"type":"time","value":300},"target":{"type":"heart.rate.zone","zone":1}},
    {"type":"interval","duration":{"type":"time","value":1500},"target":{"type":"heart.rate.zone","zone":2}},
    {"type":"cooldown","duration":{"type":"time","value":300},"target":{"type":"heart.rate.zone","zone":1}}
  ]
}
```

### 5x1km intervals

```json
{
  "name": "5x1km Intervals",
  "sport": "running",
  "description": "VO2max interval session",
  "steps": [
    {"type":"warmup","duration":{"type":"time","value":600},"target":{"type":"heart.rate.zone","zone":1}},
    {
      "type":"repeat","count":5,
      "steps": [
        {"type":"interval","duration":{"type":"distance","value":1000},"target":{"type":"speed.zone","min":3.70,"max":4.17}},
        {"type":"recovery","duration":{"type":"time","value":120},"target":{"type":"no.target"}}
      ]
    },
    {"type":"cooldown","duration":{"type":"time","value":600},"target":{"type":"heart.rate.zone","zone":1}}
  ]
}
```

### Cycling power workout

```json
{
  "name": "Sweet Spot Cycling",
  "sport": "cycling",
  "description": "Sweet spot intervals at power zone 3-4",
  "steps": [
    {"type":"warmup","duration":{"type":"time","value":600},"target":{"type":"power.zone","zone":2}},
    {
      "type":"repeat","count":3,
      "steps": [
        {"type":"interval","duration":{"type":"time","value":600},"target":{"type":"power.zone","zone":4}},
        {"type":"recovery","duration":{"type":"time","value":300},"target":{"type":"power.zone","zone":1}}
      ]
    },
    {"type":"cooldown","duration":{"type":"time","value":300},"target":{"type":"open"}}
  ]
}
```

---

## Workflow for LLM agents

```
1. Check auth:      garmin-cli --json login status
2. Create workout:  echo '<json>' | garmin-cli --json workout create --stdin
3. Parse response:  extract "id" from response data[0]
4. Schedule:        garmin-cli --json workout schedule <id> 2026-04-01
5. Verify:          garmin-cli --json workout calendar --from 2026-04-01 --to 2026-04-01
```

---

### Write-specific error codes

| Code | Context | Meaning |
|------|---------|---------|
| `INVALID_INPUT` | `workout create/update` | JSON schema validation failed — check required fields and enum values |
| `NOT_FOUND` | `workout update/delete/schedule` | Workout ID does not exist |
| `AUTH_FAILED` | Any write command | Session expired (401) or insufficient permissions (403) — re-login |

### Performance

```bash
# Thresholds -- fields: sport, lt_hr_bpm, lt_pace, ftp_watts, weight_kg
garmin-cli --json performance thresholds

# VO2 max -- fields: date, vo2max, sport
garmin-cli --json performance vo2max
garmin-cli --json performance vo2max --date 2026-03-11

# Lactate threshold zones -- fields: sport, lt_hr_bpm, lt_pace
garmin-cli --json performance zones
```

## Patterns for agents

### Login and check authentication

```bash
# Interactive login (saves session to ~/.garth)
garmin-cli login

# Non-interactive login (for scripting)
garmin-cli login --email user@example.com --password secret

# Check if a session is active
garmin-cli --json login status
```

`login status` returns `{"ok": true, ..., "data": [{"authenticated": true, "garth_home": "..."}]}` when a session is present and `"authenticated": false` when not. Exit code is always `0` (it is an informational command).

After login, verify the session is usable:

```bash
garmin-cli --json health status
```

If this returns `ok: true`, the session is valid. If `AUTH_MISSING` or `AUTH_FAILED`, run `garmin-cli login` first.

### Parse JSON output

```python
import json
import subprocess

result = subprocess.run(
    ["garmin-cli", "--json", "health", "sleep", "--days", "7"],
    capture_output=True, text=True
)
envelope = json.loads(result.stdout)
if envelope["ok"]:
    for row in envelope["data"]:
        print(row["date"], row["score"])
else:
    print(f"Error: {envelope['error_code']} - {envelope['error']}")
```

### Rate limiting

Garmin Connect enforces rate limits. The CLI retries 3 times with backoff (2s, 4s, 8s) for 429/5xx. If you still get `RATE_LIMITED`, wait 30-60 seconds before retrying. Space sequential calls by at least 1 second.

### CSV output

Use `--format csv` instead of `--json` when piping to data tools:

```bash
garmin-cli --format csv health sleep --days 30 > sleep.csv
```

## Output format reference

| Flag | Format | Stdout content |
|------|--------|---------------|
| *(default)* | Table | Human-readable table |
| `--json` | JSON | Envelope with `ok`, `command`, `count`, `data`, `date_range` |
| `--format csv` | CSV | Header row + data rows |
| `--format json` | JSON | Same as `--json` |

---

## MCP Server (Alternative)

For Claude Code/Desktop integration via MCP protocol instead of shell commands. Uses MCP Python SDK v2 (MCPServer).

### Install

```bash
pip install "garmin-cli[mcp]"
```

### Register with Claude Code (stdio)

```bash
claude mcp add --transport stdio garmin -- garmin-cli mcp-server
```

Or with a custom garth home:

```bash
claude mcp add --transport stdio garmin -- garmin-cli --garth-home /path/to/.garth mcp-server
```

### HTTP transports (SSE / streamable-http)

```bash
garmin-cli mcp-server --transport streamable-http --host 127.0.0.1 --port 8000
garmin-cli mcp-server --transport sse --host 127.0.0.1 --port 8000
```

See README.md for full HTTP transport options and authentication notes.

### Available tools

Read-only CLI commands are exposed as MCP tools (write operations like workout create/update/delete are not included):

| Tool | Parameters | Returns |
|------|-----------|---------|
| `health_sleep` | `start_date`, `end_date` | `{count, rows}` |
| `health_hrv` | `start_date`, `end_date` | `{count, rows}` |
| `health_weight` | `start_date`, `end_date` | `{count, rows}` |
| `health_daily_summary` | `start_date`, `end_date` | `{count, rows}` — steps, floors, intensity minutes, calories, resting HR (one API call per day) |
| `health_steps` | `start_date`, `end_date` | `{count, rows}` — steps, distance, step goal (native range API) |
| `health_intensity_minutes` | `start_date`, `end_date` | `{count, rows}` — moderate/vigorous minutes, weekly goal (native range API) |
| `health_body_battery` | `start_date`, `end_date` | `{count, rows}` |
| `health_stress` | `start_date`, `end_date` | `{count, rows}` |
| `health_spo2` | `start_date`, `end_date` | `{count, rows}` |
| `health_resting_hr` | `start_date`, `end_date` | `{count, rows}` |
| `health_readiness` | `start_date`, `end_date` | `{count, rows}` |
| `health_training_status` | `date` | `{count, rows}` |
| `activity_list` | `limit?`, `start?`, `activity_type?`, `search?` | `{count, rows}` |
| `activity_get` | `activity_id` | `{count, rows}` |
| `activity_weather` | `activity_id` | `{count, rows}` |
| `workout_list` | `limit?` | `{count, rows}` |
| `workout_get` | `workout_id` | `{count, rows}` |
| `workout_calendar` | `start_date`, `end_date` | `{count, rows}` |
| `performance_race_predictions` | *(none)* | `{count, rows}` — predicted times for 5K, 10K, half marathon, marathon |
| `performance_endurance_score` | `start_date`, `end_date` | `{count, rows}` — endurance score and classification (one API call per day) |
| `performance_hill_score` | `start_date`, `end_date` | `{count, rows}` — hill score, endurance score, strength score (one API call per day) |
| `performance_thresholds` | *(none)* | `{count, rows}` |
| `performance_vo2max` | `date?` | `{count, rows}` |
| `performance_zones` | *(none)* | `{count, rows}` |
| `device_list` | *(none)* | `{count, rows}` — registered devices with type and last sync |
| `login_status` | *(none)* | `{authenticated, garth_home}` |

Dates use `YYYY-MM-DD` format. Max date range: 90 days. Errors surface as MCP ToolError with the original error message.

SKILL.md remains the default and simpler integration method. Use MCP when you want native tool semantics without shell command parsing.
