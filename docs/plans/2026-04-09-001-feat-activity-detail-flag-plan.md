---
title: "feat: Add --detail flag to activity get for extended metrics"
type: feat
status: active
date: 2026-04-09
---

# feat: Add --detail flag to activity get for extended metrics

## Overview

Add a `--detail` / `-d` flag to `garmin-cli activity get` (and a `detail` parameter to the MCP `activity_get` tool) that returns extended activity fields: calories, elevation, speed, cadence, power (cycling), and training stress metrics. The default compact view stays unchanged.

## Problem Frame

The current `activity get` command returns only 7 fields (id, date, name, type, distance, duration, avg_hr). Cycling users need power metrics (avg power, normalized power, max power, TSS, IF), and all users benefit from calories, elevation gain, max HR, and cadence. The Garmin API response likely contains these fields based on community reverse-engineering -- the serializer must handle absent fields gracefully since field availability varies by device and sport.

## Requirements Trace

- R1. `activity get <id> --detail` shows extended fields alongside existing ones
- R2. Default output (no flag) remains unchanged -- no breaking change
- R3. MCP `activity_get` gains an optional `detail: bool` parameter (default false)
- R4. Extended fields that are absent from the API response render as blank/null, not errors
- R5. All three output formats (table, JSON, CSV) support the extended view

## Scope Boundaries

- No sport-specific conditional column hiding (fields are null when inapplicable)
- No new API endpoints -- reuse existing `/activity-service/activity/{id}` response
- No changes to `activity list` (list endpoint returns fewer fields)
- No changes to multisport children serializer (separate concern)

## Context & Research

### Relevant Code and Patterns

- `src/garmin_cli/commands/activities.py:72-103` -- `get_cmd` uses `serialize_activity_summary` and selects columns via `COLUMNS_ACTIVITY_SUMMARY`
- `src/garmin_cli/serializers.py:465-483` -- `serialize_activity_summary` extracts 7 fields with `_coalesce` pattern for summaryDTO fallback
- `src/garmin_cli/serializers.py:7-81` -- 27 `COLUMNS_*` tuples define table/CSV column sets
- `src/garmin_cli/mcp_server.py:312-329` -- MCP `activity_get` tool wraps the same serializer
- `src/garmin_cli/output.py` -- `echo_table`, `echo_csv`, `echo_json` accept columns tuple to control rendering
- Existing pattern: `COLUMNS_ACTIVITY_SUMMARY` (compact) vs `COLUMNS_WORKOUT` / `COLUMNS_WORKOUT_DETAIL` (two detail levels for workouts)

### Garmin API Fields Available

The `/activity-service/activity/{id}` response includes these fields beyond the current 7. Fields are classified by verification status:

**Verified in repo** (present in test fixtures or code):

| Category | API Field | Output Key | Unit/Notes |
|----------|-----------|------------|------------|
| Calories | `calories` | `calories` | kcal |
| Elevation | `elevationGain` | `elevation_gain_m` | meters |
| Speed | `averageSpeed` | `avg_speed_kmh` | m/s -> km/h |

**Unverified** (from community reverse-engineering, may vary by device/sport):

| Category | API Field | Output Key | Unit/Notes |
|----------|-----------|------------|------------|
| HR | `maxHR` | `max_hr` | bpm |
| Elevation | `elevationLoss` | `elevation_loss_m` | meters |
| Speed | `maxSpeed` | `max_speed_kmh` | m/s -> km/h |
| Cadence | `averageRunningCadenceInStepsPerMinute` | `avg_cadence_spm` | spm (running only) |
| Cadence | `averageBikingCadenceInRevPerMinute` | `avg_cadence_rpm` | rpm (cycling only) |
| Power | `averagePower` | `avg_power_w` | watts |
| Power | `maxPower` | `max_power_w` | watts |
| Power | `normPower` | `norm_power_w` | watts (NP) |
| Training | `trainingStressScore` | `tss` | dimensionless |
| Training | `intensityFactor` | `intensity_factor` | dimensionless |

Source: [dotnet.garmin.connect GarminActivity model](https://github.com/sealbro/dotnet.garmin.connect/blob/main/Garmin.Connect/Models/GarminActivity.cs). Unverified field names should be validated during implementation by inspecting a real API response (log raw keys). All unverified fields must use the null-safe coalesce pattern.

## Key Technical Decisions

- **Single extended column set, not per-sport**: All extended fields are included in one `COLUMNS_ACTIVITY_DETAIL` tuple. Fields not present in the API response are null. This keeps the serializer simple and avoids sport-detection logic in the output layer.
- **Separate cadence columns per sport**: Running cadence (spm) and cycling cadence (rpm) use different units and are semantically different. Use `avg_cadence_spm` for running and `avg_cadence_rpm` for cycling as separate columns, matching the repo convention of encoding units in field names (e.g., `distance_km`, `duration_min`). Both columns appear in the detail view; one will be null depending on sport.
- **Speed conversion**: Convert m/s to km/h (multiply by 3.6) in the serializer, matching the `_km()` conversion pattern.
- **Reuse via shared base function**: Follow the `_normalize_workout_base` pattern used by `serialize_workout_summary`/`serialize_workout_detail`/`serialize_workout_mutate`. Extract a `_normalize_activity_base` function for the 7 shared fields, called by both `serialize_activity_summary` and the new `serialize_activity_detail`. This guarantees R2 (default unchanged) by construction.
- **Flag name**: `--detail` / `-d` aligns with the existing `COLUMNS_WORKOUT_DETAIL` naming precedent.
- **Multisport CSV with --detail**: When `--detail` is used on a multisport parent, CSV outputs the parent detail row followed by child rows (unchanged children columns). This matches the table behavior where both parent and children are shown.

## Implementation Units

- [ ] **Unit 1: Add detail serializer and column definition**

  **Goal:** Extract extended fields from API response alongside existing summary fields.

  **Requirements:** R1, R4

  **Dependencies:** None

  **Files:**
  - Modify: `src/garmin_cli/serializers.py`
  - Test: `tests/test_serializers.py`

  **Approach:**
  - Extract `_normalize_activity_base(activity, summary)` returning the 7 shared fields, following the `_normalize_workout_base` reuse pattern
  - Refactor `serialize_activity_summary` to call `_normalize_activity_base`
  - Add `COLUMNS_ACTIVITY_DETAIL` tuple: all 7 base fields + max_hr, calories, elevation_gain_m, elevation_loss_m, avg_speed_kmh, max_speed_kmh, avg_cadence_spm, avg_cadence_rpm, avg_power_w, max_power_w, norm_power_w, tss, intensity_factor
  - Add `serialize_activity_detail(raw)` that calls `_normalize_activity_base` then extends with detail fields using `_coalesce` for summaryDTO fallback
  - Add `_kmh(value)` helper to convert m/s to km/h (analogous to `_km`)
  - Separate cadence: `avg_cadence_spm` from `averageRunningCadenceInStepsPerMinute`, `avg_cadence_rpm` from `averageBikingCadenceInRevPerMinute`

  **Patterns to follow:**
  - `_normalize_workout_base` shared base pattern (line 186)
  - `serialize_activity_summary` coalesce pattern (lines 465-483)
  - `_km()`, `_minutes()` conversion helpers
  - `COLUMNS_ACTIVITY_SUMMARY` tuple structure

  **Test scenarios:**
  - Happy path: cycling activity with all power/cadence/elevation fields populated returns correct values with unit conversions
  - Happy path: running activity with running cadence (spm) and no power fields returns cadence_spm, nulls for cadence_rpm and power
  - Edge case: activity with no extended fields (all absent) returns nulls without error
  - Edge case: fields in summaryDTO but not top-level are picked up via coalesce
  - Edge case: speed conversion 0.0 m/s returns 0.0 km/h, null speed returns null
  - Happy path: existing 7 fields from `serialize_activity_summary` remain byte-identical after refactor to use `_normalize_activity_base`
  - Happy path: `serialize_activity_detail` output is a strict superset of `serialize_activity_summary` output (first 7 keys match)
  - Edge case: null/missing values in CSV render as empty strings, not "None"

  **Verification:** All tests pass; `serialize_activity_summary` behavior unchanged; `serialize_activity_detail` returns superset.

- [ ] **Unit 2: Add --detail flag to CLI command**

  **Goal:** Wire `--detail` / `-d` flag into `activity get` to select between compact and extended output.

  **Requirements:** R1, R2, R5

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `src/garmin_cli/commands/activities.py`
  - Test: `tests/test_commands/test_activities_cmd.py`

  **Approach:**
  - Add `@click.option("--detail", "-d", is_flag=True, default=False)` to `get_cmd`
  - When `detail=True`, use `serialize_activity_detail` + `COLUMNS_ACTIVITY_DETAIL` instead of `serialize_activity_summary` + `COLUMNS_ACTIVITY_SUMMARY`
  - No change to multisport children rendering
  - Import the new serializer and columns constant

  **Patterns to follow:**
  - `--stdin` flag pattern in workouts commands (`is_flag=True, default=False`)
  - Column selection in `render_output` calls

  **Test scenarios:**
  - Happy path: `activity get <id> --detail` outputs extended columns in table format
  - Happy path: `activity get <id> --detail --json` includes extended fields in JSON envelope
  - Happy path: `activity get <id> --detail --csv` outputs extended fields in CSV format
  - Happy path: `activity get <id>` (no flag) outputs unchanged compact view
  - Happy path: `activity get <id> -d` short flag works
  - Integration: multisport parent with `--detail` in table format shows extended parent fields + unchanged children table
  - Integration: multisport parent with `--detail` in CSV format outputs parent detail row (not suppressed as in current no-detail CSV)
  - Edge case: `--detail` with activity where extended fields are all null still renders without error

  **Verification:** CLI outputs extended fields when `--detail` is passed; default output is byte-identical to current behavior; multisport CSV shows parent row when `--detail` is used.

- [ ] **Unit 3: Add detail parameter to MCP tool**

  **Goal:** Expose the detail option to MCP clients (Claude Desktop, etc.).

  **Requirements:** R3, R4

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `src/garmin_cli/mcp_server.py`
  - Test: `tests/test_mcp_server.py`

  **Approach:**
  - Add `detail: bool = False` parameter to `activity_get` MCP tool
  - When true, use `serialize_activity_detail` instead of `serialize_activity_summary`
  - Update tool docstring to list the extended fields

  **Patterns to follow:**
  - Existing MCP tool parameter patterns (e.g., `limit: int = 20` defaults)
  - `_envelope(rows)` wrapping

  **Test scenarios:**
  - Happy path: `activity_get(id, detail=True)` returns rows with extended fields
  - Happy path: `activity_get(id)` (default) returns unchanged compact rows
  - Happy path: `activity_get(id, detail=False)` explicitly returns compact rows

  **Verification:** MCP tool returns extended fields when `detail=True`; default behavior unchanged.

## System-Wide Impact

- **API surface parity:** CLI `--detail` and MCP `detail=True` produce identical field sets
- **Unchanged invariants:** `activity list` command, multisport children serializer, and all other commands are unaffected
- **Error propagation:** No new error paths -- missing fields produce null values

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unverified API field names may differ from real responses | All field access uses null-safe coalesce; absent fields render as null. During implementation, log raw API keys from a real activity to validate field names |
| Table output too wide with 20 columns | Column names are concise; users can use `--json` or `--csv` for programmatic consumption. Table width is a known trade-off of showing all fields |
| Shared base refactor could regress summary output | `_normalize_activity_base` reuse pattern + explicit test that summary output is unchanged after refactor |

## Sources & References

- Garmin Connect API field names: [dotnet.garmin.connect GarminActivity model](https://github.com/sealbro/dotnet.garmin.connect/blob/main/Garmin.Connect/Models/GarminActivity.cs)
- Related code: `src/garmin_cli/serializers.py`, `src/garmin_cli/commands/activities.py`
