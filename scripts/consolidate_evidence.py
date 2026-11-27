"""Consolidate review evidence and open the human release gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from factory_app import run_state  # noqa: E402
from factory_app.evidence_runner import run_evidence  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/consolidate_evidence.py CR-001")
    change_id = sys.argv[1].strip().upper()
    try:
        result = run_evidence(change_id)
    except run_state.RunStateError as error:
        raise SystemExit(str(error)) from error

    print(f"{result.change_id}: {result.status}")
    print(
        "Evidence consolidated. A release manager decides with:\n"
        f'  python scripts/approve_gate.py {result.change_id} release APPROVED '
        '"Release evidence reviewed" --by <name> --role release_manager'
    )


if __name__ == "__main__":
    main()
