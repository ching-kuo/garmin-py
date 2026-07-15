"""Tests for stateless planned-versus-actual matching."""

from __future__ import annotations

from datetime import date

from garmin_cli.services.reconciliation import reconcile_plan


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
