"""Create the run folder for a Change Request.

Usage: python scripts/start_run.py CR-001
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `python scripts/start_run.py` import factory_app

from factory_app import run_state  # noqa: E402

CR_DIR = ROOT / "change_requests"


def find_change_request(change_id: str) -> Path:
    matches = sorted(CR_DIR.glob(f"{change_id}-*.md"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one Change Request for {change_id}; found {len(matches)}")
    return matches[0]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/start_run.py CR-001")
    change_id = sys.argv[1].strip().upper()
    source = find_change_request(change_id)
    try:
        run = run_state.create_run(change_id, source)
    except run_state.RunAlreadyExistsError as error:
        raise SystemExit(str(error)) from error
    print(f"Created {run.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
