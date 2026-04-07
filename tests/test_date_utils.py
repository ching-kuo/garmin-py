"""Tests for garmin_cli.date_utils — resolve_date_range()."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import click
import pytest

from garmin_cli.date_utils import resolve_date_range


TODAY = date.today()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(**kwargs: Any) -> tuple[date, date]:
    """Call resolve_date_range with sensible defaults for unspecified args."""
    defaults: dict[str, Any] = {
        "date": None,
        "from_date": None,
        "to_date": None,
        "days": None,
        "ahead": None,
        "default_days": 1,
    }
    defaults.update(kwargs)
    return resolve_date_range(
        defaults["date"],
        defaults["from_date"],
        defaults["to_date"],
        defaults["days"],
        defaults["ahead"],
        defaults["default_days"],
    )


# ---------------------------------------------------------------------------
# No arguments — defaults
# ---------------------------------------------------------------------------

class TestResolveDefault:

    def test_no_args_returns_today_to_today(self) -> None:
        start, end = _resolve()
        assert start == TODAY
        assert end == TODAY

    def test_no_args_default_days_7_returns_past_7_days(self) -> None:
        start, end = _resolve(default_days=7)
        assert start == TODAY - timedelta(days=6)
        assert end == TODAY


# ---------------------------------------------------------------------------
# --date flag
# ---------------------------------------------------------------------------

class TestResolveDate:

    def test_date_returns_single_day_range(self) -> None:
        d = date(2026, 3, 11)
        start, end = _resolve(date=d)
        assert start == d
        assert end == d



# ---------------------------------------------------------------------------
# --days flag
# ---------------------------------------------------------------------------

class TestResolveDays:

    def test_days_1_returns_today_only(self) -> None:
        start, end = _resolve(days=1)
        assert start == TODAY
        assert end == TODAY

    def test_days_7_returns_past_7_days_inclusive(self) -> None:
        start, end = _resolve(days=7)
        assert start == TODAY - timedelta(days=6)
        assert end == TODAY

    def test_days_30_returns_past_30_days(self) -> None:
        start, end = _resolve(days=30)
        assert start == TODAY - timedelta(days=29)
        assert end == TODAY

    def test_days_90_boundary(self) -> None:
        start, end = _resolve(days=90)
        assert start == TODAY - timedelta(days=89)
        assert end == TODAY

    def test_days_range_length_is_correct(self) -> None:
        start, end = _resolve(days=14)
        assert (end - start).days == 13  # 14 days inclusive

    def test_days_0_raises_usage_error(self) -> None:
        with pytest.raises((click.UsageError, click.exceptions.BadParameter, ValueError)):
            _resolve(days=0)

    def test_days_negative_raises_usage_error(self) -> None:
        with pytest.raises((click.UsageError, click.exceptions.BadParameter, ValueError)):
            _resolve(days=-1)


# ---------------------------------------------------------------------------
# --ahead flag
# ---------------------------------------------------------------------------

class TestResolveAhead:

    def test_ahead_1_returns_today_only(self) -> None:
        start, end = _resolve(ahead=1)
        assert start == TODAY
        assert end == TODAY

    def test_ahead_7_returns_next_7_days_inclusive(self) -> None:
        start, end = _resolve(ahead=7)
        assert start == TODAY
        assert end == TODAY + timedelta(days=6)

    def test_ahead_30_returns_next_30_days(self) -> None:
        start, end = _resolve(ahead=30)
        assert start == TODAY
        assert end == TODAY + timedelta(days=29)

    def test_ahead_range_length_correct(self) -> None:
        start, end = _resolve(ahead=14)
        assert (end - start).days == 13

    def test_ahead_0_raises_usage_error(self) -> None:
        with pytest.raises((click.UsageError, click.exceptions.BadParameter, ValueError)):
            _resolve(ahead=0)

    def test_ahead_negative_raises_usage_error(self) -> None:
        with pytest.raises((click.UsageError, click.exceptions.BadParameter, ValueError)):
            _resolve(ahead=-5)


# ---------------------------------------------------------------------------
# --from / --to explicit range
# ---------------------------------------------------------------------------

class TestResolveFromTo:

    def test_from_and_to_returns_explicit_range(self) -> None:
        from_d = date(2026, 3, 1)
        to_d = date(2026, 3, 10)
        start, end = _resolve(from_date=from_d, to_date=to_d)
        assert start == from_d
        assert end == to_d

    def test_from_equals_to_is_valid(self) -> None:
        d = date(2026, 3, 11)
        start, end = _resolve(from_date=d, to_date=d)
        assert start == d
        assert end == d

    def test_from_without_to_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(from_date=date(2026, 3, 1), to_date=None)

    def test_to_without_from_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(from_date=None, to_date=date(2026, 3, 10))

    def test_from_after_to_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(from_date=date(2026, 3, 15), to_date=date(2026, 3, 1))

    def test_range_exceeding_90_days_raises_usage_error(self) -> None:
        from_d = date(2026, 1, 1)
        to_d = date(2026, 4, 10)  # > 90 days
        with pytest.raises(click.UsageError, match="90 days"):
            _resolve(from_date=from_d, to_date=to_d)

    def test_range_exactly_90_days_is_valid(self) -> None:
        from_d = date(2026, 1, 1)
        to_d = from_d + timedelta(days=89)  # 90 days inclusive
        start, end = _resolve(from_date=from_d, to_date=to_d)
        assert start == from_d
        assert end == to_d


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestResolveDateConflicts:

    def test_date_and_from_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(date=date(2026, 3, 11), from_date=date(2026, 3, 1))

    def test_date_and_to_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(date=date(2026, 3, 11), to_date=date(2026, 3, 11))

    def test_date_and_days_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(date=date(2026, 3, 11), days=7)

    def test_date_and_ahead_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(date=date(2026, 3, 11), ahead=7)

    def test_days_and_ahead_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(days=7, ahead=7)

    def test_days_and_from_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(days=7, from_date=date(2026, 3, 1))

    def test_days_and_to_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(days=7, to_date=date(2026, 3, 10))

    def test_ahead_and_from_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(ahead=7, from_date=date(2026, 3, 1))

    def test_ahead_and_to_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError):
            _resolve(ahead=7, to_date=date(2026, 3, 10))

    def test_days_exceeding_90_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError, match="90 days"):
            _resolve(days=91)

    def test_ahead_exceeding_90_raises_usage_error(self) -> None:
        with pytest.raises(click.UsageError, match="90 days"):
            _resolve(ahead=91)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

