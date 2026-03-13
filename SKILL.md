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
```

`workout get` includes a `steps` array with structured step data (step_order, step_type, duration_type, duration_value, target_type, target_value_low, target_value_high) and a `steps_summary` string.

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
