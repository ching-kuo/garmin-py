# Changelog

## [3.0.0] - 2026-11-26

### Breaking

- `GARMIN_MCP_BEARER_TOKEN` must be at least 32 characters of the RFC 6750 token alphabet (`A-Z a-z 0-9 - . _ ~ + /`, optional trailing `=`); `mcp-server` refuses to start otherwise (generate one with `python -c "import secrets;print(secrets.token_urlsafe(32))"`).
- `GARMIN_MCP_BEARER_TOKEN` is now enforced on loopback HTTP binds too whenever the variable is present; a present-but-blank value refuses to start on any HTTP bind. Only stdio and loopback binds with the variable absent stay unauthenticated.
- MCP `activity_download` and `activity_upload` only read and write inside `GARMIN_MCP_FILE_ROOT` (default `~/Downloads/garmin-py`, created 0700 on first download); relative paths resolve under it, absolute paths must use the root's resolved form, no path component may be a symlink (even one pointing inside the root), and the download default moved there from the server's working directory. A custom value must be an absolute path (`~` allowed); one still containing an unexpanded `${...}` placeholder falls back to the default. The CLI `activity download` / `activity upload` commands are unchanged.
- `garmin-cli --json login` (and `login` with a non-terminal stdin) never prompts: missing credentials now fail with `AUTH_MISSING` (was `INVALID_INPUT`), and an MFA challenge without a supplied code fails with `MFA_REQUIRED`. Interactive prompts go to stderr.
- `GARMIN_HOME` / `--garmin-home` must be a directory: a `.json` file path (any case) or an existing file fails with `INVALID_INPUT`, and a path reached through a user-owned symlink in any component fails with `AUTH_FAILED` (root-owned system links such as macOS `/tmp` are allowed).
- After Garmin rejects (bad credentials, 401/403) or throttles (429/427) a login, the MCP server refuses new login attempts for 60 seconds, doubling per consecutive failure up to 15 minutes, and returns the cached error with `retry_after_seconds` (the first failure reports the wait it starts); a rejected MFA code pauses logins the same way, and a 429 on `submit_mfa_code` keeps the challenge but gates resubmission for the pause (a 5xx or network failure keeps it without a pause). The pause resets after a successful login or session resume, or when the configured email/password change. Network errors, timeouts and 5xx during login never pause logins.
- Login failures are classified instead of always blaming the credentials: Garmin 5xx reports `SERVER_ERROR`, an unreachable Garmin reports `NETWORK_ERROR`, and a throttle in any upstream shape (including SSO 427) reports `RATE_LIMITED`.
- Connection errors and timeouts (including DNS, TLS, and broken chunked responses) report `NETWORK_ERROR` ("Could not reach Garmin.") after the normal retries; they surfaced as `INTERNAL_ERROR` (CLI) or an unstructured MCP error. Local upstream failures with no network cause (an unreadable response or token store) are not retried and are not reported as network errors.
- Other Garmin 4xx responses on reads (400, 405, 422, ...) report `INVALID_INPUT` with the HTTP status in the message instead of `INTERNAL_ERROR`.
- Resuming or validating a saved session no longer reports `AUTH_FAILED` ("reconnect") or starts a credential login when Garmin throttles, returns 5xx (or 408/425), or is unreachable: those report `RATE_LIMITED`, `SERVER_ERROR`, or `NETWORK_ERROR`. `login status` exits 1 with that code instead of printing `authenticated: false`; `doctor` reports it as the session check's code; MCP `login_status` returns it in new optional `error_code` / `detail` fields; resources report it with a "could not check the Garmin session" message.
- Workout create, workout schedule, and activity upload are retried only on 429, never after a 5xx or timeout, since Garmin may already have applied the first attempt; a failed create may still have landed, so list before retrying.
- The `garmin://server/manifest` resource no longer lists `limits.steps_window_days`; steps ranges are no longer limited to 28 days.
- Workout input (`workout create` / `workout update`, MCP `workout_create` / `workout_update`, and inline plan workouts) rejects unknown or misspelled keys at the top, step, duration, and target level with a message naming the key and the allowed keys (for example `{"title": ...}` no longer reports "updated" without changing anything); a target only accepts the fields its type uses.
- A workout update must include at least one of `name`, `sport`, `description`, or `steps`; an empty `{}` update is `INVALID_INPUT`.
- Workout `description` is capped at 1024 characters.
- `training_plan_reschedule` returns a `destination_occupied` conflict without writing when the new date already holds a different workout; it used to schedule on top of it.
- Workout target `open` is sent to Garmin as `no.target` (id 1); it was sent as id 6, which is `pace.zone`. `cadence.zone` targets are sent with Garmin's key `cadence`.
- `coach_snapshot` / `coach snapshot` make at most 24 Garmin data requests, which is also the hard cap (2.13.0: 31), because resting HR is now one range request plus at most one per-day request for the current date; the calendar is still charged for two weekly pages plus the schedule lookup. `recent_daily_days` must be 1-9 (was 1-14) even with `include_extended_daily_baselines`, which ignores it: for example `baseline_days=7, recent_daily_days=10` with extended baselines was accepted in 2.13.0 and is now rejected.
- Activity, workout, and schedule ids must be positive integers: `0`, negative ids, booleans, and floats are `INVALID_INPUT` (CLI) or a tool validation error (MCP). CLI ids and `garmin://activity/{id}` must be plain ASCII digits, at most 20 (no sign, spaces, or `_`); MCP id parameters are strict integers, so `true`, `1.0`, and `"1"` fail schema validation instead of being coerced to `1`.
- Calendar items of type activity, weight, or nap never report a `workout_schedule_id`, even when they carry a `workoutId`; other items with a `workoutId` (including Garmin Coach types) do. Training plans no longer treat such items as occupying or satisfying a date.
- `activity delete`, `workout delete`, and `workout unschedule` never prompt under `--json` or without a terminal: pass `--confirm` (new aliases `--yes` / `-y`) or they fail with `INVALID_INPUT`. The id is validated first, the prompt goes to stderr before any login, and any answer but y/yes (or end of input) prints `Aborted.` (exit 1, `INVALID_INPUT`) instead of an empty `INTERNAL_ERROR`.
- Ctrl-C (or end of input at a login prompt) exits 130 with the new error code `INTERRUPTED` ("Interrupted.") instead of `INTERNAL_ERROR`.
- `login` prompts only for table output at a terminal: `--format csv` behaves like `--json` (no prompts). Email, password, and MFA prompts go to stderr only (the password without echo), and a missing stdin counts as non-interactive.
- `garmin-cli --json coach snapshot` returns the standard envelope (`data[0]` is the snapshot) instead of the bare snapshot; table output adds a note pointing to `--json` for the sections it omits, and `--format csv` is `INVALID_INPUT`.
- `activity get --laps --format csv` is `INVALID_INPUT` (use `activity laps`), and `activity get --detail --format csv` on a multisport activity prints only the detail table; CSV output is now always one table.
- `health sleep` no longer accepts `--ahead`.
- `--limit` must be 1-100 (`activity list`, `workout list`); values above 100 were sent to Garmin.
- CLI `workout schedule` reports `workout_schedule_id` instead of `workoutScheduleId`, matching the MCP tool and `workout calendar`.
- CLI `workout schedule` checks the date first, like MCP `workout_schedule`: a workout already scheduled there reports status `no_op` without writing, a date holding a different workout fails with `INVALID_INPUT` unless the new `--allow-multiple` flag is passed, and a missing schedule id in Garmin's response is recovered by re-reading the date (left empty when that read fails). If the pre-write calendar read is incomplete, nothing is scheduled.
- MCP `workout_schedule` refuses to write when its pre-write calendar read is incomplete (Garmin's schedule lookup failed), and reports `workout_schedule_id: null` instead of failing when the post-write id recovery read fails.
- `workout schedule` / `workout_schedule` refuse, even with `--allow-multiple` / `allow_multiple`, when the same workout is already on the date but Garmin returned no schedule id ("this workout is already scheduled on that date but Garmin returned no schedule id").
- `doctor --format` accepts `csv` like every other command; it used to fall back to a table.
- MCP row-returning tools publish a plain `{"type": "object"}` output schema instead of the shared count/rows/paging schema, and generated `title` fields are dropped from every tool schema; `tools/list` shrinks by about 30% (66k to 46k characters). Only `activity_get`, `activity_detail_metrics`, `login_status`, and `submit_mfa_code` keep typed output schemas. Clients that validated `structuredContent` against the old envelope schema must stop relying on it.
- MCP `workout_create`, `workout_update`, `training_plan_preview`, and `training_plan_apply` publish typed input schemas; a wrong type, unknown key, unknown sport/step/target type, or a string id now fails as a tool error naming the field path (for example `workout.steps.0.type`) before the tool runs, instead of an `INVALID_INPUT` result row (rule violations such as zone limits or one entry per date still return that row).
- MCP `activity_list` renames `start` to `offset` (matching `activity_laps`) and adds `truncated` (true when a full page came back) and `next_offset`; an old `start` argument (even `null`) fails with an error pointing to `offset`.
- `activity weather` (CLI and MCP) reports `temp_c`, `apparent_temp_c`, and `dew_point_c` in Celsius, replacing `temperature`, `apparent_temp`, and `dew_point`: Garmin sends these in Fahrenheit even for metric accounts (checked live), and they were passed through unconverted.
- MCP `report_snapshot.kind`, `training_plan_reconcile.detail`, and `activity_download.fmt` are enums; `fmt` is now case-sensitive (lowercase), and an unknown value fails schema validation instead of returning an `INVALID_INPUT` row.
- MCP auth errors (`AUTH_MISSING`, and `AUTH_FAILED` when Garmin rejected the credentials or session) carry a recovery hint covering MCP login (Claude Desktop extension settings, then `submit_mfa_code` for a challenge pending in this server) and terminal login (`garmin-cli login`); the `garmin://server/manifest` error inventory shows the same hints. An `AUTH_FAILED` caused by an unsafe or unusable Garmin home or token file points at `GARMIN_HOME` and `garmin-cli doctor` instead (tools and resources alike), a rejected MFA code says to wait, retry the original call for a new code, and submit it, and any hint with `retry_after_seconds` starts with the wait.
- The deprecated `GARTH_HOME` environment variable and `--garth-home` option are removed; use `GARMIN_HOME` / `--garmin-home`.
- A session saved only under the old `~/.garth/garmin_tokens.json` is no longer copied into `~/.garminconnect`, and old garth token files (`oauth1_token.json`, ...) are no longer reported specially: such a user gets `AUTH_MISSING` and runs `garmin-cli login`. `GARMIN_HOME=~/.garth` works only when that folder holds a `garmin_tokens.json`; old garth OAuth files need a fresh login. `doctor` adds an informational `legacy_garth` row naming a leftover `GARTH_HOME` or an unused `~/.garth/garmin_tokens.json`, and with `GARTH_HOME` set while the default home is in use, `AUTH_MISSING` messages (CLI, MCP tools and resources) add "GARTH_HOME is no longer read; set GARMIN_HOME."
- `login logout` deletes only the token file in the selected Garmin home (no longer also `~/.garth/garmin_tokens.json`), and its output row drops the `legacy_token_removed` field.
- `mcp-server --mount-path` is removed (it was already rejected); it is now an unknown option.
- Library callers of `build_garmin_payload` / `merge_workout_payload` can no longer use the `heart.rate`, `calories`, or `power` end conditions (the CLI and MCP tools never accepted them).
- Library imports: `garmin_cli.metrics` exports only `FieldEntry` and `FieldTable` (import `REGISTRY`, `MetricEntry`, `resolve`, and the `*_TYPE_KEYS` sets from `garmin_cli.metrics.registry`; `for_sport` and `validate_table_coverage` are gone, `project_row` / `resolve_field` live in `garmin_cli.metrics.field_table`); `FieldTable` takes only `entries` and derives `columns`; `garmin_cli.serializers` no longer re-exports `REGISTRY`, `CYCLING_TYPE_KEYS`, `LAP_SWIM_TYPE_KEYS`, `RUNNING_TYPE_KEYS`, `UNION_COLUMNS`, `SportProfile`, `profile_for` (use `garmin_cli.metrics.registry` / `garmin_cli.metrics.sport_profile`), `COLUMNS_ACTIVITY_LAPS_*` (use `garmin_cli.serializers.activities`), or the private `_`-helpers (use `garmin_cli.serializers._common`); `error_contracts.UNKNOWN_ERROR_CONTRACT` is private; `token_store.expand_garth_home` is renamed `expand_garmin_home` and the legacy migration helpers are removed.
- Library imports: `garmin_cli.endpoints.health.get_resting_hr(day)` and `get_training_readiness(day)` are removed; use `get_resting_hr_range(day, day)` and `get_training_readiness_range(day, day)`.
- `performance zones` (MCP `performance_zones`) returns the athlete's heart-rate and power zone tables, one row per zone with `kind`, `sport`, `zone`, `low`, `high`, `unit`, instead of `sport`, `lt_hr_bpm`, `lt_pace` (lactate-threshold values stay in `performance thresholds`).

### Added

- `garmin-cli plan preview|apply|reschedule|reconcile`: CLI versions of the MCP `training_plan_preview`, `training_plan_apply`, `training_plan_reschedule`, and `training_plan_reconcile` tools, running the same code; plans are read from a JSON or YAML file or stdin, writes ask for confirmation (or `--confirm`), `plan apply --dry-run` previews, and an incomplete result exits 1.
- Training readiness rows (`health readiness`, MCP `health_readiness`, the morning report, and `coach_snapshot` wellness rows) add `latest_score` and `latest_level`, the day's newest recalculation, so afternoon changes after a workout are visible next to the morning `score` / `level`.
- `workout schedule --allow-multiple` and MCP `workout_schedule(allow_multiple=true)` schedule a workout on a date that already holds a different one (Garmin allows several per day).
- `--json` and `--format` also work after the subcommand (`garmin-cli health sleep --days 7 --json`); the subcommand's value wins over a global one.
- `workout create --dry-run` and `workout update --dry-run` validate the input and print the Garmin payload without saving (`--json`: `data[0]` has `dry_run` and `wire_payload`; `--format csv` is rejected); create needs no login, and the update preview is the exact PUT body.
- `workout calendar --date DATE` shows a single day.
- `doctor` reports the garmin-py and garminconnect versions, fails the MCP check when the installed `mcp` is outside `>=2.2.0,<3` (with a reinstall hint), accepts `GARMIN_EMAIL` / `GARMIN_PASSWORD` as a valid sign-in setup when no token store or session exists yet, and gives check-specific recovery hints (install Python 3.12+, the permission mode to set, fixing `GARMIN_HOME` or the bearer token).
- `login`, `login status`, and `login logout` print a one-row CSV table under `--format csv`; they printed a sentence.
- `garmin-cli --help` has a description with examples, and the shared date, limit, type, search, and confirm options have help text; `workout create --help` shows `FILE` as optional.
- `garmin-cli login` reads the password from `GARMIN_PASSWORD` when `--password` is absent, accepts `--password-stdin` (piped stdin only; an empty line is `AUTH_MISSING`), and takes an MFA code from `--mfa-code` / `GARMIN_MFA_CODE` (only useful for codes valid for the new challenge, such as authenticator-app codes; emailed/SMS codes still need an interactive login, which prompts and ignores `GARMIN_MFA_CODE`). A rejected MFA code is reported as such, not as bad credentials. `--password` is deprecated (shell history and process-list exposure).
- `garmin-cli login logout` deletes the saved `garmin_tokens.json` (refusing symlinks); it reports `{"logged_out": true|false}` (plain text names the deleted file) and exits 0 when there was nothing to delete. Stop a running MCP server first: it keeps its loaded session and may save refreshed tokens again.
- `doctor` checks that `garmin_tokens.json` is a regular file (not a symlink, dangling or not) with mode 600, and names the offending symlink when the Garmin home path passes through one; an uninspectable token store is a check failure, not `INTERNAL_ERROR`.
- `mcp-server --read-only` (also `GARMIN_MCP_READ_ONLY=1` and a "Read-only mode" setting in the Claude Desktop extension) registers no write tools (workout, activity, file, and training-plan writes), and its server instructions and `plan_next_week` prompt stop at the preview; `doctor` and `server_doctor` report the mode, and `doctor` fails the check for a non-boolean `GARMIN_MCP_READ_ONLY` (still reporting any bearer-token problem), which `mcp-server` refuses at start-up.
- MCP health and performance range tools accept `days` (an integer 1-90) instead of `start_date`, and `end_date` defaults to today in the athlete's Garmin profile timezone; explicit ranges work as before.
- `coach_snapshot`/`report_snapshot`, `activity_get`/`activity_detail_metrics`, and `health_daily_summary` describe when to use each instead of the overlapping tool.
- Workout heart-rate and power targets accept a custom range instead of a zone number: `{"type":"heart.rate.zone","min":145,"max":155}` (bpm, at most 250) or `{"type":"power.zone","min":240,"max":260}` (watts, at most 2500), in `workout create` / `workout update`, the MCP workout tools, and inline plan workouts; `workout get` reads them back in the same shape, including custom power ranges made in Garmin Connect.
- `performance zones` / MCP `performance_zones` list the athlete's heart-rate zones per sport profile and cycling and running power zones, with each zone's low and high bound.
- `training_plan_reconcile(detail="targets")` resolves power zone-number targets to watts from the power zone table of the workout's sport (shown as `resolved_band`) instead of reporting `missing_power_zone_boundaries`, and compares custom bpm and watt ranges against lap or stream data; stream-based scores add `scope: "whole_activity"`, and provenance adds `power_zone_requests`.
- `workout get` keeps a custom heart-rate or power range with a unit (for example percent of FTP) as `unit` and leaves it out of `write_projection`, so it is never rewritten as watts or bpm; a step with a secondary target is also left out (`unsupported_secondary_target`) instead of being rewritten without it.
- `workout send WORKOUT_ID [--device DEVICE_ID] [--dry-run]` and MCP `workout_send_to_device` send a saved workout to a watch or bike computer (delivered on its next sync). The workout is read first (missing: `NOT_FOUND`, dry run included), and only devices that take workouts of its sport qualify (a run never goes to an Edge); without a device id the only qualifying device is used, and several are refused with a list of their ids and names. The CLI asks for confirmation naming the workout and device; the MCP tool is a destructive-hint, non-idempotent, audited write left out in read-only mode. A send is never retried after a 5xx or timeout, and that error says the workout may already be queued.
- `device list` and MCP `device_list` add a `workout_capable` column.

### Changed

- The first-run `AUTH_MISSING` message leads with "Run `garmin-cli login`" before mentioning `GARMIN_EMAIL` / `GARMIN_PASSWORD`.
- The `login` help text says it saves session tokens, not credentials.
- CLI `--days`, `--ahead`, and default date ranges (and `health status` / `activity list` relative dates) count from today in the Garmin profile timezone, like the MCP server, instead of the host date; explicit `--date` / `--from` / `--to` are unchanged.
- Paces are rounded to the nearest second instead of truncated (2.778 m/s reads 6:00, not 5:59); NaN, infinite, negative, and boolean values give no pace.
- `garmin://athlete/profile` returns the latest VO2max row per sport (ignoring days without a value), caches a snapshot only when every failed section was `NOT_FOUND` and the session did not change while it was fetched, and drops its cached snapshot after a login, MFA completion, or logout in any process (it watches the token file's metadata, never its contents).
- The MCP server's cached session check is dropped when `garmin_tokens.json` changes, so a `garmin-cli login` or `login logout` in another process takes effect on the next call instead of after the probe TTL.
- Strict calendar reads (training-plan rechecks) fail, and report `unknown`, when a calendar page or the schedule lookup returns no item list, instead of reading it as empty.
- `coach_snapshot` `provenance.completed_requests` counts the calendar pages actually read (one or two) instead of always charging the maximum.
- Resting heart rate (`health resting-hr`, MCP `health_resting_hr`, the weekly report, and `coach_snapshot`) is read with one range request instead of one request per day, plus one per-day request for the last date when the range has no value for it; rows are unchanged, including days without a value.
- `training_plan_preview` / `training_plan_apply` read the scheduled workout templates concurrently (`GARMIN_CLI_FETCH_CONCURRENCY`, spaced by `GARMIN_CLI_DAILY_CALL_DELAY`) instead of one at a time, and stop starting new reads after a failure.

### Security

- Table output shows control characters (other than tab and newline) in cell text as `\xNN`, so terminal escape sequences in Garmin or plan text are not run by the terminal; JSON and CSV values are unchanged.
- JSON error envelopes no longer echo option values in `command` (for example `login --password <secret>` reported the password); only known command names are reported, and a subcommand only when it directly follows its group.
- MCP `activity_download` rejects `..`, symlinked path components, and paths outside the file root, checks the root and target directory before signing in, creates files with `O_EXCL | O_NOFOLLOW` (0600) and removes a partial file if the write fails, overwrites atomically, and is now annotated `destructive_hint=True`.
- MCP `activity_upload` returns one generic `File not available under GARMIN_MCP_FILE_ROOT` error for missing, outside-root, symlinked, or non-file paths, so it no longer reveals which host paths exist.
- MCP `activity_upload` opens the file once without following a final symlink, requires a regular file, and uploads a private copy (deleted afterwards), so a symlink swapped in after the path check is not followed.
- Requests whose bearer token contains non-ASCII characters get 401 instead of crashing the request.
- `mcp-server --host` rejects empty, whitespace-only, and bracketed non-IPv6 values such as `[]`; they were treated as loopback (no token required) while the HTTP server bound every interface.
- `CliConfig` no longer includes the password in its `repr`.
- The MCP server no longer logs failed tool calls and resource reads with their error text (which can echo caller arguments such as type keys, dates, or file paths) to stderr: the MCP SDK logger is held at WARNING.
- Install hints now say `pip install "garmin-py[mcp]"`; they named `garmin-cli`, an unrelated PyPI package.
- `login status`, `doctor`, and the MCP `login_status` / session resources no longer chmod the Garmin home while checking status (they may still refresh tokens on disk). Every session resume and save refuses a symlinked `garmin_tokens.json`, dangling links included.
- A fresh login now saves the client it authenticated, then publishes it; a concurrent status check could previously swap in a stale session that was saved instead.
- The MCP write audit log works: each write tool call logs exactly one JSON object (tool, outcome, ids, and lengths only, never names, paths, codes, or an activity type key Garmin has not accepted) to stderr on the `garmin_cli.audit` logger; it used to log only a bare word. `training_plan_apply`, `training_plan_reschedule`, and `submit_mfa_code` are now audited; calls rejected by the input schema or id checks log `failed-validation` with only the tool name; plan results refused by conflicts or the live recheck before any write log `conflict`; an upload Garmin declined logs `rejected`; the lines propagate to host-configured root handlers instead of a private stderr handler when the host configured logging; an unexpected error is logged as `failed-upstream` before it propagates; `workout_unschedule` logs `schedule_id` (it was logged as `workout_id`).
- The Claude Desktop bundle installs the dependency versions pinned at release time (`server/constraints.txt`) when they have wheels for your platform and Python, otherwise retries once in a fresh environment without the pins; both attempts share one 15-minute limit; pip ignores `pip.conf` and `PIP_*` settings (custom index mirrors are not used); on macOS and Linux `~/.garmin-py/mcpb/` is private (0700), including directories left by older releases (Windows keeps the existing permissions).

### CI

- Every GitHub Action is pinned to a commit SHA, workflows default to read-only `contents` permission without persisted checkout credentials, and publishing stops when the release tag does not match the pyproject version.
- CI also tests on macOS, smoke-tests the CLI-only wheel (no `[mcp]` extra), builds the `.mcpb` bundle on every push and PR (a release attaches that same CI-built bundle), and type-checks `mcpb/` and `scripts/`.

### Fixed

- Training readiness (`health readiness`, MCP `health_readiness`, the morning report, and `coach_snapshot`) works again: the per-day `daily-readiness` endpoint it used returns 404, so it now reads Garmin's readiness range endpoint in one request and returns one row per day, the latest morning (`AFTER_WAKEUP_RESET`) score or, without one, the day's latest score.
- The installed `garmin-cli` command now prints JSON error envelopes for `--json` / `--format json` failures; it previously fell back to plain-text errors because the console entry point never passed its arguments to the error handler.
- `doctor` fails the write-surface check for a `GARMIN_MCP_BEARER_TOKEN` that is present but blank, too short, or outside the RFC 6750 token alphabet, and its write-surface text describes the loopback enforcement.
- `garmin-cli --json mcp-server` without the `mcp` extra now prints a JSON error envelope instead of plain text, and startup refusals (such as an invalid bearer token) report `INVALID_INPUT` instead of `INTERNAL_ERROR`.
- `mcp-server --host [::1]` binds `::1`; the bracketed form previously reached the HTTP server unchanged.
- HTTP binds on an IPv6 literal host (for example `--host ::1` with a token set) build a valid auth URL instead of failing at startup.
- Concurrent MCP calls that queued behind an in-progress login for the same Garmin home no longer start a second login once the first succeeds; they re-resume and probe the saved session first and log in only if that fails.
- A failing Garmin read now makes 1 + `GARMIN_CLI_RETRY_DELAYS` attempts (4 by default); python-garminconnect's own retries stacked under ours made up to 16 attempts (~34 s) per call.
- Status codes are read from the HTTP response (anywhere in the exception chain) or explicit wording such as `API Error 503` / `HTTP 503`; `port=443` or an id like `/workout/502` in an error message no longer counts as a status.
- Upstream `GarminConnectTooManyRequestsError` (including SSO 427) on data calls is treated as a rate limit and reports `RATE_LIMITED`.
- `workout list` / `workout get` (and their MCP tools) report `AUTH_FAILED` on 401/403 instead of `INTERNAL_ERROR`.
- `health steps` / `health_steps` and `health intensity-minutes` / `health_intensity_minutes` accept the full 90-day range: requests are split into windows of 28 days (steps) and 31 days (intensity minutes), Garmin's per-request limits, instead of failing with a 400.
- `coach_snapshot` records a timed-out or unreachable section as a section error (`NETWORK_ERROR`, category `network`) and still returns the other sections.
- A Cloudflare bot challenge during login reports `RATE_LIMITED` instead of blaming the credentials, "All login strategies exhausted" without a credential rejection reports `NETWORK_ERROR` (or `SERVER_ERROR` for a 5xx), and an upstream authentication error that wraps a 5xx or timeout is classified by that cause. On data and write calls only the HTTP status counts.
- A token refresh that fails because Garmin throttles, returns 5xx, or is unreachable is reported with that code instead of as a rejected session, so it no longer triggers a credential login.
- `submit_mfa_code` keeps the pending challenge after a `SERVER_ERROR` or `NETWORK_ERROR` too, not only after `RATE_LIMITED`.
- `training_plan_apply` reports outcome `unknown`, not `compensated`, when a workout create or schedule fails with `SERVER_ERROR`, `NETWORK_ERROR`, or `INTERNAL_ERROR`, since that write may have landed; a new template whose schedule may exist is kept instead of deleted. `training_plan_reschedule` reports `unknown` with an unknown schedule operation in the same case.
- Deleting or unscheduling a workout and deleting an activity succeed when a retry after a 5xx or read timeout gets 404 (the first attempt already removed it); after a connection or DNS failure a 404 is still `NOT_FOUND`.
- The `NETWORK_ERROR` and `SERVER_ERROR` recovery hints warn that a failed write may still have been applied and to verify remote state before repeating it.
- `training_plan_preview` / `training_plan_apply` accept swaps, chained shifts, and a removal plus replacement on the same date: an occupant the plan itself vacates (another entry's verified source or a verified removal) is no longer a `destination_occupied` conflict. Apply removes such an occupant just before writing that destination and restores it if the plan rolls back.
- Updating a workout's `steps` without `sport` keeps its stored sport, so workouts with Garmin sub-sports such as `trail_running` or `road_biking` can be updated (a known stored sport without a valid id gets it from the known sport table); a workout with no usable stored sport asks for `sport`.
- `training_plan_apply` rollback removes this call's new schedules before restoring removed sources and verifies each restore by its own new schedule id, so a leftover new schedule of the same workout can no longer pass for a restore; `restore_source` operations now report the old `schedule_id` and the new `restored_schedule_id`.
- `training_plan_apply` rechecks the calendar when deleting a source fails with a server, network, or internal error, or with a rate limit or auth error after an earlier attempt that Garmin may have processed: a delete that landed is restored on rollback (or, as the plan's last step, counts as done), and an unreadable or incomplete recheck (Garmin's schedule lookup failed) is reported as an `unknown` operation for that schedule.
- `training_plan_apply` and `training_plan_reschedule` verify a new schedule by its returned id, workout, and date together; when Garmin returns no id, only a single new row of that workout on that date (absent before the write and not already claimed) is accepted, otherwise the result is `unknown`. A stale or untouched schedule of the same workout no longer passes as the new one.
- `training_plan_apply` reports a `source_schedule_changed` conflict and deletes nothing when a schedule it would vacate has moved onto the destination date since the plan was read.
- The `training_plan_apply` and `training_plan_reschedule` rechecks no longer treat a schedule as gone when Garmin's supplemental schedule lookup failed and only the calendar pages were read.
- `training_plan_apply` rollback records a failure of any kind in one cleanup step as an `unknown` operation with its `error_code` and continues with the remaining cleanup, instead of escaping with an internal error.
- `training_plan_reschedule` reports `destination_occupied` when the new date holds a different workout even if the same workout is also there.
- Stress rows use Garmin's `calendarDate`; they were dated with the raw epoch-millisecond sample timestamp (for example `"1795446000000"`), which dropped every stress day from `coach_snapshot` baselines.
- `workout calendar` and every calendar-based tool fetch each Garmin calendar week the range touches (walking by the week each page returns), so a range such as Wednesday to the next Tuesday no longer drops the last week's items; items repeated across pages are listed once, only workout schedule items count as already-scheduled when merging Garmin Coach sessions, and a page with `calendarItems: null` or inconsistent bounds no longer breaks the walk.
- Planned-versus-actual reconciliation scores heart-rate zone intervals with Garmin's live time-in-zone data, which has only zone floors (a zone runs up to, not including, the next zone's floor; zone 5 is open-ended; a missing next zone is `insufficient_data`), instead of marking every interval `insufficient_data`.
- `training_plan_preview` / `training_plan_apply` treat an inline workout as already applied when Garmin holds it with `open` read back as `no.target` or a null target, or whole numbers read back as floats (180 vs 180.0), instead of reporting `destination_occupied`; a date only counts as already holding the workout when its schedule id is known, and apply never removes a source without a verified destination schedule.
- `training_plan_reschedule` onto a date that already holds the same workout rechecks the calendar when removing the source fails in a way that may have landed: a source that is gone is `complete`, an unreadable recheck is `unknown`.
- Running cadence targets are scored against full steps per minute (`directDoubleCadence`, or `directRunCadence` doubled when its median is below 120, i.e. per foot); the per-foot stream made every running cadence sample read about half.
- `workout get` maps Garmin's `cadence` target key back to `cadence.zone`, so cadence workouts get a `write_projection`.
- CSV output no longer prefixes negative numbers with a tab; only text cells that start with a formula character are escaped.
- Once a command's options are parsed, errors (including date-range usage errors) follow the parsed output format, so an option value that happens to be `--json` (for example a search term) no longer switches errors to JSON; JSON error envelopes then name the full command (for example `login status`). Before parsing, a subcommand's `--format` overrides a global `--json`, and a repeated `--format` follows click's last-wins rule.
- `training_plan_reconcile` no longer counts a calendar activity, weight, or nap item that carries a `workoutId` as a planned workout.
- `workout schedule` / `workout_schedule` ignore logged activities on the date: an activity done from the same workout no longer turns the call into a `no_op`, and one from another workout no longer blocks it; `no_op` now requires a known schedule id.
- `training_plan_reschedule` reports an unexpected (non-Garmin) failure while removing the source or cleaning up the new schedule as a failed or `unknown` operation with `INTERNAL_ERROR`, instead of escaping as an internal tool error; cleanup operations name the new `schedule_id` and, when cleanup fails, its `error_code`.
- `training_plan_reschedule` keeps the source when the read that verifies the new schedule fails: it removes the new schedule (`compensated`) or, when Garmin returned no id, reports `unknown` with the destination date, with the read's error in `errors`. A compact `expected_date` such as `20260705` no longer reports `source_schedule_changed`.
- `training_plan_apply` re-reads each source's expected date just before deleting it at the end of a plan: a source that moved meanwhile is a `source_schedule_changed` conflict, and a failed read deletes nothing; both roll back the plan's new schedules instead of deleting the source on its new date.
- `training_plan_preview` / `training_plan_apply` treat a scheduled workout without a schedule id as occupying the date for an entry that names no source (it used to pass as the entry's own source), read workout templates only for scheduled rows (not logged activities), and skip a template Garmin no longer has instead of failing the plan.
- Strict calendar reads (plan rechecks, `workout_schedule`) read a no-content (HTTP 204) calendar page or schedule lookup as an empty period instead of failing.
- A failure to save the session tokens after a successful `garmin-cli login` reports "Authenticated, but saving the session ... failed" (`AUTH_FAILED`) instead of "Garmin login failed".
- The Claude Desktop bundle no longer fails on macOS when `python3` is Apple's Python 3.9: it switches to the oldest Homebrew (`/opt/homebrew/bin`, `/usr/local/bin`) or python.org Python whose real version meets the minimum (pyenv, asdf, and uv Pythons are not searched). The manifest now declares Python >=3.8 so Claude Desktop lets the bundle start on such a Mac; the launcher still enforces 3.12.
- The MCP `health_daily_summary` description and SKILL.md name the fields the tool returns (`active_kilocalories`, `floors_ascended`, `floors_descended`, `resting_heart_rate`, ...) instead of `calories`, `floors`, and `resting_hr`; SKILL.md now documents `coach snapshot`, `activity rename`, `activity set-type`, and `workout unschedule`, and points to the README for MCP setup instead of repeating it.

## [2.13.0] - 2026-11-09

### Added

- `performance ftp-history` / `performance_ftp_history`: daily functional threshold power (FTP) for cycling or running.
- `performance acclimation` / `performance_acclimation`: daily heat acclimation percentage, acclimated altitude, and Garmin's trend labels.
- `performance cycling-ability` / `performance_cycling_ability`: daily aerobic endurance, aerobic capacity, and anaerobic capacity scores with the rider profile type.
- `performance power-curve` / `performance_power_curve`: best average power per duration across activities (cycling or rowing; Garmin rejects running).
- `performance fastest-splits` / `performance_fastest_splits`: fastest times per standard distance (running or cycling), 1-10 efforts per distance.
- `workout calendar` and every calendar-backed surface (`coach_snapshot`, `report_snapshot`, `training_plan_*`) now also list Garmin Coach (adaptive plan) sessions, which Garmin's calendar pages can omit. They come from `workoutScheduleByPeriod`, deduplicated by schedule id, so `workout_schedule_id` still unschedules them.

### Changed

- Bump `garminconnect` 0.3.5 -> 0.3.20. Picks up upstream security hardening (symlink-safe atomic token writes, input validation on identifier-bearing URLs, JWT `alg: none` rejection, no response bodies in debug logs), the restored mobile login (no more 429 fallback to slower login strategies), and HTTP 427 login blocks reported as rate limits. Upstream 404s now raise `GarminConnectNotFoundError`, a subclass of the connection error garmin-py already classifies by status code.
- `health daily-summary` / `health_daily_summary` fetch the whole range in one request (v2 `dailysummaries`) instead of one request per day. Floors are now whole numbers (Garmin's v2 payload rounds them; the old endpoint returned fractions such as `238.42`).
- Default "today" dates in `coach_snapshot`, `report_snapshot`, `training_plan_reconcile`, the athlete-profile resource, `coach snapshot`, and the latest VO2 max / power-to-weight lookups follow the athlete's Garmin profile timezone once a session is active, so a server running in UTC no longer asks for yesterday every evening. CLI date options still resolve against the host date because they are parsed before login.
- `coach_snapshot` costs 31 Garmin requests by default (was 30) because the calendar adds the adaptive-plan lookup; the hard cap rose to 31 so the default window is unchanged.
- Workout updates use the typed upstream `update_workout` helper instead of a raw PUT. The request is the same.

### Fixed

- Calendar workout rows (`workout calendar`, `workout_calendar`, and the calendar inside `coach_snapshot`/`report_snapshot`/`training_plan_*`) now report the sport in `type`. Live calendar items carry it as `sportTypeKey`, not the `workoutTypeKey` the serializer read, so `type` was always null; `training_plan_reconcile`'s date-and-sport fallback can now match a completed activity whose type equals the planned sport (for example `running`).
- Concurrent 401s refresh the Garmin session once again. garminconnect 0.3.10+ serializes refreshes under its own lock, which made garmin-py's coalescing guard see an already-advanced generation and refresh once per thread; the guard now snapshots the generation when each request's auth headers are built, so a 401 is answered by exactly one refresh per token.

### Removed

- The raw write transport (`backend.connectapi` POST/PUT/DELETE, `_make_write_request`) and the raw-fallback registry (`backend.RAW_FALLBACKS`, `get_raw_fallback_registry`), which had no callers once workout updates became typed. `backend.connectapi` is now GET-only.

### CI

- Dependabot version updates enabled for pip and GitHub Actions (weekly, minor/patch grouped).

## [2.12.0] - 2026-10-26

### Changed

- **BREAKING:** garmin-py now requires Python 3.12 or newer (was 3.10). Every `garminconnect` release that fixes CVE-2026-54447 requires Python 3.12. CI now tests 3.12 and 3.13; `garmin-cli doctor` and the Claude Desktop bundle enforce the new minimum.
- `--stdin` workout input is now decoded as UTF-8 (matching file input) instead of the console locale, and invalid UTF-8 reports `INVALID_INPUT`. Replaces `click.get_text_stream`, which Click 8.5 deprecates.
- `workout create`/`update` now reject a FILE argument combined with `--stdin` (`INVALID_INPUT`) instead of silently reading stdin and ignoring the file.
- `workout create`/`update` read and validate their input before authenticating, so input errors report `INVALID_INPUT` without a login or network round-trip.

### Fixed

- Workout input that cannot be read (a directory, missing permission, invalid UTF-8, or a closed stdin) now reports `INVALID_INPUT` instead of `INTERNAL_ERROR`.
- Workout input with a UTF-8 byte-order mark (PowerShell pipes, Notepad-saved files) is now accepted instead of failing JSON parsing.
- Bearer-token `mcp-server` HTTP transports set `AuthSettings.validate_token_resource=False` explicitly, silencing the mcp SDK deprecation warning. The static token carries no audience claim, so behavior is unchanged.

### CI

- The PyPI publish workflow now runs the full CI workflow (tests, lint, type-check, dependency audit) against the release and only publishes if it passes.

### Security

- Bump `garminconnect` to 0.3.5 for CVE-2026-54447 (GHSA-wjhr-76vg-2hvc): earlier versions wrote the OAuth token store world-readable. garmin-py already tightened the token file to 0600 after login; 0.3.5 now creates it 0600 itself.
- Require `mcp>=2.2.0` for CVE-2026-59951 (GHSA-84m7-p3x7-pcfv): stateful Streamable HTTP servers leaked session state without bound. Affects `mcp-server --transport streamable-http` without `--stateless-http`.
- Require `pytest>=9.0.3` (dev) for CVE-2025-71176 (predictable `/tmp/pytest-of-{user}` directory).
- CI now runs `pip-audit` against the runtime dependencies (including the `mcp` extra) in a separate job.

## [2.11.2] - 2026-08-18

### Fixed

- MCP tool calls no longer fail against clients that validate structured output (e.g. "None is not of type 'boolean'" on `truncated`): the MCP SDK serializes omitted optional envelope keys as `null`, so the typed output schemas now declare `total`, `truncated`, `next_offset`, `children`, and `unavailable` as nullable. Clients should treat a `null` paging key the same as an absent one.
- MCP server startup on Python 3.10: typed output schemas now express optional envelope keys via `total=False` TypedDict bases instead of `NotRequired`, which the MCP SDK's stdlib `get_type_hints` call leaked into pydantic on 3.10 and crashed tool registration with `PydanticForbiddenQualifier`. Generated JSON schemas are unchanged.

## [2.11.1] - 2026-08-06

### Fixed

- `activity_detail_metrics` now defaults to `max_samples=0` (auto): the sample cap is sized to the number of requested channels (a ~2400-value budget, clamped to 100–1000 samples) so multi-channel pulls fit MCP client response limits in one call. Explicit `max_samples` values of 100–5000 behave as before. The tool docstring and server instructions now tell clients to fetch all channels in a single call — rows are timestamp-aligned at any stride — instead of splitting channels across calls and stitching. The server manifest reports `activity_detail_metrics_auto_cell_budget` in place of `activity_detail_metrics_default_samples`.

## [2.11.0] - 2026-08-04

### Added

- MCP v2 server instructions now describe authentication, response and error contracts, limits, write approval guidance, and discovery resources at connection time.
- MCP entity resource templates for `garmin://activity/{id}` and `garmin://health/sleep/{date}`.

### Changed

- MCP tool output schemas now expose machine-readable envelope and locally-owned result contracts, including paging metadata, instead of generic open-object schemas.
- `activity_download` now advertises explicit non-destructive local-file annotations, and all registered tools are guarded against missing annotations.
- MCP list and discovery methods now carry one-hour private cache hints; resource reads remain uncached at the protocol level.

## [2.10.0] - 2026-07-30

### Added

- Sanitized backend-boundary fixture recording (`--e2e --record-fixtures`) and an offline CLI/MCP replay contract tier with a focused synthetic corpus. Fixture keys are deterministic and identifier-safe; identity, location, image, token, password, and secret fields are redacted before writing.
- MCP resources `garmin://server/manifest` and `garmin://athlete/profile`, plus the `weekly_training_review`, `recovery_check`, `compare_recent_activities`, and `plan_next_week` prompts. The athlete profile snapshot is cached in-process with the auth-probe TTL: a cache hit performs no network calls, and a rebuild reuses a fresh auth probe instead of issuing its own.
- `garmin-cli doctor` and the read-only MCP `server_doctor` tool for non-raising configuration, token-store, session, MCP-extra, and write-surface diagnostics.
- Running/cycling target analysis for `training_plan_reconcile(detail="targets")`, including HR-zone, lap, bounded sample-stream, interval-mapping, coverage, and data-quality results. Missing sensors and unsupported sports report `insufficient_data`. Sample-stream fallback scores are always time-weighted (`time_in_band_pct`), even for distance-prescribed steps, because samples carry equal weights.
- A maintainer-run calendar identifier probe gated behind both `--e2e` and `--e2e-writes`.

### Changed

- MCP `activity_laps` responses are capped at 100 rows with offset paging metadata.
- MCP `activity_detail_metrics` now returns a deterministic whole-stream stride sample (1000 samples by default; configurable from 100 to 5000) with sample and stride metadata. Previously it returned the complete stream.
- Structured MCP errors now include `retry_after_seconds`; rate-limit errors use the first configured retry delay and other errors return `null`.
- The `mcp` extra now requires the stable v2 SDK: `mcp[cli]>=2.0.0,<3` (the v2.0.0 stable release is out; the pre-release floor `2.0.0b1` is no longer needed). No code changes were required — the server-side surface this package uses (`MCPServer`, `ToolAnnotations`, `ToolError`, auth settings) is unchanged since the beta.
- MCP `login_status` no longer raises on an unusable Garmin home (for example a symlinked directory); every failure mode now reports `authenticated: false`. `garmin-cli doctor` surfaces the underlying cause.
- Read-only status surfaces (`garmin-cli doctor`, MCP `login_status`, and the MCP resources) no longer repair token-store directory permissions or migrate legacy tokens while probing the session — they only report. Login and authenticated tool calls still perform those repairs.
- Lap-based target scores in `training_plan_reconcile(detail="targets")` report `quality: "lap_summary_aggregate"` when the activity's lap structure does not match the planned steps, since values are then whole-activity aggregates rather than per-step measurements.

### Fixed

- Fixture recording now redacts sensitive key fragments anywhere in a key name instead of exact names: live payloads prefix identity fields (`ownerFullName`, `ownerDisplayName`, `ownerProfileImageUrl*`), carry bare `userId`/`ownerId`, and weather rows carry bare `latitude`/`longitude`, all of which previously leaked into recorded fixtures (found by a live recording run; the leaked local recordings were deleted).
- Calendar rows now populate `workout_schedule_id` from the item's `id` field for scheduled workouts. The live calendar payload has no `workoutScheduleId` key (that key only appears in schedule-write responses; verified by the live calendar probe on 2026-07-27), so since v2.9.0 the field was always `null`, which silently broke unschedule matching in `training_plan_apply`/`training_plan_reschedule`. Race and event rows keep `workout_schedule_id: null` because their `id` is not a schedule id.

## [2.9.0] - 2026-07-16

### Added

- AI-coaching read surfaces: `coach_snapshot` (MCP and `garmin-cli coach snapshot`) returns bounded recovery baselines, activity-derived weekly load, current Garmin training status, upcoming calendar items (today plus six days), wellness rows (training readiness, SpO2, steps, weight), execution summaries, data quality, and request provenance. Its default request budget is 30, which is also the hard cap; a terminal rate limit stops further requests and preserves completed sections.
- `training_plan_reconcile` MCP tool for bounded planned-versus-actual matching. It fetches detail for each examined activity, prefers the structured `workout_id` association, labels date/sport fallback matches as inferred, and leaves ambiguous sessions explicit. Summary mode is implemented; target mode currently reports explicit insufficient-data state pending interval/metric-stream analysis.
- Stateless `training_plan_preview`, `training_plan_apply`, and `training_plan_reschedule` MCP tools with a closed plan schema, live-state rechecks, semantic duplicate protection, destination-first/destructive-last ordering, compensation of newly created resources, and truthful partial/unknown outcomes. Preview is read-only; apply and reschedule are destructive and rely on MCP client approval.

### Changed

- Calendar workout rows now add `workout_id` and `workout_schedule_id` while retaining compatibility `id`. Workout detail rows preserve recursive segment/repeat structure and expose a simplified `write_projection` only for supported constructs; unsupported constructs remain visible with incompatibility reasons.
- Workout and plan validation rejects non-finite or non-positive durations, invalid target zones/ranges, unsupported nested repeats, excessive aggregate size, duplicate source schedules, and unknown AI-facing fields before writes.
- MCP tool annotations now consistently identify read-only and destructive operations. Garmin failures retain machine-readable `error_code`, `category`, `message`, and `recovery_hint` data at the MCP boundary.

### Fixed

- `coach_snapshot` capped its steps window to 28 dates: Garmin's daily-steps endpoint rejects wider spans with a 400 (observed live), which failed every default snapshot. Steps feed the wellness section only, so baselines are unaffected.

## [2.8.0] - 2026-07-14

### Added
- Claude Desktop one-click bundle: `scripts/build_mcpb.py` packages a `.mcpb` extension (manifest with keychain-stored `GARMIN_EMAIL`/`GARMIN_PASSWORD` user config plus a stdlib-only bootstrap that installs the matching PyPI release into a private venv under `~/.garmin-py/mcpb/` on first launch). The install is wheels-only (`--only-binary=:all:`, so no sdist build hooks execute) with the Garmin credentials stripped from pip's environment, serialized by a cross-process lock on POSIX, and self-repairs if the cached venv's interpreter disappears. The publish workflow builds the bundle and attaches it to every GitHub release after the PyPI upload succeeds.
- `submit_mfa_code` MCP tool and `MFA_REQUIRED` error code: when the env-credential auto-login hits a Garmin multi-factor challenge, the tool call fails with `MFA_REQUIRED` and the login can be completed in-conversation with the one-time code (resumable MFA via `garminconnect` `return_on_mfa`/`resume_login`; the pending login is held in process memory and is single-use).

### Changed
- `ensure_authenticated`'s credential fallback now uses `return_on_mfa=True`: on MFA-protected accounts it raises `MFA_REQUIRED` (previously the challenge surfaced as an opaque `AUTH_FAILED`), and while a challenge is outstanding further calls re-raise `MFA_REQUIRED` without starting a new login, so concurrent tool calls don't spam the user with fresh codes. Interactive `garmin-cli login` still prompts for the code as before.

## [2.7.0] - 2026-07-08

### Added
- GitHub Actions publish workflow (`.github/workflows/publish.yml`): builds sdist/wheel and uploads to PyPI via trusted publishing whenever a GitHub release is published.

### Changed
- Distribution renamed from `garmin-cli` to `garmin-py` for PyPI publication (`garmin-cli` was already taken on PyPI). The import package `garmin_cli` and the `garmin-cli` console command are unchanged. The GitHub repository moved to `ching-kuo/garmin-py`.
- The `mcp` extra now depends on `mcp[cli]>=2.0.0b1,<3` from PyPI instead of a pinned git commit, unblocking PyPI publication (PyPI rejects direct URL dependencies). Ported to the v2 SDK layout: `ToolAnnotations` moved from `mcp.types` to the `mcp_types` package.

## [2.6.0] - 2026-07-07

### Added
- `performance personal-records` (CLI) and `performance_personal_records` (MCP): all-time PRs from Garmin's personalrecord service with a human-readable `label` per typeId (`fastest_1km_s` ... `fastest_marathon_s`, `longest_run_m`, `longest_ride_m`, `total_ascent_m`, `max_avg_power_20min_w`, `most_steps_day/week/month`, `longest_goal_streak_days`); unmapped typeIds (11, swim records 16-22) surface with `label: null` and the raw value.
- `health status` / `health_training_status` now return Garmin's full training-load picture: `acute_load`, `chronic_load`, `acwr` + `acwr_status`, the chronic-load tunnel (`load_tunnel_min`/`max`), monthly load-focus buckets (`monthly_load_aerobic_low`/`aerobic_high`/`anaerobic`) with their target ranges, and `load_balance_status`. On multi-device accounts the primary training device's status and its same-device load-balance entry are merged (never cross-device).
- Per-activity training response is now exposed for every sport: `aerobic_training_effect`/`anaerobic_training_effect` render for swims and unknown sports too (previously run/bike only), plus new universal fields `training_effect_label` (primary-benefit label such as `TEMPO`), `training_load` (EPOC-based load, also added to `activity list` rows), and `workout_id` (the structured workout an activity executed — links plan to execution).
- `workout calendar` / `workout_calendar` rows now include `item_type`, `is_race`, `primary_event`, `event_time`, and `location`, so scheduled races/events on the Garmin calendar are distinguishable from planned workouts.

### Fixed
- The single-activity detail payload stores aerobic training effect under `summaryDTO.trainingEffect` (not `aerobicTrainingEffect`, which is the search-list spelling); the metric registry now reads both, so `activity get --detail` no longer shows a null aerobic TE.

### Changed
- **Breaking:** `health status` was rebuilt against `/metrics-service/metrics/trainingstatus/aggregated/{date}` because the old `trainingstatus/daily` path now 404s (the command returned empty rows). The `training_status` column's value space changed from the `trainingStatusType` enum to Garmin's `trainingStatusFeedbackPhrase` (e.g. `PRODUCTIVE_2`), and the `load_type` column was removed.

## [2.5.1] - 2026-07-07

### Added
- Sleep rows (`health sleep` CLI and `health_sleep` MCP) now include `bedtime` and `wake_time`: the actual sleep start/end as local wall-clock ISO timestamps, sourced from `sleepStartTimestampLocal`/`sleepEndTimestampLocal`. Closes #2.

## [2.5.0] - 2026-07-05

### Added
- `activity detail-metrics ACTIVITY_ID [--metric KEY]...` (CLI) and `activity_detail_metrics` (MCP): the raw per-sample metric time series from Garmin's `metricDescriptors`/`activityDetailMetrics` detail stream, pivoted to one row per sample keyed by metric key (`directTimestamp`, `directHeartRate`, `directPower`, ...). Optional metric-key filtering keeps output small (~2000 samples per typical activity); unknown keys are rejected with `INVALID_INPUT` listing what the activity actually recorded. Enables intra-activity analyses (e.g. aerobic decoupling) that summary and lap data cannot support.
- `health body-battery` / `health_body_battery` rows now include `max_level` (the intraday peak), alongside `start_level`/`end_level`.

### Fixed
- `health body-battery` was broken by upstream API drift: Garmin removed the per-day `/wellness-service/wellness/bodyBattery/{date}` endpoint (now 404). The command now uses `/wellness-service/wellness/bodyBattery/reports/daily` — the same path garminconnect 0.3.2 uses — and fetches the whole date range in a single call instead of one call per day. The serializer handles the new `[epoch_ms, level]` sample shape and per-item `date` field (legacy ISO-timestamp payloads still parse).

## [2.4.0] - 2026-07-02

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
