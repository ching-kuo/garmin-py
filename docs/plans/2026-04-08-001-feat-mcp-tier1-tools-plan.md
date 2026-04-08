---
title: "feat: Add Tier 1 MCP tools (steps, race predictions, scores, floors, devices)"
type: feat
status: active
date: 2026-04-08
deepened: 2026-04-08
---

# feat: Add Tier 1 MCP tools

## Overview

Expand the MCP server from 19 to ~27 tools by adding the most commonly queried Garmin domains that are currently missing: daily summary/steps, race predictions, endurance/hill scores, intensity minutes, and devices.

## Problem Frame

The MCP server currently covers health metrics, activities, workouts, and performance thresholds — but misses the most basic fitness data people ask about: "how many steps did I take?", "what's my predicted marathon time?", "which device recorded this?". These are high-frequency queries that any fitness-focused LLM integration needs.

## Requirements Trace

- R1. Add daily summary data (steps, distance, calories, floors, intensity minutes — all from one API call)
- R2. Add race predictions (latest predicted times for 5K, 10K, half marathon, marathon)
- R3. Add endurance score and hill score metrics (separate tools, each single-date)
- R4. Add device list and last-used device
- R5. All new tools follow existing patterns: envelope response, ToolError on failure, 90-day max range
- R6. E2E tests that hit real Garmin API endpoints (gated behind --e2e flag)

## Scope Boundaries

- No write operations (read-only tools only)
- No CLI commands — MCP tools only for this iteration
- No separate floors/intensity-minutes endpoints — daily summary already includes these fields
- No hydration or nutrition (Tier 2)

## Context & Research

### Verified API Paths (from garth library source)

| Tool | API Path | Params | Source |
|------|----------|--------|--------|
| Daily summary | `/usersummary-service/usersummary/daily/?calendarDate={date}` | calendarDate (ISO) | garth/data/daily_summary.py:54 |
| Steps range | `/usersummary-service/stats/steps/daily/{start}/{end}` | path params | garth/stats/steps.py:17 |
| Intensity mins range | `/usersummary-service/stats/im/daily/{start}/{end}` | path params | garth/stats/intensity_minutes.py:17 |
| Race predictions | `/metrics-service/metrics/racepredictions` | none | garth connectapi |
| Endurance score | `/metrics-service/metrics/endurancescore` | calendarDate (ISO) | garth/data/garmin_scores.py:40,44 |
| Hill score | `/metrics-service/metrics/hillscore` | calendarDate (ISO) | garth/data/garmin_scores.py:39,41 |
| Device list | `/device-service/deviceregistration/devices` | none | garminconnect source |
| Device last used | `/device-service/deviceservice/mylastused` | none | garminconnect source |

### Key Finding: No displayName Needed

The garth library's `DailySummary.get()` calls `/usersummary-service/usersummary/daily/?calendarDate={date}` without any displayName parameter. The steps stats endpoint uses path params: `/usersummary-service/stats/steps/daily/{start}/{end}`. This resolves the BLOCKED finding from Codex review.

### Daily Summary vs Separate Endpoints

The daily summary response already includes: `total_steps`, `total_distance_meters`, `floors_ascended`, `floors_descended`, `moderate_intensity_minutes`, `vigorous_intensity_minutes`, `active_kilocalories`, `resting_heart_rate`, `average_stress_level`, `body_battery_highest_value`, `average_spo_2`. This is a single API call that returns everything.

Decision: Use daily summary as the primary "steps" tool. It gives steps + floors + intensity minutes + more in one call. For date ranges, use the stats endpoints which support `{start}/{end}` path params natively.

### Endurance/Hill Scores Are Single-Date

Both `/metrics-service/metrics/endurancescore` and `/metrics-service/metrics/hillscore` accept a single `calendarDate` parameter. For date ranges, use `_collect_daily_range` pattern.

### Relevant Code Patterns

- **Endpoint pattern**: `_request(url, params=params)` wrapping `garth.connectapi`, with `_make_request` for retry/error handling
- **Daily collection**: `_collect_daily_range(start, end, fetcher)` in health.py iterates day-by-day for single-date APIs
- **Stats range pattern**: Stats APIs like steps and intensity minutes accept `{start}/{end}` path params natively (no daily iteration needed)
- **Serializer pattern**: `serialize_xyz(raw) -> list[dict[str, Any]]` with defensive extraction via `_get_nested()`
- **MCP tool pattern**: `@mcp.tool()` decorator, `_parse_date_range` validation, `ensure_authenticated(config)`, `_envelope(serialize_xyz(raw))`
- **Test pattern**: Mock `ensure_authenticated` + endpoint function, call via `_call(server, tool_name, args)`, assert envelope shape

## Key Technical Decisions

- **Daily summary as primary steps tool**: One API call returns steps, floors, intensity minutes, calories, and more. No need for 3 separate endpoints.
- **Stats API for ranges**: Steps and intensity minutes have native range support via `/stats/steps/daily/{start}/{end}` — no `_collect_daily_range` needed.
- **New endpoint module for metrics**: `src/garmin_cli/endpoints/metrics.py` for race predictions + scores (metrics-service domain).
- **New endpoint module for devices**: `src/garmin_cli/endpoints/devices.py` for device-service calls.
- **Daily summary goes in health.py**: It's a usersummary-service endpoint, same domain family as existing health data.
- **Endurance/hill scores use _collect_daily_range**: These are single-date APIs; for MCP date range tools, iterate daily.

## Open Questions

### Resolved During Planning

- **DisplayName needed?** No. garth's DailySummary.get() uses calendarDate only (verified in garth source).
- **Where do metrics endpoints go?** New `metrics.py` module — performance.py handles biometric-service, metrics-service is different.
- **Separate floors/intensity endpoints?** No. Daily summary includes all three. For dedicated range queries, use the stats API.
- **Endurance/hill score aggregation?** Both are daily single-date with calendarDate param (verified in garth/data/garmin_scores.py).

### Deferred to Implementation

- **Exact race prediction response shape**: Need real API response. Serializer will be defensive.
- **Device response fields**: Need real API response to finalize serializer field names.

## Implementation Units

- [ ] **Unit 1: Endpoint layer — health additions (daily summary, steps range, intensity minutes range)**

**Goal:** Add endpoint functions for daily summary and stats-based range queries.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/garmin_cli/endpoints/health.py`
- Test: `tests/test_mcp_server.py`

**Approach:**
- `get_daily_summary(day: date) -> dict` — calls `/usersummary-service/usersummary/daily/?calendarDate={date}`
- `get_daily_summary_range(start: date, end: date) -> list` — wraps with `_collect_daily_range`
- `get_steps_range(start: date, end: date) -> list` — calls `/usersummary-service/stats/steps/daily/{start}/{end}` (native range)
- `get_intensity_minutes_range(start: date, end: date) -> list` — calls `/usersummary-service/stats/im/daily/{start}/{end}` (native range)

**Execution note:** TDD — write failing tests first, then implement.

**Patterns to follow:**
- `get_stress(day)` — single-day pattern
- `get_stress_range(start, end)` — `_collect_daily_range` pattern
- `get_hrv(start, end)` — native range endpoint pattern

**Test scenarios:**
- Happy path: get_daily_summary returns dict with totalSteps, totalDistanceMeters, floorsAscended, moderateIntensityMinutes fields
- Happy path: get_steps_range returns list of step data dicts
- Happy path: get_intensity_minutes_range returns list of intensity minute dicts
- Edge case: API returns None → coalesced to empty dict/list
- Error path: 404 → GarminCliError with NOT_FOUND

**Verification:** All endpoint functions callable, return normalized data.

---

- [ ] **Unit 2: Endpoint layer — metrics (race predictions, endurance score, hill score)**

**Goal:** Create new metrics endpoint module for metrics-service API calls.

**Requirements:** R2, R3

**Dependencies:** None (parallel with Unit 1)

**Files:**
- Create: `src/garmin_cli/endpoints/metrics.py`
- Test: `tests/test_mcp_server.py`

**Approach:**
- `get_race_predictions() -> list` — calls `/metrics-service/metrics/racepredictions`
- `get_endurance_score(day: date) -> dict` — calls `/metrics-service/metrics/endurancescore` with `params={"calendarDate": day.isoformat()}`
- `get_endurance_score_range(start, end) -> list` — wraps with `_collect_daily_range`
- `get_hill_score(day: date) -> dict` — calls `/metrics-service/metrics/hillscore` with `params={"calendarDate": day.isoformat()}`
- `get_hill_score_range(start, end) -> list` — wraps with `_collect_daily_range`

**Execution note:** TDD — write failing tests first.

**Patterns to follow:**
- `src/garmin_cli/endpoints/performance.py` — module structure with local `_request()` helper
- `src/garmin_cli/endpoints/health.py` — `_collect_daily_range` pattern for range variants

**Test scenarios:**
- Happy path: get_race_predictions returns list/dict of predictions
- Happy path: get_endurance_score returns dict with overallScore, calendarDate
- Happy path: get_hill_score returns dict with overallScore, calendarDate
- Edge case: No predictions available → empty list
- Edge case: Score API returns None → coalesced to empty dict
- Error path: 404 → GarminCliError

**Verification:** All functions return data matching expected shapes.

---

- [ ] **Unit 3: Endpoint layer — devices**

**Goal:** Create new devices endpoint module.

**Requirements:** R4

**Dependencies:** None (parallel with Units 1-2)

**Files:**
- Create: `src/garmin_cli/endpoints/devices.py`
- Test: `tests/test_mcp_server.py`

**Approach:**
- `get_devices() -> list` — calls `/device-service/deviceregistration/devices`
- `get_device_last_used() -> dict` — calls `/device-service/deviceservice/mylastused`

**Execution note:** TDD — write failing tests first.

**Patterns to follow:**
- `src/garmin_cli/endpoints/activities.py` — simple GET pattern

**Test scenarios:**
- Happy path: get_devices returns list of device dicts
- Happy path: get_device_last_used returns single device dict
- Edge case: No devices → empty list
- Error path: 404 → GarminCliError

**Verification:** Both functions callable and return device data.

---

- [ ] **Unit 4: Serializers for all new tools**

**Goal:** Add serializer functions for all new data types.

**Requirements:** R1-R4

**Dependencies:** Units 1-3 (need to know raw response shapes)

**Files:**
- Modify: `src/garmin_cli/serializers.py`
- Test: `tests/test_mcp_server.py`

**Approach:**
- `serialize_daily_summary(raw)` → extract date, steps, distance_km, calories, floors_ascended, floors_descended, moderate_intensity_min, vigorous_intensity_min, resting_hr
- `serialize_steps(raw)` → extract date, total_steps, total_distance, step_goal (for stats range endpoint)
- `serialize_intensity_minutes(raw)` → extract date, moderate_min, vigorous_min, weekly_goal (for stats range endpoint)
- `serialize_race_predictions(raw)` → extract race_type, predicted_time_seconds (field names UNVERIFIED until E2E)
- `serialize_endurance_score(raw)` → extract date, score, classification
- `serialize_hill_score(raw)` → extract date, score, endurance_score, strength_score
- `serialize_device(raw)` → extract device_id, display_name, device_type, last_sync (field names UNVERIFIED until E2E)

**Execution note:** TDD — write tests with expected output shapes, then implement. Mark field names as UNVERIFIED where we lack sample payloads.

**Patterns to follow:**
- `serialize_training_readiness()` — simple field mapping with `_listify()`
- `serialize_sleep()` — defensive extraction with nested wrappers

**Test scenarios:**
- Happy path: Each serializer produces expected field names from sample raw data
- Edge case: Missing fields → None values in output
- Edge case: Empty input / None → empty list
- Edge case: Non-dict input → empty list (via `_listify`)

**Verification:** All serializers return `list[dict[str, Any]]` with documented fields.

---

- [ ] **Unit 5: MCP tools registration**

**Goal:** Wire all new endpoints + serializers as MCP tools.

**Requirements:** R1-R5

**Dependencies:** Units 1-4

**Files:**
- Modify: `src/garmin_cli/mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Approach:**
Add 7 new tools following exact existing pattern:
- `health_daily_summary(start_date, end_date)` — daily summary with steps, floors, intensity minutes
- `health_steps(start_date, end_date)` — steps range via stats API
- `health_intensity_minutes(start_date, end_date)` — intensity minutes range via stats API
- `performance_race_predictions()` — no date params, returns latest predictions
- `performance_endurance_score(start_date, end_date)` — endurance score over range (daily collection)
- `performance_hill_score(start_date, end_date)` — hill score over range (daily collection)
- `device_list()` — all registered devices (includes last-used info)

Note: Collapsed device_list and device_last_used into one tool since device_last_used can be derived from the device list.

**Execution note:** TDD — update EXPECTED_TOOLS set in test first, then implement each tool.

**Patterns to follow:**
- `health_sleep()` — date range tool with _parse_date_range, ensure_authenticated, serialize, envelope
- `performance_thresholds()` — no-argument tool pattern
- `login_status()` — simple getter pattern

**Test scenarios:**
- Happy path: Each tool returns envelope with count and rows
- Happy path: Tool registration test includes all new tools in EXPECTED_TOOLS
- Edge case: Invalid date format → ToolError
- Edge case: Date range > 90 days → ToolError
- Error path: GarminCliError from endpoint → ToolError with message
- Error path: AUTH_MISSING → ToolError with login hint

**Verification:** All tools callable via `_call()`, return correct envelope shape. Total tool count increases from 19 to 26.

---

- [ ] **Unit 6: E2E tests**

**Goal:** Add real API tests for new endpoints, gated behind --e2e flag.

**Requirements:** R6

**Dependencies:** Unit 5

**Files:**
- Modify or create: `tests/e2e/test_mcp_e2e.py` or add to existing e2e test file
- Test: Self-contained

**Approach:**
- Test each new MCP tool against real Garmin Connect API
- Use rate limiting delay (5s default) between calls
- Validate response envelope shape and field names
- Skip if no auth session available
- Capture real response payloads to verify serializer field names marked UNVERIFIED

**Execution note:** These tests require a valid garth session. Run manually with `pytest --e2e`.

**Patterns to follow:**
- Existing e2e test patterns in the project

**Test scenarios:**
- Integration: Each new MCP tool returns valid envelope from real API
- Integration: Response rows contain expected field names
- Integration: Empty or single-day date ranges return valid envelopes

**Verification:** `pytest tests/ --e2e` passes with real Garmin session.

## System-Wide Impact

- **MCP tool count**: 19 → 26
- **New endpoint modules**: `metrics.py`, `devices.py` added to `endpoints/`
- **Serializers**: ~7 new functions in `serializers.py`
- **No CLI changes**: MCP-only expansion
- **No auth changes**: Uses existing `ensure_authenticated` pattern
- **Unchanged invariants**: All existing 19 tools remain unchanged

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Race prediction response shape unknown | Serializer is defensive; E2E tests capture real shape; field names marked UNVERIFIED |
| Device response shape unknown | Same defensive strategy; UNVERIFIED fields |
| Daily summary per-day iteration slow for 90-day ranges | Steps and intensity minutes use native range APIs; only daily summary + scores iterate daily |
| Rate limiting during daily-iteration range queries | Existing 0.5s sleep between calls in `_collect_daily_range`; E2E tests use 5s delay |
| Score APIs may not be available for all users | Serializers handle None/empty responses gracefully |

## Sources & References

- garth library source (verified API paths in garth/data/ and garth/stats/)
- Taxuspt/garmin_mcp project (cross-referenced API coverage)
- Existing garmin-cli codebase patterns
