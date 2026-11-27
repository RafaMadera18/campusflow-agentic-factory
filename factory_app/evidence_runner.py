"""Consolidate produced evidence and open the human release gate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import run_state


@dataclass(frozen=True)
class EvidenceResult:
    change_id: str
    status: str


def run_evidence(change_id: str, runs_dir: Path = run_state.RUNS_DIR) -> EvidenceResult:
    change_id = change_id.upper()
    state = run_state.load_state(change_id, runs_dir)
    if state["status"] != run_state.EVIDENCE_CONSOLIDATED:
        raise run_state.RunStateError(
            f"{change_id} is {state['status']}. Evidence consolidation requires "
            "EVIDENCE_CONSOLIDATED."
        )

    folder = run_state.run_folder(change_id, runs_dir)
    required = (
        "00-change-request.md",
        "03-implementation-plan.md",
        "07-verification.txt",
        "08-review-report.md",
        "09-security-report.md",
    )
    missing = [filename for filename in required if not (folder / filename).is_file()]
    if missing:
        raise run_state.RunStateError(
            f"{folder.name}: missing evidence: {', '.join(missing)}"
        )

    summary = _render_summary(folder, state)
    run_state.write_evidence(folder, "14-evidence-summary.md", summary)
    run_state.write_evidence(
        folder,
        "traceability.md",
        _render_traceability(change_id),
    )
    run_state.write_evidence(
        folder,
        "factory-run.json",
        json.dumps(state, indent=2) + "\n",
    )

    state = run_state.load_state(change_id, runs_dir)
    run_state.transition(
        state,
        run_state.AWAITING_RELEASE_DECISION,
        "evidence consolidated, waiting for a release decision",
    )
    run_state.save_state(change_id, state, runs_dir)
    run_state.write_evidence(
        folder,
        "factory-run.json",
        json.dumps(state, indent=2) + "\n",
    )
    return EvidenceResult(change_id, run_state.AWAITING_RELEASE_DECISION)


def _render_summary(folder: Path, state: dict) -> str:
    lines = [
        "# Evidence Summary",
        "",
        f"- Change: `{state['change_id']}`",
        f"- Status: `{state['status']}`",
        f"- Verification: `{state['verification']}`",
        f"- Iterations: `{state['iterations']}`",
        "",
        "## Produced evidence",
    ]
    for filename in (
        "00-change-request.md",
        "03-implementation-plan.md",
        "07-verification.txt",
        "08-review-report.md",
        "09-security-report.md",
        "11-semgrep.txt",
        "12-pip-audit.txt",
        "13-secret-scan.txt",
        "10-human-review-decisions.json",
    ):
        path = folder / filename
        lines.append(f"- {'present' if path.is_file() else 'missing'}: `{filename}`")
    return "\n".join(lines) + "\n"


def _render_traceability(change_id: str) -> str:
    return (
        "# Traceability\n\n"
        "| AC / Task | Implementation | Test / Evidence | Finding / Decision |\n"
        "|---|---|---|---|\n"
        f"| {change_id} acceptance criteria | `03-implementation-plan.md` | "
        f"`07-verification.txt`, `tests/` | `08-review-report.md`, "
        f"`09-security-report.md`, `10-human-review-decisions.json` |\n"
    )
