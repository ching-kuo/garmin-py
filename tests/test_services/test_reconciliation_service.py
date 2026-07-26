"""Tests for stateless planned-versus-actual matching."""

from __future__ import annotations

from datetime import date

from garmin_cli.services.reconciliation import reconcile_plan
from garmin_cli.services.reconciliation_targets import compare_activity_targets


def _reconcile(calendar: list[dict], activities: list[dict], today: date | None = None) -> dict:
    return reconcile_plan(
        calendar,
        activities,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 14),
        detail="summary",
        activities_examined=len(activities),
        detail_requests=len(activities),
        max_activities=50,
        truncated=False,
        today=today or date(2026, 7, 15),
    )


def test_exact_workout_association_wins_over_date_sport() -> None:
    result = _reconcile(
        [{"date": "2026-07-10", "workout_id": 10, "type": "running"}],
        [
            {"id": 1, "date": "2026-07-10T08:00:00", "type": "running", "workout_id": 10},
            {"id": 2, "date": "2026-07-10T09:00:00", "type": "running", "workout_id": None},
        ],
    )
    row = result["entries"][0]
    assert row["state"] == "completed_exact"
    assert row["match_method"] == "workout_id"
    assert row["actual"]["activity_id"] == 1


def test_same_day_multiple_candidates_remain_ambiguous() -> None:
    result = _reconcile(
        [{"date": "2026-07-10", "workout_id": 10, "type": "running"}],
        [
            {"id": 1, "date": "2026-07-10T08:00:00", "type": "running", "workout_id": None},
            {"id": 2, "date": "2026-07-10T09:00:00", "type": "running", "workout_id": None},
        ],
    )
    row = result["entries"][0]
    assert row["state"] == "ambiguous"
    assert row["match_confidence"] == "ambiguous"


def test_single_date_sport_candidate_is_inferred_and_unmatched_is_unplanned() -> None:
    result = _reconcile(
        [{"date": "2026-07-10", "workout_id": 10, "type": "running"}],
        [
            {"id": 1, "date": "2026-07-10T08:00:00", "type": "running", "workout_id": None},
            {"id": 2, "date": "2026-07-11T08:00:00", "type": "cycling", "workout_id": None},
        ],
    )
    assert result["entries"][0]["state"] == "completed_inferred"
    assert result["entries"][1]["state"] == "unplanned_activity"
    assert result["provenance"]["detail_requests"] == 2


def test_reused_workout_id_is_disambiguated_by_date_without_reusing_activity() -> None:
    result = _reconcile(
        [
            {"date": "2026-07-09", "workout_id": 10, "type": "running"},
            {"date": "2026-07-10", "workout_id": 10, "type": "running"},
        ],
        [
            {"id": 1, "date": "2026-07-09T08:00:00", "type": "running", "workout_id": 10},
            {"id": 2, "date": "2026-07-10T08:00:00", "type": "running", "workout_id": 10},
        ],
    )
    assert [entry["actual"]["activity_id"] for entry in result["entries"]] == [1, 2]


def test_fallback_never_steals_an_activity_with_a_different_workout_id() -> None:
    result = _reconcile(
        [
            {"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 1, "type": "running"},
        ],
        [{"id": 5, "date": "2026-07-10T08:00:00", "type": "running", "workout_id": 99}],
    )
    planned = [row for row in result["entries"] if row["planned"] is not None]
    assert planned[0]["state"] == "skipped"


def test_cross_date_exact_is_not_assigned_when_template_recurs() -> None:
    result = _reconcile(
        [
            {"date": "2026-07-08", "workout_id": 10, "workout_schedule_id": 1, "type": "running"},
            {"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 2, "type": "running"},
        ],
        [{"id": 5, "date": "2026-07-09T08:00:00", "type": "running", "workout_id": 10}],
    )
    planned = [row for row in result["entries"] if row["planned"] is not None]
    assert all(row["state"] != "completed_exact" for row in planned)
    assert any(
        {"reason": "cross_date_exact_ambiguous"} in row["data_quality"] for row in planned
    )


def test_todays_unmatched_workout_stays_planned() -> None:
    result = _reconcile(
        [{"date": "2026-07-10", "workout_id": 10, "workout_schedule_id": 1, "type": "running"}],
        [],
        today=date(2026, 7, 10),
    )
    assert result["entries"][0]["state"] == "planned_future"


def test_activities_without_ids_surface_with_a_data_quality_note() -> None:
    result = _reconcile(
        [],
        [{"id": None, "date": "2026-07-10T08:00:00", "type": "running"}],
    )
    assert result["entries"][0]["state"] == "unplanned_activity"
    assert result["entries"][0]["data_quality"] == [{"reason": "missing_activity_id"}]


def _target_workout(steps: list[dict], sport: str = "running") -> dict:
    return {
        "sport": sport,
        "write_projection": {
            "name": "Target workout",
            "sport": sport,
            "steps": steps,
        },
    }


def _step(
    step_type: str,
    target: dict,
    *,
    duration_type: str = "time",
) -> dict:
    return {
        "type": step_type,
        "duration": {"type": duration_type, "value": 60},
        "target": target,
    }


def test_targets_maps_interval_laps_and_reports_high_time_in_band() -> None:
    workout = _target_workout([{
        "type": "repeat",
        "count": 2,
        "steps": [
            _step("interval", {"type": "speed.zone", "min": 2.5, "max": 3.5}),
            _step("recovery", {"type": "speed.zone", "min": 1.0, "max": 2.0}),
        ],
    }])
    laps = [
        {"lap_index": 1, "duration_min": 1.0, "distance_km": 0.18},
        {"lap_index": 2, "duration_min": 1.0, "distance_km": 0.09},
        {"lap_index": 3, "duration_min": 1.0, "distance_km": 0.18},
        {"lap_index": 4, "duration_min": 1.0, "distance_km": 0.09},
    ]

    result = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=laps,
        hr_zones=[],
        samples=[],
    )

    assert result["state"] == "completed"
    assert [target["time_in_band_pct"] for target in result["targets"]] == [100.0, 100.0]
    assert all(target["quality"] == "lap_summary" for target in result["targets"])
    assert result["interval_mapping"]["state"] == "mapped"
    assert len(result["interval_mapping"]["intervals"]) == 4
    assert all(
        interval["state"] == "completed" and interval["in_band"] is True
        for interval in result["interval_mapping"]["intervals"]
    )


def test_targets_keep_hr_result_when_prescribed_pace_data_is_missing() -> None:
    workout = _target_workout([
        _step("interval", {"type": "heart.rate.zone", "zone": 3}),
        _step("interval", {"type": "speed.zone", "min": 2.5, "max": 3.5}),
    ])

    result = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=[],
        hr_zones=[
            {"zone": 2, "seconds_in_zone": 60},
            {"zone": 3, "seconds_in_zone": 240},
        ],
        samples=[],
    )

    by_type = {target["target_type"]: target for target in result["targets"]}
    assert by_type["hr"]["state"] == "completed"
    assert by_type["hr"]["time_in_band_pct"] == 80.0
    assert by_type["pace"]["state"] == "insufficient_data"
    assert by_type["pace"]["reason"] == "missing_pace_sensor_data"
    assert result["state"] == "insufficient_data"


def test_targets_fall_back_to_whole_activity_samples_when_laps_are_absent() -> None:
    workout = _target_workout([
        _step("interval", {"type": "speed.zone", "min": 2.5, "max": 3.5}),
    ])

    result = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=[],
        hr_zones=[],
        samples=[
            {"directSpeed": 3.0},
            {"directSpeed": 4.0},
            {"directSpeed": None},
        ],
    )

    target = result["targets"][0]
    assert target["state"] == "completed"
    assert target["time_in_band_pct"] == 50.0
    assert target["coverage_pct"] == 66.7
    assert target["quality"] == "sampled_stream"


def test_distance_step_sample_fallback_is_labelled_time_weighted() -> None:
    """Equal-weight samples cannot claim distance weighting for distance steps."""
    workout = _target_workout([
        _step(
            "interval",
            {"type": "speed.zone", "min": 2.5, "max": 3.5},
            duration_type="distance",
        ),
    ])

    result = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=[],
        hr_zones=[],
        samples=[{"directSpeed": 3.0}, {"directSpeed": 4.0}],
    )

    target = result["targets"][0]
    assert target["quality"] == "sampled_stream"
    assert target["time_in_band_pct"] == 50.0
    assert "distance_in_band_pct" not in target


def test_targets_leave_lap_structure_mismatch_at_summary_level() -> None:
    workout = _target_workout([
        _step("interval", {"type": "cadence.zone", "min": 160, "max": 180}),
        _step("recovery", {"type": "cadence.zone", "min": 130, "max": 150}),
    ])

    result = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=[{"lap_index": 1, "duration_min": 1, "avg_cadence_spm": 170}],
        hr_zones=[],
        samples=[],
    )

    assert result["interval_mapping"] == {
        "state": "ambiguous",
        "reason": "lap_structure_mismatch",
        "planned_steps": 2,
        "actual_laps": 1,
    }
    assert {"reason": "lap_structure_mismatch"} in result["data_quality"]
    # Per-step laps cannot be attributed to either target, so both are scored
    # against the whole activity and must be labeled as aggregates.
    assert all(
        target["quality"] == "lap_summary_aggregate" for target in result["targets"]
    )


def test_targets_report_stream_budget_exhaustion_and_unsupported_sports() -> None:
    workout = _target_workout([
        _step("interval", {"type": "speed.zone", "min": 2.5, "max": 3.5}),
    ])
    exhausted = compare_activity_targets(
        sport="running",
        workout=workout,
        laps=[],
        hr_zones=[],
        samples=[],
        stream_unavailable_reason="stream_request_limit_reached",
    )
    unsupported = compare_activity_targets(
        sport="pool_swimming",
        workout=workout,
        laps=[],
        hr_zones=[],
        samples=[],
    )

    assert exhausted["targets"][0]["reason"] == "stream_request_limit_reached"
    assert unsupported["state"] == "insufficient_data"
    assert unsupported["reason"] == "unsupported_sport"
