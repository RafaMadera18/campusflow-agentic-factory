"""Tests for the retry/backoff wrapper used around LLM calls (rate limits, busy models)."""

import pytest

from factory_app.retry import call_with_retries


class FakeApiError(Exception):
    """Looks like google.genai errors: they expose the HTTP status in `.code`."""

    def __init__(self, code):
        super().__init__(f"{code} error")
        self.code = code


def flaky(failures, error):
    """Return a function that raises `error` `failures` times, then returns 'ok'."""
    state = {"calls": 0}

    def call():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise error
        return "ok"

    call.state = state
    return call


def test_success_on_first_try_does_not_sleep():
    sleeps = []

    assert call_with_retries(lambda: "ok", sleep=sleeps.append) == "ok"
    assert sleeps == []


@pytest.mark.parametrize("code", [429, 500, 503])
def test_busy_or_rate_limited_calls_are_retried(code):
    call = flaky(2, FakeApiError(code))

    assert call_with_retries(call, sleep=lambda _seconds: None) == "ok"
    assert call.state["calls"] == 3


def test_waiting_time_grows_exponentially():
    sleeps = []
    call = flaky(3, FakeApiError(503))

    call_with_retries(call, base_delay=2, sleep=sleeps.append)

    assert sleeps == [2, 4, 8]


def test_it_gives_up_after_max_attempts_and_raises_the_last_error():
    call = flaky(10, FakeApiError(429))

    with pytest.raises(FakeApiError):
        call_with_retries(call, max_attempts=3, sleep=lambda _seconds: None)

    assert call.state["calls"] == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_errors_that_retrying_cannot_fix_are_raised_immediately(code):
    call = flaky(1, FakeApiError(code))

    with pytest.raises(FakeApiError):
        call_with_retries(call, sleep=lambda _seconds: None)

    assert call.state["calls"] == 1


def test_errors_without_a_status_code_are_raised_immediately():
    call = flaky(1, ValueError("bug in our code"))

    with pytest.raises(ValueError):
        call_with_retries(call, sleep=lambda _seconds: None)

    assert call.state["calls"] == 1
