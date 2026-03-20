# garmin-cli

A command-line tool for extracting health, activity, workout, and performance data from Garmin Connect. Designed for both human use (table output) and LLM agent consumption (JSON output).

## Installation

From a local checkout:

```bash
pip install .
```

Verify the installation:

```bash
garmin-cli --version
```

## Authentication

`garmin-cli` authenticates via the [`garth`](https://github.com/matin/garth) library.

### Interactive login (recommended)

```bash
garmin-cli login
# Email: your@email.com
# Password: (hidden)
# Login successful. Session saved at: ~/.garth
```

Use `--email` / `--password` to skip the prompts (useful for scripting):

```bash
garmin-cli login --email your@email.com --password yourpassword
```

Check login status at any time:

```bash
garmin-cli login status
# Logged in. Session saved at: ~/.garth

garmin-cli --json login status
# {"ok": true, "command": "login status", "count": 1, "data": [{"authenticated": true, "garth_home": "..."}]}
```

### Environment variables (alternative)

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
garmin-cli health sleep --days 1
```

### Custom session directory

```bash
garmin-cli --garth-home /path/to/session login
garmin-cli --garth-home /path/to/session health sleep --days 1
```

The session directory (`~/.garth`) contains OAuth tokens. It is created with `0o700` permissions. Symlinks are rejected. Do not share this directory.

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
    {"date": "2026-03-05", "duration_hours": 7.2, "score": 78, ...}
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
garmin-cli health sleep       [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health hrv         [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health weight      [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health body-battery [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health stress      [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health spo2        [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health resting-hr  [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health readiness   [--date DATE | --from DATE --to DATE | --days N]
garmin-cli health status      [--date DATE]
```

### Activities

```bash
garmin-cli activity list    [--limit N] [--type TYPE] [--search TEXT]
garmin-cli activity get     ACTIVITY_ID
garmin-cli activity weather ACTIVITY_ID
```

`--limit` defaults to 20, max 100. `--type` filters by activity type key (e.g., `running`, `cycling`).

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
```

`--ahead N` shows the next N days of planned workouts (future-facing). `--days N` shows past N days.

YAML input requires `pyyaml`: `pip install pyyaml`. See [SKILL.md](SKILL.md) for the full workout JSON schema reference and step/target types.

### Performance

```bash
garmin-cli performance thresholds
garmin-cli performance zones
garmin-cli performance vo2max
```

## Normalized JSON Schemas

Recent fixes normalized several JSON payloads for agent-safe output:

- `performance vo2max` returns `date`, `vo2max`, `sport`
- `performance zones` returns `sport`, `lt_hr_bpm`, `lt_pace`
- `workout calendar` includes `id`
- `workout get` includes `steps` and `steps_summary`
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
| `NOT_FOUND` | API endpoint unavailable (404) |
| `RATE_LIMITED` | 429 after 3 retries |
| `SERVER_ERROR` | 5xx after 3 retries |
| `NETWORK_ERROR` | Connection or timeout failure |
| `INVALID_INPUT` | Bad arguments or conflicting options |
| `INTERNAL_ERROR` | Unexpected error |

## Development

```bash
pip install -e ".[dev]"
pytest tests/            # unit tests (640+ tests, 96% coverage)
pytest tests/ --e2e      # unit + e2e tests (requires garth session)
```

E2E tests make real Garmin Connect API calls. They require a valid session in `~/.garth` (or `GARTH_HOME`). Set `E2E_RATE_LIMIT_SECONDS` (default: 5) to adjust the inter-request delay.
