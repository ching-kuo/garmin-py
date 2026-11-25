"""Tests for garmin_cli.endpoints.health — all health endpoint functions."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from garmin_cli.endpoints.health import (
    get_body_battery_range,
    get_hrv,
    get_intensity_minutes_range,
    get_resting_hr_range,
    get_sleep,
    get_spo2_range,
    get_steps_range,
    get_stress_range,
    get_training_readiness_range,
    get_training_status,
)
from garmin_cli.exceptions import GarminCliError
from garmin_cli.serializers import serialize_resting_hr, serialize_training_readiness
from tests.helpers import make_http_error as _http_error


# ---------------------------------------------------------------------------
# get_training_status — endpoint path
# ---------------------------------------------------------------------------

class TestGetTrainingStatus:

    def test_uses_aggregated_metrics_service_endpoint(self, mocker: Any) -> None:
        # The old /training-info-service/.../training-status/{date} path 404s
        # live (2026-07-07); the aggregated path is the working replacement.
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        get_training_status(date(2026, 7, 7))
        call_str = str(mock_garth.connectapi.call_args)
        assert "/metrics-service/metrics/trainingstatus/aggregated/2026-07-07" in call_str


# ---------------------------------------------------------------------------
# get_hrv — endpoint routing logic
# ---------------------------------------------------------------------------

class TestGetHrv:

    def test_multi_day_range_uses_daily_range_endpoint(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = {}
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        get_hrv(date(2026, 3, 1), date(2026, 3, 7))
        call_str = str(mock_garth.connectapi.call_args)
        assert "/hrv-service/hrv/daily/2026-03-01/2026-03-07" in call_str


# ---------------------------------------------------------------------------
# Rate limiting / error handling (strengthened assertions)
# ---------------------------------------------------------------------------

class TestHealthEndpointErrorHandling:

    def test_http_404_raises_garmin_cli_error_with_not_found_code(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_http_429_raises_rate_limited_error_after_retries(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        # 4 calls: 1 initial + 3 retries — all return 429
        mock_garth.connectapi.side_effect = [_http_error(429)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")  # avoid real delays in tests

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "RATE_LIMITED"

    def test_http_500_raises_server_error_after_retries(
        self, mocker: Any
    ) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(500)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")

        with pytest.raises(GarminCliError) as exc_info:
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "SERVER_ERROR"

    def test_http_429_retries_before_failing(self, mocker: Any) -> None:
        """Implementation must retry 3 times before giving up on 429."""
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [_http_error(429)] * 4
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mock_sleep = mocker.patch("time.sleep")

        with pytest.raises(GarminCliError):
            get_sleep(date(2026, 3, 11), date(2026, 3, 11))

        # Should have called sleep for exponential backoff
        assert mock_sleep.call_count >= 1

    def test_http_429_succeeds_on_retry(self, mocker: Any) -> None:
        """Implementation retries and succeeds on 2nd attempt."""
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = [
            _http_error(429),
            {"dailySleepDTO": {}},  # succeeds on retry
        ]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        mocker.patch("time.sleep")

        result = get_sleep(date(2026, 3, 11), date(2026, 3, 11))
        assert result is not None

    def test_hrv_404_raises_not_found(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.connectapi.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        with pytest.raises(GarminCliError) as exc_info:
            get_hrv(date(2026, 3, 11), date(2026, 3, 11))
        assert exc_info.value.error_code == "NOT_FOUND"


class TestDailyHealthRangeHelpers:

    def test_body_battery_range_single_ranged_call(self, mocker: Any) -> None:
        # reports/daily accepts a start/end range natively: one call, one item
        # per day (the old per-day bodyBattery/{date} endpoint was removed).
        mock_garth = mocker.MagicMock()
        mock_garth.connectapi.return_value = [
            {"date": "2026-03-11", "bodyBatteryValuesArray": [[1000, 85]]},
            {"date": "2026-03-12", "bodyBatteryValuesArray": [[2000, 75]]},
        ]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        result = get_body_battery_range(date(2026, 3, 11), date(2026, 3, 12))

        assert result == [
            {"date": "2026-03-11", "bodyBatteryValuesArray": [[1000, 85]]},
            {"date": "2026-03-12", "bodyBatteryValuesArray": [[2000, 75]]},
        ]
        mock_garth.connectapi.assert_called_once_with(
            "/wellness-service/wellness/bodyBattery/reports/daily",
            params={"startDate": "2026-03-11", "endDate": "2026-03-12"},
        )

    def test_body_battery_range_wraps_dict_and_none(self, mocker: Any) -> None:
        mock_garth = mocker.MagicMock()
        mock_garth.connectapi.return_value = {"date": "2026-03-11"}
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        assert get_body_battery_range(date(2026, 3, 11), date(2026, 3, 11)) == [{"date": "2026-03-11"}]

        mock_garth.connectapi.return_value = None
        assert get_body_battery_range(date(2026, 3, 11), date(2026, 3, 11)) == []

    def test_stress_and_spo2_ranges_reuse_daily_iteration(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health.get_stress",
            return_value={"avgStressLevel": 35},
        )
        mocker.patch(
            "garmin_cli.endpoints.health.get_spo2",
            return_value={"averageSpO2": 97},
        )
        mocker.patch("garmin_cli.endpoints._base.time.sleep")

        assert len(get_stress_range(date(2026, 3, 11), date(2026, 3, 12))) == 2
        assert len(get_spo2_range(date(2026, 3, 11), date(2026, 3, 12))) == 2


# ---------------------------------------------------------------------------
# resting HR and training readiness — one range request instead of per day
# ---------------------------------------------------------------------------

class TestRestingHrRange:
    def test_ninety_days_is_one_range_request(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_rhr_daily.return_value = [{"calendarDate": "2026-03-31", "value": 50.0}]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        rows = get_resting_hr_range(date(2026, 1, 1), date(2026, 3, 31))

        mock_garth.get_rhr_daily.assert_called_once_with("2026-01-01", "2026-03-31")
        mock_garth.get_heart_rates.assert_not_called()
        assert len(rows) == 90

    def test_missing_end_value_is_filled_from_the_per_day_endpoint(self, mocker: Any) -> None:
        # The series may not carry today's value yet; dailyHeartRate does.
        mock_garth = MagicMock()
        mock_garth.get_rhr_daily.return_value = [{"calendarDate": "2026-03-11", "value": 52.0}]
        mock_garth.get_heart_rates.return_value = {"calendarDate": "2026-03-12", "restingHeartRate": 47}
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        rows = get_resting_hr_range(date(2026, 3, 11), date(2026, 3, 12))

        mock_garth.get_heart_rates.assert_called_once_with("2026-03-12")
        assert [row["restingHeartRate"] for row in rows] == [52, 47]

    def test_end_fill_not_found_leaves_the_value_empty(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_rhr_daily.return_value = []
        mock_garth.get_heart_rates.side_effect = _http_error(404)
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        rows = get_resting_hr_range(date(2026, 3, 11), date(2026, 3, 11))

        assert rows == [{"calendarDate": "2026-03-11", "restingHeartRate": None}]

    def test_rows_match_the_per_day_dailyheartrate_rows(self, mocker: Any) -> None:
        # Upstream flattens to {calendarDate, value: float} and drops days
        # without a value; per-day dailyHeartRate returned one int row per day.
        mock_garth = MagicMock()
        mock_garth.get_rhr_daily.return_value = [
            {"calendarDate": "2026-03-11", "value": 52.0},
            {"calendarDate": "2026-03-13", "value": 49.0},
        ]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
        per_day = [
            {"calendarDate": "2026-03-11", "restingHeartRate": 52},
            {"calendarDate": "2026-03-12", "restingHeartRate": None},
            {"calendarDate": "2026-03-13", "restingHeartRate": 49},
        ]

        rows = serialize_resting_hr(get_resting_hr_range(date(2026, 3, 11), date(2026, 3, 13)))

        assert rows == serialize_resting_hr(per_day)
        assert [type(row["resting_hr"]) for row in rows] == [int, type(None), int]

    def test_inverted_range_makes_no_request(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        assert get_resting_hr_range(date(2026, 3, 12), date(2026, 3, 11)) == []
        mock_garth.get_rhr_daily.assert_not_called()

    def test_range_ending_at_date_max_does_not_overflow(self, mocker: Any) -> None:
        mock_garth = MagicMock()
        mock_garth.get_rhr_daily.return_value = []
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        rows = get_resting_hr_range(date.max - timedelta(days=1), date.max)

        assert [row["calendarDate"] for row in rows] == ["9999-12-30", "9999-12-31"]


def _readiness(day: str, clock: str, context: str, score: int) -> dict[str, Any]:
    return {
        "calendarDate": day,
        "timestampLocal": f"{day}T{clock}:00.0",
        "inputContext": context,
        "score": score,
        "level": "MODERATE",
    }


class TestTrainingReadinessRange:
    def test_one_request_keeps_the_wakeup_entry_else_the_latest(self, mocker: Any) -> None:
        # Live shape: several entries per day, newest first.
        mock_garth = MagicMock()
        mock_garth.connectapi.return_value = [
            _readiness("2026-03-12", "12:00", "UPDATE_REALTIME_VARIABLES", 64),
            _readiness("2026-03-12", "08:00", "AFTER_POST_EXERCISE_RESET", 50),
            _readiness("2026-03-11", "18:00", "UPDATE_REALTIME_VARIABLES", 60),
            _readiness("2026-03-11", "09:00", "AFTER_POST_EXERCISE_RESET", 55),
            _readiness("2026-03-11", "06:00", "AFTER_WAKEUP_RESET", 70),
        ]
        mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 12))

        mock_garth.connectapi.assert_called_once_with(
            "/metrics-service/metrics/trainingreadiness/2026-03-11/2026-03-12", params=None
        )
        # score/level: the morning entry, else the latest; latest_*: the newest.
        assert serialize_training_readiness(rows) == [
            {"date": "2026-03-11", "score": 70, "level": "MODERATE", "latest_score": 60, "latest_level": "MODERATE"},
            {"date": "2026-03-12", "score": 64, "level": "MODERATE", "latest_score": 64, "latest_level": "MODERATE"},
        ]

    def test_date_falls_back_to_local_timestamp(self, mocker: Any) -> None:
        entry = _readiness("2026-03-11", "06:00", "AFTER_WAKEUP_RESET", 70)
        del entry["calendarDate"]
        mocker.patch("garmin_cli.endpoints.health._request", return_value=[entry])

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 11))

        assert [row["calendarDate"] for row in rows] == ["2026-03-11"]

    def test_empty_payload_yields_no_rows(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.endpoints.health._request", return_value=None)
        assert get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 11)) == []

    def test_ties_and_missing_timestamps_keep_garmins_newest_first_order(self, mocker: Any) -> None:
        same = {"timestamp": "2026-03-11T10:00:00.0", "timestampLocal": "2026-03-11T12:00:00.0"}
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[
                {"calendarDate": "2026-03-11", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 64, **same},
                {"calendarDate": "2026-03-11", "inputContext": "AFTER_POST_EXERCISE_RESET", "score": 50, **same},
                {"calendarDate": "2026-03-12", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 71},
                {"calendarDate": "2026-03-12", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 66},
            ],
        )

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 12))

        assert [row["score"] for row in rows] == [64, 71]

    def test_dst_fall_back_ranks_by_utc_timestamp(self, mocker: Any) -> None:
        # 01:15 EST (06:15Z) is later than 01:45 EDT (05:45Z) despite its
        # earlier local clock.
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[
                {"calendarDate": "2026-11-01", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 61,
                 "timestamp": "2026-11-01T06:15:00.0", "timestampLocal": "2026-11-01T01:15:00.0"},
                {"calendarDate": "2026-11-01", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 59,
                 "timestamp": "2026-11-01T05:45:00.0", "timestampLocal": "2026-11-01T01:45:00.0"},
            ],
        )

        rows = get_training_readiness_range(date(2026, 11, 1), date(2026, 11, 1))

        assert [row["score"] for row in rows] == [61]

    def test_mixed_timestamps_keep_garmins_order_instead_of_comparing_utc_to_local(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[
                {"calendarDate": "2026-03-11", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 80,
                 "timestampLocal": "2026-03-11T09:00:00.0"},
                {"calendarDate": "2026-03-11", "inputContext": "UPDATE_REALTIME_VARIABLES", "score": 40,
                 "timestamp": "2026-03-11T20:00:00.0", "timestampLocal": "2026-03-11T08:00:00.0"},
            ],
        )

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 11))

        assert [(row["score"], row["latest_score"]) for row in rows] == [(80, 80)]

    def test_entries_with_non_string_dates_are_skipped(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[
                {"calendarDate": 20260311, "inputContext": "AFTER_WAKEUP_RESET", "score": 99},
                {"timestampLocal": 1773216000000, "inputContext": "AFTER_WAKEUP_RESET", "score": 98},
                _readiness("2026-03-11", "06:00", "AFTER_WAKEUP_RESET", 70),
            ],
        )

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 11))

        assert [row["score"] for row in rows] == [70]

    def test_inverted_range_makes_no_request(self, mocker: Any) -> None:
        request = mocker.patch("garmin_cli.endpoints.health._request")
        assert get_training_readiness_range(date(2026, 3, 12), date(2026, 3, 11)) == []
        request.assert_not_called()

    def test_entries_outside_the_requested_window_are_dropped(self, mocker: Any) -> None:
        mocker.patch(
            "garmin_cli.endpoints.health._request",
            return_value=[
                _readiness("2026-03-12", "06:00", "AFTER_WAKEUP_RESET", 70),
                _readiness("2026-03-11", "06:00", "AFTER_WAKEUP_RESET", 66),
                _readiness("2026-03-10", "06:00", "AFTER_WAKEUP_RESET", 60),
            ],
        )

        rows = get_training_readiness_range(date(2026, 3, 11), date(2026, 3, 11))

        assert [row["calendarDate"] for row in rows] == ["2026-03-11"]


# ---------------------------------------------------------------------------
# usersummary stats ranges — chunked to Garmin's live span limits
# ---------------------------------------------------------------------------

def _stats_spans(mock_garth: MagicMock) -> list[tuple[str, str]]:
    return [tuple(c.args[0].rsplit("/", 2)[1:]) for c in mock_garth.connectapi.call_args_list]


@pytest.mark.parametrize(
    ("getter", "days", "spans"),
    [
        (get_steps_range, 28, [("2026-01-01", "2026-01-28")]),
        (get_steps_range, 29, [("2026-01-01", "2026-01-28"), ("2026-01-29", "2026-01-29")]),
        (get_steps_range, 56, [("2026-01-01", "2026-01-28"), ("2026-01-29", "2026-02-25")]),
        (
            get_steps_range,
            90,
            [
                ("2026-01-01", "2026-01-28"),
                ("2026-01-29", "2026-02-25"),
                ("2026-02-26", "2026-03-25"),
                ("2026-03-26", "2026-03-31"),
            ],
        ),
        (get_intensity_minutes_range, 31, [("2026-01-01", "2026-01-31")]),
        (get_intensity_minutes_range, 32, [("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-01")]),
    ],
)
def test_stats_range_is_chunked_within_garmin_span_limit(
    mocker: Any, getter: Any, days: int, spans: list[tuple[str, str]]
) -> None:
    mock_garth = MagicMock()
    mock_garth.connectapi.side_effect = lambda url, params=None: [{"calendarDate": url[-21:-11]}]
    mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)
    start = date(2026, 1, 1)

    rows = getter(start, start + timedelta(days=days - 1))

    assert _stats_spans(mock_garth) == spans
    assert [row["calendarDate"] for row in rows] == [first for first, _ in spans]


def test_stats_range_chunking_does_not_overflow_at_date_max(mocker: Any) -> None:
    mock_garth = MagicMock()
    mock_garth.connectapi.return_value = []
    mocker.patch("garmin_cli.endpoints.health.garth", mock_garth)

    get_steps_range(date(9999, 12, 1), date.max)

    assert _stats_spans(mock_garth) == [("9999-12-01", "9999-12-28"), ("9999-12-29", "9999-12-31")]
