"""Record a human decision on a gate.

Usage:
  python scripts/approve_gate.py CR-001 plan APPROVED "Plan reviewed" --by Rafa --role tech_lead
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `python scripts/approve_gate.py` import factory_app

from factory_app import run_state  # noqa: E402


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a human decision on a gate.")
    parser.add_argument("change_id", help="for example CR-001")
    parser.add_argument("gate", help=f"one of {list(run_state.GATE_RULES)}")
    parser.add_argument("decision", help=f"one of {list(run_state.DECISIONS)}")
    parser.add_argument("reason", help="why the human decided this (required)")
    parser.add_argument("--by", required=True, help="name of the person who decides")
    parser.add_argument("--role", required=True, help="product_owner, tech_lead...")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    try:
        path = run_state.record_decision(
            args.change_id,
            args.gate.lower(),
            args.decision.upper(),
            args.reason,
            decided_by=args.by,
            role=args.role.lower(),
        )
    except run_state.RunStateError as error:
        raise SystemExit(f"Decision NOT recorded: {error}") from error
    status = run_state.load_state(args.change_id)["status"]
    print(f"Recorded. Evidence: {path.relative_to(ROOT)}")
    print(f"Run status is now {status}")


if __name__ == "__main__":
    main()
