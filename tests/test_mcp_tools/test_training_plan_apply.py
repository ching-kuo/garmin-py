"""MCP apply/reschedule tests against a stateful fake calendar (ordering, rollback, rechecks)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config  # noqa: E402


def _plan() -> dict:
    return {
        "name": "July block",
        "start_date": "2026-07-01",
        "end_date": "2026-07-14",
        "entries": [{"entry_id": "run-1", "date": "2026-07-10", "workout_id": 10}],
    }


class _FakeCalendar:
    """Stateful stand-in for the Garmin calendar so apply ordering is observable."""

    def __init__(self, rows: list[tuple[str, int, int]]) -> None:
        self.rows = [{"date": day, "workoutId": wid, "workoutScheduleId": sid} for day, wid, sid in rows]
        self.calls: list[tuple[Any, ...]] = []
        # Per-call scripts, consumed in order; "ok" once exhausted.
        # schedule: ok | fail (429, not applied) | ghost (id returned, no row)
        #   | noid (row added, no id returned) | ghost_noid (neither)
        # unschedule: ok | fail (5xx, not applied) | fail_landed (5xx, applied)
        #   | fail_unreadable (5xx, not applied, next read fails) | boom (RuntimeError)
        #   | stale (success, but reads keep showing the row)
        #   | landed_429 (applied, then a 429 after the retries, flagged may_have_landed)
        self.schedule_effects: list[str] = []
        self.unschedule_effects: list[str] = []
        self.read_error = False
        self.incomplete = False  # strict reads fail (supplemental lookup down)
        self.moves_after_first_read: dict[int, str] = {}
        self.reads = 0

    def install(self, mocker: Any) -> None:
        mocker.patch("garmin_cli.mcp_tools._shared.ensure_authenticated")
        mocker.patch("garmin_cli.mcp_tools.training_plan.ensure_authenticated")
        mocker.patch("garmin_cli.services.schedule_writes.get_calendar_range", side_effect=self.get)
        for module in ("plan_apply", "plan_reschedule"):
            mocker.patch(f"garmin_cli.services.{module}.schedule_workout", side_effect=self.schedule)
            mocker.patch(f"garmin_cli.services.{module}.unschedule_workout", side_effect=self.unschedule)
        mocker.patch(
            "garmin_cli.services.plan_apply.get_workout",
            return_value={"workoutName": "Run", "sportType": {"sportTypeKey": "running"}, "workoutSegments": []},
        )

    def get(self, start: Any, end: Any, strict: bool = False) -> list[dict[str, Any]]:
        if self.read_error:
            self.read_error = False
            raise GarminCliError("unreachable", "NETWORK_ERROR")
        if strict and self.incomplete:
            raise GarminCliError("schedule lookup failed", "SERVER_ERROR")
        rows = [dict(row) for row in self.rows if start.isoformat() <= row["date"] <= end.isoformat()]
        self.reads += 1
        if self.reads == 1:
            for row in self.rows:
                row["date"] = self.moves_after_first_read.get(row["workoutScheduleId"], row["date"])
        return rows

    def schedule(self, workout_id: int, day: Any) -> dict[str, Any]:
        effect = self.schedule_effects.pop(0) if self.schedule_effects else "ok"
        if effect == "fail":
            raise GarminCliError("throttled", "RATE_LIMITED")
        schedule_id = 1000 + len(self.calls)
        self.calls.append(("schedule", workout_id, day.isoformat()))
        if effect in {"ok", "noid"}:
            self.rows.append({"date": day.isoformat(), "workoutId": workout_id, "workoutScheduleId": schedule_id})
        return {} if effect in {"noid", "ghost_noid"} else {"workoutScheduleId": schedule_id}

    def unschedule(self, schedule_id: int) -> None:
        effect = self.unschedule_effects.pop(0) if self.unschedule_effects else "ok"
        if effect == "boom":
            raise RuntimeError("unexpected")
        if effect in {"fail", "fail_unreadable"}:
            self.read_error = effect == "fail_unreadable"
            raise GarminCliError("upstream", "SERVER_ERROR")
        self.calls.append(("unschedule", schedule_id))
        if effect != "stale":
            self.rows = [row for row in self.rows if row["workoutScheduleId"] != schedule_id]
        if effect == "fail_landed":
            raise GarminCliError("upstream", "SERVER_ERROR")
        if effect == "landed_429":
            raise GarminCliError("throttled", "RATE_LIMITED", may_have_landed=True)

    def by_date(self) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for row in self.rows:
            result.setdefault(row["date"], []).append(row["workoutId"])
        return {day: sorted(ids) for day, ids in sorted(result.items())}


def _apply(plan: dict) -> dict:
    return _call(create_mcp_server(_config()), "training_plan_apply", {"plan": plan})


def _swap_plan() -> dict:
    plan = _plan()
    plan["entries"] = [
        {"entry_id": "tue", "date": "2026-07-07", "workout_id": 20, "move_from_schedule_id": 2, "expected_source_date": "2026-07-09"},
        {"entry_id": "thu", "date": "2026-07-09", "workout_id": 10, "move_from_schedule_id": 1, "expected_source_date": "2026-07-07"},
    ]
    return plan


def _chained_plan() -> dict:
    plan = _plan()
    plan["entries"] = [
        {"entry_id": "tue-wed", "date": "2026-07-08", "workout_id": 10, "move_from_schedule_id": 1, "expected_source_date": "2026-07-07"},
        {"entry_id": "wed-thu", "date": "2026-07-09", "workout_id": 10, "move_from_schedule_id": 2, "expected_source_date": "2026-07-08"},
    ]
    return plan


def _removals_plan(removals: list[tuple[int, str]]) -> dict:
    plan = _plan()
    plan["entries"] = []
    plan["removals"] = [{"schedule_id": sid, "expected_date": day} for sid, day in removals]
    return plan


def _swap_fake(mocker: Any, schedule: tuple[str, ...] | list[str] = (), unschedule: tuple[str, ...] | list[str] = ()) -> _FakeCalendar:
    fake = _FakeCalendar([("2026-07-07", 10, 1), ("2026-07-09", 20, 2)])
    fake.schedule_effects, fake.unschedule_effects = list(schedule), list(unschedule)
    fake.install(mocker)
    return fake


_SWAP_ORIGINAL = {"2026-07-07": [10], "2026-07-09": [20]}


def test_apply_swaps_two_scheduled_workouts(mocker: Any) -> None:
    fake = _swap_fake(mocker)

    result = _apply(_swap_plan())

    assert result["outcome"] == "complete", result
    assert fake.by_date() == {"2026-07-07": [20], "2026-07-09": [10]}
    # The vacated occupant is removed before the destination is written.
    assert fake.calls[:2] == [("unschedule", 1), ("schedule", 20, "2026-07-07")]


def test_apply_move_onto_a_completed_activity_of_the_workout_schedules_it(mocker: Any) -> None:
    # A logged activity carries the workout's id but is not a schedule: it must
    # neither satisfy the move (keep) nor block it.
    fake = _FakeCalendar([("2026-07-05", 10, 1)])
    fake.rows.append({"date": "2026-07-10", "workoutId": 10, "workoutScheduleId": None, "id": 777, "itemType": "activity"})
    fake.install(mocker)
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 1, "expected_source_date": "2026-07-05"})

    result = _apply(plan)

    assert result["outcome"] == "complete", result
    assert fake.calls == [("schedule", 10, "2026-07-10"), ("unschedule", 1)]


def test_apply_swap_failure_restores_early_removed_sources(mocker: Any) -> None:
    fake = _swap_fake(mocker, schedule=["ok", "fail"])

    result = _apply(_swap_plan())

    assert result["outcome"] == "compensated", result
    assert fake.by_date() == _SWAP_ORIGINAL
    restores = [op for op in result["operations"] if op["action"] == "restore_source"]
    # Restored schedules get new ids; both old and new are reported.
    assert [(op["schedule_id"], op["state"]) for op in restores] == [(2, "compensated"), (1, "compensated")]
    assert all(isinstance(op["restored_schedule_id"], int) for op in restores)
    # New schedules are removed before sources are restored.
    states = [(op["action"], op["state"]) for op in result["operations"]]
    assert states.index(("unschedule", "compensated")) < states.index(("restore_source", "compensated"))


def test_apply_restore_is_verified_by_its_own_schedule_id(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1), ("2026-07-08", 10, 2)])
    # Wed write lands, Thu write fails, Wed restore returns an id but never lands.
    fake.schedule_effects = ["ok", "fail", "ghost"]
    fake.unschedule_effects = ["ok", "boom"]  # the new Wed row survives cleanup
    fake.install(mocker)

    result = _apply(_chained_plan())

    assert result["outcome"] == "unknown", result
    restore = next(op for op in result["operations"] if op["action"] == "restore_source")
    # The surviving new Wed row (same workout) must not count as the restore.
    assert restore["state"] == "unknown"


def test_apply_idless_restores_of_one_workout_claim_distinct_rows(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1), ("2026-07-07", 10, 2), ("2026-07-08", 20, 3)])
    fake.unschedule_effects = ["ok", "ok", "fail"]
    fake.schedule_effects = ["noid", "noid"]
    fake.install(mocker)

    result = _apply(_removals_plan([(1, "2026-07-07"), (2, "2026-07-07"), (3, "2026-07-08")]))

    assert result["outcome"] == "compensated", result
    restored = [op["restored_schedule_id"] for op in result["operations"] if op["action"] == "restore_source"]
    assert len(set(restored)) == 2
    assert fake.by_date() == {"2026-07-07": [10, 10], "2026-07-08": [20]}


def test_apply_idless_restore_never_claims_an_untouched_schedule(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1), ("2026-07-07", 10, 9), ("2026-07-08", 20, 3)])
    fake.unschedule_effects = ["ok", "fail"]
    fake.schedule_effects = ["ghost_noid"]
    fake.install(mocker)

    result = _apply(_removals_plan([(1, "2026-07-07"), (3, "2026-07-08")]))

    assert result["outcome"] == "unknown", result
    restore = next(op for op in result["operations"] if op["action"] == "restore_source")
    assert restore["state"] == "unknown" and "restored_schedule_id" not in restore


@pytest.mark.parametrize(("effect", "outcome"), [("ghost", "compensated"), ("ghost_noid", "unknown")])
def test_apply_stale_row_of_a_deleted_schedule_does_not_verify_a_move(mocker: Any, effect: str, outcome: str) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1), ("2026-07-08", 10, 2)])
    fake.unschedule_effects = ["stale"]  # Wed source deleted, but reads still show it
    fake.schedule_effects = [effect]  # the Wed write never shows up
    fake.install(mocker)

    result = _apply(_chained_plan())

    assert result["outcome"] == outcome, result
    assert not any(op.get("state") == "verified" for op in result["operations"])


@pytest.mark.parametrize(
    ("effect", "outcome"),
    [
        ("fail_landed", "compensated"),
        ("landed_429", "compensated"),  # 503 landed, retries then hit 429
        ("fail", "compensated"),
        ("fail_unreadable", "unknown"),
    ],
)
def test_apply_ambiguous_source_delete_is_rechecked(mocker: Any, effect: str, outcome: str) -> None:
    fake = _swap_fake(mocker, unschedule=[effect])

    result = _apply(_swap_plan())

    assert result["outcome"] == outcome, result
    assert fake.by_date() == _SWAP_ORIGINAL
    if effect == "fail_unreadable":
        assert {"action": "unschedule", "schedule_id": 1, "state": "unknown"} in result["operations"]


def test_apply_recheck_needs_a_complete_calendar_read(mocker: Any) -> None:
    fake = _swap_fake(mocker, unschedule=["fail_landed"])
    fake.incomplete = True

    result = _apply(_swap_plan())

    assert result["outcome"] == "unknown", result
    assert {"action": "unschedule", "schedule_id": 1, "state": "unknown"} in result["operations"]


def test_apply_landed_final_source_delete_is_success(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-05", 55, 77)])
    fake.unschedule_effects = ["fail_landed"]
    fake.install(mocker)
    plan = _plan()
    plan["removals"] = [{"schedule_id": 77, "expected_date": "2026-07-05"}]

    result = _apply(plan)

    assert (result["complete"], result["outcome"]) == (True, "complete"), result
    assert fake.by_date() == {"2026-07-10": [10]}
    assert not any(op["action"] == "restore_source" for op in result["operations"])


def test_apply_does_not_vacate_a_source_that_moved_onto_the_destination(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-11", 55, 77)])
    fake.moves_after_first_read = {77: "2026-07-10"}  # moved after the plan snapshot
    fake.install(mocker)
    plan = _plan()
    plan["removals"] = [{"schedule_id": 77, "expected_date": "2026-07-11"}]

    result = _apply(plan)

    assert result["complete"] is False
    assert result["conflicts"] == [{"entry_id": "run-1", "reason": "source_schedule_changed"}]
    assert fake.calls == []


def test_apply_never_deletes_a_source_that_moved_to_a_third_date(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1)])
    fake.moves_after_first_read = {1: "2026-07-12"}  # moved elsewhere after the plan snapshot
    fake.install(mocker)
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 1, "expected_source_date": "2026-07-07"})

    result = _apply(plan)

    assert result["outcome"] == "compensated"
    assert result["conflicts"] == [{"entry_id": "run-1", "reason": "source_schedule_changed"}]
    assert ("unschedule", 1) not in fake.calls
    assert fake.by_date() == {"2026-07-12": [10]}


def test_apply_source_recheck_failure_deletes_nothing(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-07", 10, 1)])
    fake.install(mocker)
    plan = _plan()
    plan["entries"][0].update({"move_from_schedule_id": 1, "expected_source_date": "2026-07-07"})
    original_schedule = fake.schedule

    def schedule_then_break_strict_reads(workout_id: int, day: Any) -> dict[str, Any]:
        fake.incomplete = True
        return original_schedule(workout_id, day)

    mocker.patch("garmin_cli.services.plan_apply.schedule_workout", side_effect=schedule_then_break_strict_reads)

    result = _apply(plan)

    assert result["outcome"] == "compensated"
    assert ("unschedule", 1) not in fake.calls
    assert fake.by_date() == {"2026-07-07": [10]}


def test_restore_continues_past_an_unparsable_source_date(mocker: Any) -> None:
    from garmin_cli.services.plan_apply import _restore_sources

    fake = _FakeCalendar([])
    fake.install(mocker)
    operations: list[dict[str, Any]] = []
    sources = [
        {"workout_id": 10, "date": "07/07/2026", "workout_schedule_id": 1},
        {"workout_id": 20, "date": "2026-07-09", "workout_schedule_id": 2},
    ]

    assert _restore_sources(sources, set(), operations) is False

    assert [(op["schedule_id"], op["state"]) for op in operations] == [(2, "compensated"), (1, "unknown")]
    assert fake.by_date() == {"2026-07-09": [20]}


def test_apply_compensation_continues_past_unexpected_errors(mocker: Any) -> None:
    fake = _swap_fake(mocker, schedule=["ok", "fail"], unschedule=["ok", "ok", "boom"])  # new Tue row cleanup raises

    result = _apply(_swap_plan())

    assert result["outcome"] == "unknown", result
    assert {"action": "unschedule", "schedule_id": 1001, "state": "unknown", "error_code": "INTERNAL_ERROR"} in result["operations"]
    # Source restores still ran.
    assert fake.by_date() == {"2026-07-07": [10, 20], "2026-07-09": [20]}


def test_apply_removal_and_replacement_on_same_date(mocker: Any) -> None:
    fake = _FakeCalendar([("2026-07-10", 55, 77)])
    fake.install(mocker)
    plan = _plan()
    plan["removals"] = [{"schedule_id": 77, "expected_date": "2026-07-10"}]

    result = _apply(plan)

    assert result["outcome"] == "complete", result
    assert fake.by_date() == {"2026-07-10": [10]}
    assert fake.calls.count(("unschedule", 77)) == 1


@pytest.mark.parametrize(
    "rows",
    [
        [("2026-07-05", 10, 50), ("2026-07-10", 55, 77)],
        [("2026-07-05", 10, 50), ("2026-07-10", 10, 99), ("2026-07-10", 55, 77)],
    ],
)
def test_reschedule_rejects_destination_with_a_different_workout(mocker: Any, rows: list) -> None:
    fake = _FakeCalendar(rows)
    fake.install(mocker)

    result = _call(
        create_mcp_server(_config()),
        "training_plan_reschedule",
        {"schedule_id": 50, "expected_date": "2026-07-05", "new_date": "2026-07-10"},
    )

    assert result["complete"] is False
    assert result["conflicts"] == [{"reason": "destination_occupied"}]
    assert fake.calls == []
