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
- Authentication: run `garmin-cli login`, or use a saved session at `~/.garminconnect`, or set env vars `GARMIN_EMAIL` / `GARMIN_PASSWORD`

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

# Steps -- fields: date, total_steps, total_distance, step_goal
garmin-cli --json health steps --days 7

# Daily summary -- fields: date, total_steps, distance_km, calories, floors, moderate_intensity_minutes, vigorous_intensity_minutes, resting_hr
# Note: one API call per day — large ranges may be slow
garmin-cli --json health daily-summary --days 7

# Intensity minutes -- fields: date, moderate_value, vigorous_value, weekly_goal
garmin-cli --json health intensity-minutes --days 7
```

### Activities

```bash
# List recent activities -- fields: id, date, name, type, distance_km, duration_min, avg_hr
garmin-cli --json activity list --limit 10
garmin-cli --json activity list --limit 10 --type running
garmin-cli --json activity list --limit 10 --search "morning run"
garmin-cli --json activity list --from 2026-03-01 --to 2026-03-31
garmin-cli --json activity list --days 7

# Get a single activity by ID -- same fields as list
garmin-cli --json activity get 12345678901

# Sport-aware detail. Cycling rides surface power suite (avg/max/normalized,
# TSS, IF); running activities surface cadence_spm, GCT, vertical
# oscillation/ratio, stride length, training effect; pool swims surface
# SWOLF, total strokes, average stroke rate, distance per stroke. JSON
# uses a stable union schema -- every key present (null for sport-
# inapplicable). Includes a top-level `unavailable` array when any
# registry-known metric is not produced.
garmin-cli --json activity get 12345678901 --detail

# Detail + lap data in one envelope (--laps appends `laps` array).
# Pool-swim activities auto-route to per-pool-length rows.
garmin-cli --json activity get 12345678901 --detail --laps

# Lap-by-lap data (run/bike) or per-pool-length data (lap_swimming)
garmin-cli --json activity laps 12345678901

# HR time-in-zone breakdown -- fields: zone, zone_low_bpm, zone_high_bpm, seconds_in_zone, minutes_in_zone
garmin-cli --json activity zones 12345678901

# Weather for an activity -- fields: temperature, apparent_temp, dew_point, humidity, wind_speed, wind_gust, wind_direction, wind_direction_compass, condition
# Temperature fields are in the Garmin account's display unit (often Fahrenheit). No precipitation-probability or icon-code field.
garmin-cli --json activity weather 12345678901

# Metric descriptors for an activity's detail stream -- fields: key, unit, metricsIndex
# Use to discover what metrics a watch recorded before requesting samples
garmin-cli --json activity metrics-describe 12345678901

# Download an activity file to disk -- fields: id, format, path, size_bytes
# --fmt: original (FIT in a ZIP, default), tcx, gpx, kml, csv. Never prints
# binary to stdout; refuses to overwrite unless --force.
garmin-cli --json activity download 12345678901 --fmt gpx --output run.gpx

# Upload an activity file (.fit / .gpx / .tcx) -- fields: file, status, activity_id
garmin-cli --json activity upload run.fit

# Delete an activity (--confirm skips the interactive prompt) -- fields: id, status
garmin-cli --json activity delete 12345678901 --confirm
```

`--limit` defaults to 20, max 100. `--type` filters by Garmin activity type key (e.g., `running`, `cycling`, `swimming`).

#### Detailed sport-specific metrics glossary

| Metric (output key) | Unit | Sport applicability | What it is |
|---------------------|------|---------------------|------------|
| `norm_power_w` | W | Cycling | Normalized Power -- weighted average that accounts for variable effort |
| `tss` | -- | Cycling | Training Stress Score (depends on FTP being set in Garmin Connect) |
| `intensity_factor` | -- | Cycling | NP / FTP ratio for the ride |
| `avg_cadence_rpm` | rpm | Cycling | Pedal cadence |
| `avg_cadence_spm` | spm | Running | Step cadence |
| `avg_ground_contact_time` | ms | Running | Time foot is in contact with the ground per stride (requires HRM-Pro/Run/Tri or RD pod) |
| `avg_vertical_oscillation` | cm | Running | Vertical "bounce" per stride |
| `avg_vertical_ratio` | % | Running | Vertical oscillation as a percentage of stride length |
| `avg_stride_length` | cm | Running | Average stride length |
| `swolf` | -- | Lap swimming | Strokes + seconds per pool length (lower is better) |
| `total_strokes` | -- | Lap swimming | Total stroke count |
| `avg_stroke_rate` | strokes/min | Lap swimming | Average stroke rate |
| `distance_per_stroke` | m | Lap swimming | Average distance covered per stroke |
| `aerobic_training_effect` | 0.0-5.0 | Run, Bike | Aerobic load impact score |
| `anaerobic_training_effect` | 0.0-5.0 | Run, Bike | Anaerobic load impact score |
| `vo2max` | mL/kg/min | Run, Bike | Sport-specific vO2max estimate |
| `recovery_time_h` | h | Run, Bike | Recommended recovery hours after the activity |

#### Capability manifest

`activity_get(detail=True)` returns an `unavailable` array (omitted when empty) describing why a metric isn't in the response:

| Reason | Meaning | What an LLM agent should do |
|--------|---------|-----------------------------|
| `not_applicable_to_sport` | The metric doesn't apply to this sport (e.g. SWOLF on a bike ride) | Skip this metric for cross-sport rollups |
| `absent_in_response` | The metric applies to this sport but isn't in the payload (typically: missing FTP/LTHR profile, hardware that doesn't track it, or recent firmware change) | Mention the gap; do not infer a value |

Multisport parents (triathlon, duathlon) union per-child manifests with `leg_index` (0-based) attached to each entry.

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

# Create from YAML file
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

# Race predictions -- fields: race_type, predicted_time_seconds, distance_meters
garmin-cli --json performance race-predictions

# Endurance score -- fields: date, overall_score, endurance_classification
# Note: one API call per day — large ranges may be slow
garmin-cli --json performance endurance-score --days 7

# Hill score -- fields: date, overall_score, endurance_score, strength_score
# Note: one API call per day — large ranges may be slow
garmin-cli --json performance hill-score --days 7
```

### Devices

```bash
# List registered devices -- fields: device_id, display_name, device_type, last_sync_time
garmin-cli --json device list
```

## Patterns for agents

### Login and check authentication

```bash
# Interactive login (saves session to ~/.garminconnect)
garmin-cli login

# Non-interactive login (for scripting)
garmin-cli login --email user@example.com --password secret

# Check if a session is active
garmin-cli --json login status
```

`login status` returns `{"ok": true, ..., "data": [{"authenticated": true, "garmin_home": "..."}]}` when a session is present and `"authenticated": false` when not. Exit code is always `0` (it is an informational command).

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

Or with a custom session directory:

```bash
claude mcp add --transport stdio garmin -- garmin-cli --garmin-home /path/to/.garminconnect mcp-server
```

### HTTP transports (SSE / streamable-http)

`--host` defaults to `127.0.0.1`. Non-loopback binds require the `GARMIN_MCP_BEARER_TOKEN` environment variable; when set, the MCP SDK gates every tool call (read and write) through `Authorization: Bearer <token>`.

```bash
garmin-cli mcp-server --transport streamable-http --port 8000
garmin-cli mcp-server --transport sse --port 8000

# Non-loopback (requires bearer token):
export GARMIN_MCP_BEARER_TOKEN="<long-random-token>"
garmin-cli mcp-server --transport streamable-http --host 0.0.0.0 --port 8000
```

See README.md for full HTTP transport options and authentication notes.

### Available tools

Read tools and four workout write tools (`workout_create`, `workout_schedule`, `workout_update`, `workout_delete`) are exposed. Write tools carry the SDK `destructive_hint` annotation for schedule/update/delete; create and update accept `dry_run=True` for a no-write preview.

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
| `activity_list` | `limit?`, `start?`, `activity_type?`, `search?`, `start_date?`, `end_date?` | `{count, rows}` — `start_date`/`end_date` (YYYY-MM-DD) must be provided together |
| `activity_get` | `activity_id`, `detail?` | `{count, rows, children?, unavailable?}` — `detail=true` projects sport-aware metrics (running dynamics, cycling power, swim aggregates, training response) under a stable union schema and adds an `unavailable[]` capability manifest when non-empty |
| `activity_weather` | `activity_id` | `{count, rows}` |
| `activity_laps` | `activity_id` | `{count, rows}` — per-lap rows (run/bike) or per-pool-length rows (lap_swimming) with sport-aware fields. Auto-routes pool swim to typed_splits backend method. Multisport parents fan out to each child leg's laps with a 0-based ``leg_index`` stamped on every row |
| `activity_hr_zones` | `activity_id` | `{count, rows}` — one row per HR zone with `zone`, `zone_low_bpm`, `zone_high_bpm`, `seconds_in_zone`, `minutes_in_zone` |
| `activity_metrics_describe` | `activity_id` | `{count, rows}` — descriptors for the metric stream: `key`, `unit`, `metricsIndex`. Use to discover what metrics a watch recorded for a specific activity |
| `workout_list` | `limit?` | `{count, rows}` |
| `workout_get` | `workout_id` | `{count, rows}` |
| `workout_calendar` | `start_date`, `end_date` | `{count, rows}` |
| `workout_create` | `workout`, `dry_run?` | `{count, rows}` — `ok: true, action: "created", workout_id` on success; `ok: true, dry_run: true, wire_payload, validation_report` on dry-run; `ok: false, error_code: "INVALID_INPUT", errors` on validation failure. Dry-run skips all Garmin contact. |
| `workout_schedule` | `workout_id`, `date` | `{count, rows}` — `ok: true, action: "scheduled", workout_id, workout_schedule_id, date`. **Destructive.** |
| `workout_update` | `workout_id`, `workout`, `dry_run?` | `{count, rows}` — `ok: true, action: "updated", workout_id` on success; dry-run returns the merged wire payload (one Garmin read, no write). Merge semantics preserve `workoutId`/`ownerId`/`createdDate`/`atpPlanId`. **Destructive.** |
| `workout_delete` | `workout_id` | `{count, rows}` — `ok: true, action: "deleted", workout_id`. **Destructive.** |
| `performance_race_predictions` | *(none)* | `{count, rows}` — predicted times for 5K, 10K, half marathon, marathon |
| `performance_endurance_score` | `start_date`, `end_date` | `{count, rows}` — endurance score and classification (one API call per day) |
| `performance_hill_score` | `start_date`, `end_date` | `{count, rows}` — hill score, endurance score, strength score (one API call per day) |
| `performance_thresholds` | *(none)* | `{count, rows}` |
| `performance_vo2max` | `date?` | `{count, rows}` |
| `performance_zones` | *(none)* | `{count, rows}` |
| `device_list` | *(none)* | `{count, rows}` — registered devices with type and last sync |
| `login_status` | *(none)* | `{authenticated, garmin_home}` |
| `report_snapshot` | `kind` (`morning`\|`evening`\|`weekly`), `date?` | `{kind, date_range, sections, unavailable?}` — one composite call that fans out the day's (or week's) reads server-side. `sections` maps section name → rows (same shapes as the per-domain tools). Sections with no data are empty and listed in `unavailable` with a `reason` (`not_found`\|`no_data`). `date` (YYYY-MM-DD) defaults to today; `weekly` covers the anchor day and the six prior days. |

Dates use `YYYY-MM-DD` format. Max date range: 90 days. Errors surface as MCP ToolError with the original error message.

#### `report_snapshot` section composition

Use `report_snapshot` to build a recurring morning/evening/weekly report in a single tool call instead of orchestrating a dozen individual reads. Each `kind` returns a fixed set of sections:

| `kind` | Sections |
|--------|----------|
| `morning` | `sleep`, `hrv` (last night), `readiness`, `body_battery`, `planned_today` |
| `evening` | `steps`, `intensity_minutes`, `stress`, `body_battery`, `activities_today`, `planned_tomorrow` |
| `weekly` | `sleep`, `hrv`, `stress`, `steps`, `resting_hr`, `body_battery` (7-day), `activities`, `endurance_score`, `race_predictions` |

Because the section set is fixed, a report can never silently drop a metric: an absent metric is an empty section plus an `unavailable` entry, so the agent can state the gap rather than infer a value. Auth, rate-limit, and server/network failures fail the whole call (the snapshot would be untrustworthy); only per-day "no data" gaps degrade to `unavailable`.

`date_range` reports the anchor day (or the 7-day window for `weekly`). The `evening` `planned_tomorrow` section deliberately holds the day *after* the anchor and so falls outside `date_range` — it is a forward-looking section, not part of the reported window.

Latency note: `weekly` (and the `daily-summary`/`endurance-score`/`hill-score` reads generally) fan out one upstream request per day; snapshot sections and per-day requests now run on bounded thread pools (`GARMIN_CLI_FETCH_CONCURRENCY`, default `4`), so a weekly snapshot takes a few seconds instead of 10-20s. `GARMIN_CLI_DAILY_CALL_DELAY` (seconds, default `0.5`) still throttles how fast per-day requests are submitted — tune it down if your MCP client times out, up (or set concurrency to `1`) to be gentler on Garmin's rate limits.

`activity_get(detail=true)` may carry an `unavailable[]` array (omitted when empty) annotating registry-known metrics with `not_applicable_to_sport` (the metric isn't meaningful for the sport) or `absent_in_response` (the metric applies but the upstream payload didn't include it). Multisport parents union per-child manifests with a 0-based `leg_index` attached. `activity_laps`, `activity_hr_zones`, and `activity_metrics_describe` do not carry the manifest in this release; use `activity_get(detail=true)` for sport-applicability checks.

Planned but not yet implemented: `activity_swim_lengths` (covered by `activity_laps` for `lap_swimming`) and `activity_metrics_series` (down-sampling policy pending). Hardware/profile manifest reasons (`requires_hardware`, `requires_profile_config`) will land alongside a future profile/threshold fetch.

SKILL.md remains the default and simpler integration method. Use MCP when you want native tool semantics without shell command parsing.
