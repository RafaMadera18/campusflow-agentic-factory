"""Run Intake and Planner for a Change Request and stop at the human gate.

Usage: python scripts/run_planning.py CR-001
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `python scripts/run_planning.py` import factory_app

from dotenv import load_dotenv  # noqa: E402

from factory_app import run_state  # noqa: E402
from factory_app.adk_runtime import make_agent_fn  # noqa: E402
from factory_app.agents import intake_agent, planner_agent  # noqa: E402
from factory_app.planning_runner import run_planning  # noqa: E402

NEXT_STEP = {
    run_state.AWAITING_CLARIFICATION: (
        "STOPPED: the Change Request is ambiguous. Read runs/{cr}/01-intake-report.md, then the\n"
        "Product Owner answers with:\n"
        '  python scripts/approve_gate.py {cr} requirements APPROVED "<the policy>" '
        "--by <name> --role product_owner"
    ),
    run_state.AWAITING_PLAN_APPROVAL: (
        "Plan ready. Review runs/{cr}/03-implementation-plan.md, then the Tech Lead decides with:\n"
        '  python scripts/approve_gate.py {cr} plan APPROVED "<why>" --by <name> --role tech_lead'
    ),
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/run_planning.py CR-001")
    load_dotenv(ROOT / ".env")  # GOOGLE_API_KEY lives there; `adk run` does this by itself
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    change_id = sys.argv[1].strip().upper()

    try:
        result = run_planning(
            change_id, make_agent_fn(intake_agent), make_agent_fn(planner_agent)
        )
    except run_state.RunStateError as error:
        raise SystemExit(str(error)) from error

    print(f"{result.change_id}: {result.status}")
    print(NEXT_STEP.get(result.status, "").format(cr=result.change_id))


if __name__ == "__main__":
    main()
