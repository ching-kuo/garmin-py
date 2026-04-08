"""Date range parsing and validation."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import click

_MAX_DAYS = 90

CLICK_DATE_TYPE = click.DateTime(formats=["%Y-%m-%d"])


def resolve_click_dates(
    value_date: datetime | None,
    days: int | None,
    ahead: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[date, date]:
    """Convert Click DateTime values to a (start, end) date range.

    Thin wrapper around :func:`resolve_date_range` that handles the
    ``datetime`` → ``date`` conversion Click forces on us.
    """
    return resolve_date_range(
        date_=value_date.date() if value_date else None,
        from_date=date_from.date() if date_from else None,
        to_date=date_to.date() if date_to else None,
        days=days,
        ahead=ahead,
    )


def resolve_date_range(
    date_: Optional[date],
    from_date: Optional[date],
    to_date: Optional[date],
    days: Optional[int],
    ahead: Optional[int],
    default_days: int = 1,
) -> tuple[date, date]:
    """Resolve CLI date arguments into a (start, end) tuple (both inclusive).

    Args:
        date_: Single-day selection (--date).
        from_date: Range start (--from).
        to_date: Range end (--to).
        days: Past N days (--days). End is always today.
        ahead: Future N days (--ahead). Start is always today.
        default_days: Days back to use when no option is specified.

    Returns:
        (start_date, end_date) inclusive tuple.

    Raises:
        click.UsageError: On conflicting or invalid arguments.
    """
    today = date.today()

    # ── Conflict detection ────────────────────────────────────────────────
    if date_ is not None and (from_date is not None or to_date is not None):
        raise click.UsageError("Cannot use --date with --from/--to")
    if date_ is not None and days is not None:
        raise click.UsageError("Cannot use --date with --days")
    if date_ is not None and ahead is not None:
        raise click.UsageError("Cannot use --date with --ahead")
    if days is not None and ahead is not None:
        raise click.UsageError("Cannot use --days with --ahead")
    if days is not None and (from_date is not None or to_date is not None):
        raise click.UsageError("Cannot use --days with --from/--to")
    if ahead is not None and (from_date is not None or to_date is not None):
        raise click.UsageError("Cannot use --ahead with --from/--to")
    if (from_date is None) != (to_date is None):
        raise click.UsageError("--from and --to must be used together")

    # ── Resolve range ─────────────────────────────────────────────────────
    if date_ is not None:
        return (date_, date_)

    if days is not None:
        if days <= 0:
            raise click.UsageError("--days must be a positive integer")
        if days > _MAX_DAYS:
            raise click.UsageError(
                f"Date range cannot exceed {_MAX_DAYS} days (got --days {days})"
            )
        return (today - timedelta(days=days - 1), today)

    if ahead is not None:
        if ahead <= 0:
            raise click.UsageError("--ahead must be a positive integer")
        if ahead > _MAX_DAYS:
            raise click.UsageError(
                f"Date range cannot exceed {_MAX_DAYS} days (got --ahead {ahead})"
            )
        return (today, today + timedelta(days=ahead - 1))

    if from_date is not None and to_date is not None:
        if from_date > to_date:
            raise click.UsageError(
                f"--from date ({from_date}) must be on or before --to date ({to_date})"
            )
        span = (to_date - from_date).days + 1
        if span > _MAX_DAYS:
            raise click.UsageError(
                f"Date range cannot exceed {_MAX_DAYS} days "
                f"(got {span} days from {from_date} to {to_date})"
            )
        return (from_date, to_date)

    # Default: past default_days days (inclusive of today)
    if default_days <= 1:
        return (today, today)
    return (today - timedelta(days=default_days - 1), today)
