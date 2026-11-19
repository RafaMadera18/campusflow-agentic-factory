"""Retry with exponential backoff for LLM calls.

The Gemini free tier answers ``429 RESOURCE_EXHAUSTED`` when a quota is used up and
``503 UNAVAILABLE`` when the model is busy. Both usually go away after a short wait,
so the factory waits and tries again instead of failing the whole run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# HTTP status codes worth retrying. Anything else (400, 401, 403, 404...) is our mistake
# and retrying would only waste quota.
RETRYABLE_STATUS_CODES = {429, 500, 503}

logger = logging.getLogger(__name__)


def call_with_retries(
    call: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``call()``; on a retryable error wait 2s, 4s, 8s... and try again.

    After ``max_attempts`` the last error is raised. ``sleep`` can be replaced in tests.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as error:
            is_retryable = getattr(error, "code", None) in RETRYABLE_STATUS_CODES
            if not is_retryable or attempt == max_attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            logger.warning(
                "Model call failed (%s). Retrying in %ss (attempt %s of %s)",
                error.code,
                delay,
                attempt,
                max_attempts,
            )
            sleep(delay)
    raise AssertionError("unreachable: the loop above always returns or raises")
