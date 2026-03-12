from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.e2e.conftest import RateLimiter, fetch_first_resource_id, _invoke_cli_json


def test_rate_limiter_wait_uses_last_completed_timestamp(mocker):
    limiter = RateLimiter(min_delay=5.0)

    mocker.patch("tests.e2e.conftest.time.monotonic", side_effect=[10.0, 13.0])
    sleep = mocker.patch("tests.e2e.conftest.time.sleep")

    limiter.mark_complete()
    limiter.wait()

    sleep.assert_called_once_with(2.0)


def test__invoke_cli_json_marks_completion_after_invoke(mocker):
    events: list[str] = []
    cli_runner = mocker.Mock()
    rate_limiter = mocker.Mock()

    rate_limiter.wait.side_effect = lambda extra_delay=0.0: events.append(
        f"wait:{extra_delay}"
    )
    rate_limiter.mark_complete.side_effect = lambda: events.append("mark_complete")
    cli_runner.invoke.side_effect = lambda *args, **kwargs: (
        events.append("invoke")
        or SimpleNamespace(output='{"ok": true, "data": []}', exit_code=0)
    )

    result, parsed = _invoke_cli_json(
        cli_runner,
        rate_limiter,
        ["activity", "list", "--limit", "1"],
        extra_delay=10.0,
    )

    assert result.exit_code == 0
    assert parsed == {"ok": True, "data": []}
    assert events == ["wait:10.0", "invoke", "mark_complete"]


def test_fetch_first_resource_id_returns_none_for_empty_success(mocker):
    cli_runner = mocker.Mock()
    rate_limiter = mocker.Mock()
    cli_runner.invoke.return_value = SimpleNamespace(
        output='{"ok": true, "data": []}',
        exit_code=0,
    )

    resource_id = fetch_first_resource_id(cli_runner, rate_limiter, "activity")

    assert resource_id is None


def test_fetch_first_resource_id_fails_for_error_envelope(mocker):
    cli_runner = mocker.Mock()
    rate_limiter = mocker.Mock()
    cli_runner.invoke.return_value = SimpleNamespace(
        output='{"ok": false, "error_code": "RATE_LIMITED"}',
        exit_code=1,
    )

    with pytest.raises(pytest.fail.Exception, match="activity list bootstrap failed"):
        fetch_first_resource_id(cli_runner, rate_limiter, "activity")


def test_fetch_first_resource_id_fails_for_non_json_output(mocker):
    cli_runner = mocker.Mock()
    rate_limiter = mocker.Mock()
    cli_runner.invoke.return_value = SimpleNamespace(
        output="not json",
        exit_code=1,
    )

    with pytest.raises(
        pytest.fail.Exception,
        match="activity list bootstrap returned non-JSON output",
    ):
        fetch_first_resource_id(cli_runner, rate_limiter, "activity")
