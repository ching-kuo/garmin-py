"""Published MCP input schemas for structured workout and training-plan arguments.

These mirror ``workout_schema.validate_workout_input`` and
``services.training_plan.validate_training_plan`` so clients see the real
shape. The validators stay the authority for cross-field rules (zone limits per
target type, exactly one of workout_id/workout, date ranges, nested repeats);
the schema only rejects wrong types and unknown keys. Strict mode keeps
pydantic from coercing values (``"1"`` or ``true`` to an id) the validators
would have rejected.
"""

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, WithJsonSchema

_STRICT = ConfigDict(extra="forbid", strict=True)

# int | float keeps an integer an integer (a plain float field would turn 300
# into 300.0 in the wire payload); published as a single JSON number.
Number = Annotated[int | float, WithJsonSchema({"type": "number"})]

# Literal values are drift-guarded against workout_schema's tables by a test.
Sport = Literal[
    "running", "cycling", "swimming", "walking", "multi_sport", "fitness_equipment", "hiking", "other"
]
StepType = Literal["warmup", "cooldown", "interval", "recovery", "rest", "repeat"]
TargetType = Literal["no.target", "open", "heart.rate.zone", "power.zone", "speed.zone", "cadence.zone"]


class Duration(TypedDict):
    """time in seconds, distance in meters."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    type: Literal["time", "distance"]
    value: Number


class Target(TypedDict):
    """zone for heart.rate.zone (1-5) / power.zone (1-7); min < max for speed.zone (m/s) / cadence.zone."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    type: TargetType
    zone: NotRequired[int]
    min: NotRequired[Number]
    max: NotRequired[Number]


class Step(TypedDict):
    """Regular step: type, duration, target?. Repeat step: type=repeat, count (1-99), steps (no nested repeats)."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    type: StepType
    duration: NotRequired[Duration]
    target: NotRequired[Target | None]
    count: NotRequired[int]
    steps: NotRequired[list["Step"]]


class WorkoutInput(TypedDict):
    __pydantic_config__ = _STRICT  # type: ignore[misc]
    name: str
    sport: Sport
    steps: list[Step]
    description: NotRequired[str | None]


class WorkoutUpdate(TypedDict):
    """Only the fields to change. Garmin read-only fields are tolerated and ignored."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    name: NotRequired[str]
    sport: NotRequired[Sport]
    steps: NotRequired[list[Step]]
    description: NotRequired[str | None]
    workoutId: NotRequired[Any]
    ownerId: NotRequired[Any]
    createdDate: NotRequired[Any]
    updatedDate: NotRequired[Any]
    consumer: NotRequired[Any]
    atpPlanId: NotRequired[Any]


class PlanEntry(TypedDict):
    """Exactly one of workout_id or workout. Moves/replacements need expected_source_date."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    entry_id: str
    date: str
    workout_id: NotRequired[int]
    workout: NotRequired[WorkoutInput]
    move_from_schedule_id: NotRequired[int]
    replace_schedule_id: NotRequired[int]
    expected_source_date: NotRequired[str]


class PlanRemoval(TypedDict):
    __pydantic_config__ = _STRICT  # type: ignore[misc]
    schedule_id: int
    expected_date: str


class TrainingPlan(TypedDict):
    """Dates are YYYY-MM-DD; range at most 90 days; at most 50 entries, one per date."""

    __pydantic_config__ = _STRICT  # type: ignore[misc]
    name: str
    start_date: str
    end_date: str
    entries: list[PlanEntry]
    removals: NotRequired[list[PlanRemoval]]
    description: NotRequired[str | None]
