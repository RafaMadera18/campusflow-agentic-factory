"""Run Coder -> Test Analyst -> the deterministic Verification Gate for one Change Request.

Usage: python scripts/run_coding.py CR-001

Requires an APPROVED plan gate (scripts/approve_gate.py ... plan APPROVED ...).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `python scripts/run_coding.py` import factory_app

from dotenv import load_dotenv  # noqa: E402

from factory_app import run_state  # noqa: E402
from factory_app.adk_runtime import make_agent_fn  # noqa: E402
from factory_app.agents import coder_agent, test_analyst_agent  # noqa: E402
from factory_app.coding_runner import MAX_FIX_ATTEMPTS, run_coding  # noqa: E402

PASSED_NEXT = (
    "Deterministic verification passed (07-verification.txt). Next milestone: the "
    "independent Reviewer + Security stage, still to be wired. Evidence so far in runs/{cr}/"
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/run_coding.py CR-001")
    load_dotenv(ROOT / ".env")  # GOOGLE_API_KEY lives there; `adk run` does this by itself
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    change_id = sys.argv[1].strip().upper()

    try:
        result = run_coding(
            change_id, make_agent_fn(coder_agent), make_agent_fn(test_analyst_agent)
        )
    except run_state.RunStateError as error:
        raise SystemExit(str(error)) from error

    print(f"{result.change_id}: {result.status} ({result.attempts} coder iteration(s))")
    if result.status == run_state.VERIFICATION_PASSED:
        print(PASSED_NEXT.format(cr=result.change_id))
        return

    print(
        f"STOPPED: the Verification Gate is still red after {MAX_FIX_ATTEMPTS} fix retries.\n"
        f"Read runs/{result.change_id}/07-verification.txt and intervene as a human. Running\n"
        f"this script again starts a fresh fix batch from the current diff."
    )


if __name__ == "__main__":
    main()
