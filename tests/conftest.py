"""Shared fixtures for garmin-cli test suite."""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


if "mix_stderr" not in inspect.signature(CliRunner.__init__).parameters:
    _cli_runner_init = CliRunner.__init__

    def _compat_cli_runner_init(
        self: CliRunner,
        *args: Any,
        mix_stderr: bool | None = None,
        **kwargs: Any,
    ) -> None:
        _ = mix_stderr
        _cli_runner_init(self, *args, **kwargs)

    CliRunner.__init__ = _compat_cli_runner_init


# ---------------------------------------------------------------------------
# E2E skip gating (registered at root so --e2e works from any collection path)
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help=(
            "run end-to-end tests against real Garmin Connect API; some live "
            "tests expect an account with HRV, VO2 max, and threshold data"
        ),
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--e2e", default=False):
        return
    skip_e2e = pytest.mark.skip(reason="need --e2e option to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


# ---------------------------------------------------------------------------
# Garth mock
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_garth(mocker: Any) -> MagicMock:
    """Patch the entire garth module with a MagicMock."""
    mock = mocker.MagicMock(name="garth")
    mocker.patch.dict("sys.modules", {"garth": mock})
    return mock


# ---------------------------------------------------------------------------
# Sample API payloads (raw, as returned by garth / Garmin Connect)
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_sleep_raw() -> dict:
    return {
        "dailySleepDTO": {
            "calendarDate": "2026-03-11",
            "sleepStartTimestampLocal": 1773183600000,
            "sleepEndTimestampLocal": 1773210600000,
            "sleepTimeSeconds": 27000,
            "deepSleepSeconds": 5400,
            "lightSleepSeconds": 10800,
            "remSleepSeconds": 7200,
            "awakeSleepSeconds": 3600,
            "sleepScores": {"overall": {"value": 82}},
        }
    }


@pytest.fixture()
def sample_sleep_multi_raw() -> list[dict]:
    return [
        {
            "dailySleepDTO": {
                "calendarDate": "2026-03-10",
                "sleepTimeSeconds": 25200,
                "deepSleepSeconds": 4800,
                "lightSleepSeconds": 9600,
                "remSleepSeconds": 6000,
                "awakeSleepSeconds": 4800,
                "sleepScores": {"overall": {"value": 75}},
            }
        },
        {
            "dailySleepDTO": {
                "calendarDate": "2026-03-11",
                "sleepTimeSeconds": 27000,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 10800,
                "remSleepSeconds": 7200,
                "awakeSleepSeconds": 3600,
                "sleepScores": {"overall": {"value": 82}},
            }
        },
    ]


@pytest.fixture()
def sample_hrv_raw() -> dict:
    return {
        "hrvSummary": {
            "calendarDate": "2026-03-11",
            "weeklyAvg": 52,
            "lastNightAvg": 48,
            "status": "BALANCED",
        }
    }


@pytest.fixture()
def sample_weight_raw() -> dict:
    return {
        "dateWeightList": [
            {
                "calendarDate": "2026-03-11",
                "weight": 75000,  # grams
                "bmi": 23.5,
                "bodyFat": 18.2,
            }
        ]
    }


@pytest.fixture()
def sample_body_battery_raw() -> dict:
    return {
        "bodyBatteryValuesArray": [
            ["2026-03-11T08:00:00", 85, "CHARGED"],
            ["2026-03-11T14:00:00", 60, "DRAINING"],
        ]
    }


@pytest.fixture()
def sample_stress_raw() -> dict:
    return {
        "stressValuesArray": [
            ["2026-03-11T08:00:00", 25],
            ["2026-03-11T14:00:00", 45],
        ],
        "avgStressLevel": 35,
        "maxStressLevel": 72,
    }


@pytest.fixture()
def sample_spo2_raw() -> dict:
    return {
        "dateTime": "2026-03-11",
        "averageSpO2": 97,
        "lowestSpO2": 93,
    }


@pytest.fixture()
def sample_resting_hr_raw() -> dict:
    # restingHeartRate is the current displayName-scoped dailyHeartRate
    # response key; restingHeartRateValue (legacy bare-path key) is covered
    # separately as a fallback in test_serializers.py.
    return {
        "restingHeartRate": 52,
        "calendarDate": "2026-03-11",
    }


@pytest.fixture()
def sample_training_readiness_raw() -> dict:
    return {
        "calendarDate": "2026-03-11",
        "score": 68,
        "level": "MODERATE",
        "timerStart": "2026-03-11T00:00:00",
    }


@pytest.fixture()
def sample_training_status_raw() -> dict:
    return {
        "calendarDate": "2026-03-11",
        "trainingStatusType": "PRODUCTIVE",
        "trainingLoadType": "OPTIMAL",
    }


@pytest.fixture()
def sample_activity_raw() -> dict:
    return {
        "activityId": 12345678,
        "startTimeLocal": "2026-03-11T07:30:00",
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "distance": 10000.0,
        "duration": 3600.0,
        "averageHR": 155,
        "calories": 650,
        "elevationGain": 120.0,
    }


@pytest.fixture()
def sample_activities_list_raw() -> list[dict]:
    return [
        {
            "activityId": 12345678,
            "startTimeLocal": "2026-03-11T07:30:00",
            "activityName": "Morning Run",
            "activityType": {"typeKey": "running"},
            "distance": 10000.0,
            "duration": 3600.0,
            "averageHR": 155,
            "calories": 650,
            "elevationGain": 120.0,
        },
        {
            "activityId": 12345679,
            "startTimeLocal": "2026-03-10T06:00:00",
            "activityName": "Afternoon Ride",
            "activityType": {"typeKey": "cycling"},
            "distance": 35000.0,
            "duration": 5400.0,
            "averageHR": 140,
            "calories": 900,
            "elevationGain": 350.0,
        },
    ]


@pytest.fixture()
def sample_activity_weather_raw() -> dict:
    # Mirrors the real /activity/{id}/weather wire shape: temp/relativeHumidity/
    # windDirection plus a nested weatherTypeDTO; no icon-code or precip field.
    return {
        "issueDate": "2026-06-12T23:50:00.000+00:00",
        "temp": 74,
        "apparentTemp": 74,
        "dewPoint": 66,
        "relativeHumidity": 72,
        "windDirection": 158,
        "windDirectionCompassPoint": "sse",
        "windSpeed": 10,
        "windGust": None,
        "weatherTypeDTO": {"weatherTypePk": None, "desc": "Partly Cloudy", "image": None},
    }


@pytest.fixture()
def sample_multisport_parent_raw() -> dict:
    return {
        "activityId": 18878956566,
        "startTimeLocal": "2026-04-06T06:00:00",
        "activityName": "Miyakojima City Multisport",
        "activityType": {"typeKey": "multi_sport"},
        "isMultiSportParent": True,
        "childIds": [18878956567, 18878956568, 18878956569],
        "distance": None,
        "duration": None,
        "averageHR": None,
    }


@pytest.fixture()
def sample_multisport_children_raw() -> list[dict]:
    return [
        {
            "activityId": 18878956567,
            "activityName": "Swim",
            "activityType": {"typeKey": "open_water_swimming"},
            "distance": 1500.0,
            "duration": 1800.0,
            "averageHR": 145,
            "averageSpeed": 0.833,
            "calories": 350,
        },
        {
            "activityId": 18878956568,
            "activityName": "Bike",
            "activityType": {"typeKey": "cycling"},
            "distance": 40000.0,
            "duration": 4200.0,
            "averageHR": 155,
            "averageSpeed": 9.524,
            "calories": 900,
        },
        {
            "activityId": 18878956569,
            "activityName": "Run",
            "activityType": {"typeKey": "running"},
            "distance": 10000.0,
            "duration": 3000.0,
            "averageHR": 165,
            "averageSpeed": 3.333,
            "calories": 600,
        },
    ]


@pytest.fixture()
def sample_workout_raw() -> dict:
    return {
        "workoutId": 987654,
        "workoutName": "Tempo Run",
        "sportType": {"sportTypeKey": "running"},
        "estimatedDurationInSecs": 3600,
        "description": "4x10min at threshold pace",
    }


@pytest.fixture()
def sample_workout_alt_raw() -> dict:
    return {
        "workoutId": 987654,
        "workoutName": "Tempo Run",
        "sportType": {"displayName": "Running"},
        "estimatedDuration": 3600,
        "description": "4x10min at threshold pace",
    }


@pytest.fixture()
def sample_workout_detail_raw() -> dict:
    return {
        "workoutId": 987654,
        "workoutName": "Tempo Run",
        "sportType": {"sportTypeKey": "running"},
        "estimatedDurationInSecs": 3600,
        "description": "4x10min at threshold pace",
        "workoutSegments": [
            {
                "workoutSteps": [
                    {
                        "stepOrder": 1,
                        "stepType": {"stepTypeKey": "warmup"},
                        "durationType": "time",
                        "durationValue": 600,
                    },
                    {
                        "stepOrder": 2,
                        "stepType": {"stepTypeKey": "interval"},
                        "durationType": "time",
                        "durationValue": 300,
                        "targetType": "heart.rate.zone",
                        "targetValueOne": 160,
                        "targetValueTwo": 170,
                    },
                    {
                        "stepOrder": 3,
                        "stepType": {"stepTypeKey": "cooldown"},
                        "durationType": "time",
                        "durationValue": 600,
                    },
                ]
            }
        ],
    }


@pytest.fixture()
def sample_workouts_list_raw() -> list[dict]:
    return [
        {
            "workoutId": 987654,
            "workoutName": "Tempo Run",
            "sportType": {"sportTypeKey": "running"},
            "estimatedDurationInSecs": 3600,
            "description": "4x10min at threshold pace",
        },
        {
            "workoutId": 987655,
            "workoutName": "Long Ride",
            "sportType": {"sportTypeKey": "cycling"},
            "estimatedDurationInSecs": 7200,
            "description": "Easy endurance ride",
        },
    ]


@pytest.fixture()
def sample_calendar_raw() -> dict:
    return {
        "calendarItems": [
            {
                "date": "2026-03-12",
                "workoutId": 987654,
                "title": "Tempo Run",
                "workoutTypeKey": "running",
                "durationInSeconds": 3600,
                "note": "Hard effort",
            },
            {
                "date": "2026-03-14",
                "id": 987655,
                "title": "Long Ride",
                "workoutTypeKey": "cycling",
                "durationInSeconds": 7200,
                "note": "Easy pace",
            },
        ]
    }


@pytest.fixture()
def sample_lactate_threshold_raw() -> dict:
    return {
        "lactateThresholdHeartRate": 168,
        "lactateThresholdSpeed": 3.2,  # m/s
        "sport": "running",
    }


@pytest.fixture()
def sample_lactate_threshold_live_raw() -> list[dict]:
    return [
        {
            "userProfilePK": 75253976,
            "version": 1772777901901,
            "calendarDate": "2026-03-06T15:18:21.866",
            "sequence": 1772777901901,
            "speed": 0.37499895,
            "hearRate": None,
            "heartRateCycling": None,
            "rowSpeed": None,
        },
        {
            "userProfilePK": 75253976,
            "version": 1772777901901,
            "calendarDate": "2026-03-06T15:18:21.866",
            "sequence": 1772777901901,
            "speed": None,
            "hearRate": 177,
            "heartRateCycling": None,
            "rowSpeed": None,
        },
    ]


@pytest.fixture()
def sample_vo2max_raw() -> dict:
    return {
        "calendarDate": "2026-03-11",
        "vo2MaxValue": 52.0,
        "sport": "running",
    }


@pytest.fixture()
def sample_vo2max_wrapped_raw() -> dict:
    return {
        "maxMetData": {
            "calendarDate": "2026-03-11",
            "vo2MaxValue": 52.0,
            "sport": "running",
        }
    }


@pytest.fixture()
def sample_vo2max_live_raw() -> list[dict]:
    return [
        {
            "userId": 75253976,
            "generic": {
                "calendarDate": "2026-03-10",
                "vo2MaxPreciseValue": 54.1,
                "vo2MaxValue": 54.0,
                "maxMetCategory": 0,
            },
            "cycling": {
                "calendarDate": "2026-03-10",
                "vo2MaxPreciseValue": 55.0,
                "vo2MaxValue": 55.0,
                "maxMetCategory": 1,
            },
            "heatAltitudeAcclimation": {
                "calendarDate": "2026-03-10",
            },
        }
    ]


@pytest.fixture()
def sample_all_thresholds_raw() -> dict:
    return {
        "thresholds": [
            {
                "sport": "running",
                "lactateThresholdHeartRate": 168,
                "lactateThresholdPace": "5:12",
                "functionalThresholdPower": None,
                "weight": 75.0,
            },
            {
                "sport": "cycling",
                "lactateThresholdHeartRate": 162,
                "lactateThresholdPace": None,
                "functionalThresholdPower": 280,
                "weight": 75.0,
            },
        ]
    }

