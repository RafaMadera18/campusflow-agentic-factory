"""Run independent review and security review for a verified Change Request."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from factory_app import run_state  # noqa: E402
from factory_app.adk_runtime import make_agent_fn  # noqa: E402
from factory_app.agents import reviewer_agent, security_agent  # noqa: E402
from factory_app.review_runner import run_review  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/run_review.py CR-001")
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    change_id = sys.argv[1].strip().upper()

    try:
        result = run_review(
            change_id,
            make_agent_fn(reviewer_agent),
            make_agent_fn(security_agent),
        )
    except run_state.RunStateError as error:
        raise SystemExit(str(error)) from error

    print(f"{result.change_id}: {result.status}")
    print(
        "Review evidence is ready. A reviewer records the human decision with:\n"
        f'  python scripts/approve_gate.py {result.change_id} review APPROVED '
        '"Review findings resolved" --by <name> --role reviewer'
    )


if __name__ == "__main__":
    main()
