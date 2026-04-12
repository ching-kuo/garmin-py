import json
import os
import time
from typing import Any

import pytest
from click.testing import CliRunner

from garmin_cli.cli import cli


class RateLimiter:
    def __init__(self, min_delay: float = 5.0) -> None:
        self._min_delay = min_delay
        self._last_completed: float = 0.0

    def wait(self, extra_delay: float = 0.0) -> None:
        total_delay = self._min_delay + extra_delay
        now = time.monotonic()
        elapsed = now - self._last_completed
        if elapsed < total_delay and self._last_completed > 0:
            time.sleep(total_delay - elapsed)

    def mark_complete(self) -> None:
        self._last_completed = time.monotonic()


def assert_envelope_ok(parsed: dict[str, Any] | None) -> None:
    assert parsed is not None, "Response could not be parsed as JSON"
    assert "ok" in parsed, "Missing 'ok' key in response"
    assert parsed["ok"] is True, (
        f"Response not ok: error_code={parsed.get('error_code', 'unknown')}"
    )
    for key in ("command", "count", "data"):
        assert key in parsed, f"Missing '{key}' key in response envelope"
    assert isinstance(parsed["command"], str), "command is not a string"
    assert isinstance(
        parsed["count"], int
    ), f"count is not an int: type={type(parsed['count']).__name__}"
    assert isinstance(parsed["data"], list), "data is not a list"
    assert parsed["count"] == len(parsed["data"]), (
        f"count mismatch: count={parsed['count']}, len(data)={len(parsed['data'])}"
    )


def assert_row_has_keys(row: dict[str, Any], expected_keys: list[str]) -> None:
    missing = set(expected_keys) - set(row.keys())
    assert not missing, f"Missing keys in row: {missing}"


def assert_exit_ok(result: Any) -> None:
    assert result.exit_code == 0, f"CLI exited with code {result.exit_code}"


def assert_numeric_or_none(value: Any, field_name: str) -> None:
    """Assert a value is numeric (int/float) or None without printing actual values."""
    assert isinstance(value, (int, float)) or value is None, (
        f"{field_name} must be numeric or None, got {type(value).__name__}"
    )


def _invoke_cli_json(
    cli_runner: CliRunner,
    rate_limiter: RateLimiter,
    args: list[str],
    *,
    extra_delay: float = 0.0,
) -> tuple[Any, dict[str, Any] | None]:
    rate_limiter.wait(extra_delay)
    try:
        result = cli_runner.invoke(cli, ["--json"] + args)
    finally:
        rate_limiter.mark_complete()
    try:
        parsed = json.loads(result.output)
    except json.JSONDecodeError:
        return result, None
    return result, parsed


def fetch_first_resource_id(
    cli_runner: CliRunner,
    rate_limiter: RateLimiter,
    command: str,
) -> str | int | None:
    """Fetch the first item ID for a given command (e.g. 'activity', 'workout')."""
    result, parsed = _invoke_cli_json(
        cli_runner,
        rate_limiter,
        [command, "list", "--limit", "1"],
    )
    if parsed is None:
        pytest.fail(
            f"{command} list bootstrap returned non-JSON output "
            f"(exit_code={result.exit_code})"
        )
    if result.exit_code != 0 or parsed.get("ok") is not True:
        pytest.fail(
            f"{command} list bootstrap failed: exit_code={result.exit_code}, "
            f"error_code={parsed.get('error_code', 'unknown')}"
        )
    data = parsed.get("data")
    if not isinstance(data, list):
        pytest.fail(f"{command} list bootstrap returned invalid data payload")
    if not data:
        return None
    return data[0].get("id")


@pytest.fixture(scope="session")
def cli_runner():
    return CliRunner(mix_stderr=False)


@pytest.fixture(scope="session")
def rate_limiter():
    min_delay = float(os.environ.get("E2E_RATE_LIMIT_SECONDS", "5"))
    return RateLimiter(min_delay=min_delay)


@pytest.fixture(scope="session")
def garth_session():
    mp = pytest.MonkeyPatch()
    mp.delenv("GARMIN_EMAIL", raising=False)
    mp.delenv("GARMIN_PASSWORD", raising=False)

    garth_home = os.path.expanduser(
        os.environ.get("GARMIN_HOME", os.environ.get("GARTH_HOME", "~/.garminconnect"))
    )
    if not os.path.isdir(garth_home):
        pytest.skip(
            "Garmin home directory not found (set GARMIN_HOME or GARTH_HOME to override)"
        )

    token_file = os.path.join(garth_home, "garmin_tokens.json")
    if not os.path.isfile(token_file):
        pytest.skip(
            "No garmin_tokens.json found in the Garmin home directory (run garmin-cli login first)"
        )

    yield garth_home
    mp.undo()


@pytest.fixture()
def run_cli(cli_runner, rate_limiter, garth_session):
    # garth_session dependency ensures auth is validated before any CLI calls
    def _run_cli(args: list[str], extra_delay: float = 0.0):
        return _invoke_cli_json(
            cli_runner,
            rate_limiter,
            args,
            extra_delay=extra_delay,
        )

    return _run_cli
