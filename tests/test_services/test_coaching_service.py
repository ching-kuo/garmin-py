"""Tests for deterministic AI-coach snapshot aggregation."""

from __future__ import annotations

from datetime import date, timedelta

from garmin_cli.services.coaching import (
    aggregate_activity_load,
    build_coach_snapshot,
    coach_snapshot_request_budget,
)


def _daily_rows(field: str, as_of: date, values: list[int]) -> list[dict[str, object]]:
    return [{"date": (as_of - timedelta(days=index)).isoformat(), field: value} for index, value in enumerate(values, start=1)]


class TestCoachSnapshotRequestBudget:
    def test_default_budget_is_within_cap(self) -> None:
        # 9-day daily window: two missing-day slack over the 7-sample minimum.
        assert coach_snapshot_request_budget(28, 9, False) == 30

    def test_extended_daily_baselines_charge_the_full_window(self) -> None:
        assert coach_snapshot_request_budget(28, 7, True) == 68


class TestCoachSnapshotAggregation:
    def test_baselines_exclude_as_of_and_activity_load_is_by_week(self) -> None:
        as_of = date(2026, 7, 15)
        sections = {
            "hrv": _daily_rows("last_night", as_of, [40, 42, 44, 46, 48, 50, 52]),
            "sleep": _daily_rows("duration_hours", as_of, [7, 7, 7, 7, 7, 7, 7]),
            "resting_hr": _daily_rows("resting_hr", as_of, [50, 50, 50, 50, 50, 50, 50]),
            "stress": _daily_rows("avg_stress", as_of, [30, 30, 30, 30, 30, 30, 30]),
            "body_battery": _daily_rows("max_level", as_of, [80, 80, 80, 80, 80, 80, 80]),
            "current_hrv": [{"date": as_of.isoformat(), "last_night": 60}],
            "current_sleep": [{"date": as_of.isoformat(), "duration_hours": 8}],
            "current_resting_hr": [{"date": as_of.isoformat(), "resting_hr": 49}],
            "current_stress": [{"date": as_of.isoformat(), "avg_stress": 31}],
            "current_body_battery": [{"date": as_of.isoformat(), "max_level": 75}],
            "activities": [
                {
                    "id": 1,
                    "date": "2026-07-14T08:00:00",
                    "type": "running",
                    "duration_min": 30,
                    "distance_km": 5,
                    "training_load": 80,
                },
                {
                    "id": 2,
                    "date": "2026-07-12T08:00:00",
                    "type": "cycling",
                    "duration_min": 60,
                    "distance_km": 20,
                    "training_load": None,
                },
            ],
            "training_status": [{"acute_load": 400, "chronic_load": 350}],
            "calendar": [{"date": "2026-07-15", "workout_id": 7, "is_race": False}],
        }

        result = build_coach_snapshot(
            as_of=as_of,
            baseline_days=7,
            daily_baseline_days=7,
            sections=sections,
            unavailable=[],
            errors=[],
            complete=True,
            aborted=False,
            estimated_requests=26,
            completed_requests=26,
            sports=None,
        )

        hrv = next(signal for signal in result["recovery"]["signals"] if signal["signal"] == "hrv")
        assert hrv["baseline_median"] == 46
        assert hrv["current_value"] == 60
        assert hrv["sample_count"] == 7
        running_week = next(row for row in result["load"]["weekly_activity_load"] if row["sport"] == "running")
        cycling_week = next(row for row in result["load"]["weekly_activity_load"] if row["sport"] == "cycling")
        assert running_week["training_load"] == 80
        assert cycling_week["null_training_load_count"] == 1
        assert result["plan"]["today"] == [{"date": "2026-07-15", "workout_id": 7, "is_race": False}]

    def test_daily_signals_report_their_shorter_window(self) -> None:
        as_of = date(2026, 7, 15)
        result = build_coach_snapshot(
            as_of=as_of,
            baseline_days=28,
            daily_baseline_days=9,
            sections={},
            unavailable=[],
            errors=[],
            complete=True,
            aborted=False,
            estimated_requests=30,
            completed_requests=30,
            sports=None,
        )
        by_name = {signal["signal"]: signal for signal in result["recovery"]["signals"]}
        assert by_name["hrv"]["baseline_from"] == "2026-06-17"
        assert by_name["resting_heart_rate"]["baseline_from"] == "2026-07-06"
        assert by_name["stress"]["baseline_from"] == "2026-07-06"
        assert by_name["stress"]["baseline_to"] == "2026-07-14"

    def test_insufficient_samples_stays_explicit(self) -> None:
        as_of = date(2026, 7, 15)
        result = build_coach_snapshot(
            as_of=as_of,
            baseline_days=7,
            daily_baseline_days=7,
            sections={
                "hrv": _daily_rows("last_night", as_of, [40, 41]),
                "current_hrv": [{"date": as_of.isoformat(), "last_night": 50}],
            },
            unavailable=[],
            errors=[],
            complete=True,
            aborted=False,
            estimated_requests=1,
            completed_requests=1,
            sports=None,
        )
        hrv = next(signal for signal in result["recovery"]["signals"] if signal["signal"] == "hrv")
        assert hrv["state"] == "insufficient_samples"

    def test_prior_value_is_marked_stale_instead_of_current(self) -> None:
        as_of = date(2026, 7, 15)
        result = build_coach_snapshot(
            as_of=as_of,
            baseline_days=7,
            daily_baseline_days=7,
            sections={"hrv": _daily_rows("last_night", as_of, [40] * 7)},
            unavailable=[],
            errors=[],
            complete=True,
            aborted=False,
            estimated_requests=1,
            completed_requests=1,
            sports=None,
        )
        hrv = next(signal for signal in result["recovery"]["signals"] if signal["signal"] == "hrv")
        assert hrv["state"] == "stale_current"
        assert hrv["current_value_date"] == "2026-07-14"
        assert {"section": "recovery.hrv", "reason": "stale_current"} in result["data_quality"]

    def test_activity_cap_is_declared_as_truncated(self) -> None:
        as_of = date(2026, 7, 15)
        result = build_coach_snapshot(
            as_of=as_of,
            baseline_days=7,
            daily_baseline_days=7,
            sections={
                "activities": [{"id": activity_id, "date": as_of.isoformat(), "type": "running"} for activity_id in range(100)]
            },
            unavailable=[],
            errors=[],
            complete=True,
            aborted=False,
            estimated_requests=26,
            completed_requests=26,
            sports=None,
        )
        assert result["provenance"]["truncated"] is True


def test_activity_load_filters_sports() -> None:
    rows = [
        {"date": "2026-07-14", "type": "running", "training_load": 50},
        {"date": "2026-07-14", "type": "cycling", "training_load": 75},
    ]
    weekly, by_sport, summary = aggregate_activity_load(rows, date(2026, 7, 15), ["running"])
    assert weekly[0]["training_load"] == 50
    assert by_sport == [
        {
            "sport": "running",
            "activity_count": 1,
            "duration_min": 0,
            "distance_km": 0,
            "training_load": 50,
            "null_training_load_count": 0,
        }
    ]
    assert summary["activity_count"] == 1
