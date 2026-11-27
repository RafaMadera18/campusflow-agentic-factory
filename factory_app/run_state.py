"""State of a factory run and its human gates.

Each run lives in ``runs/<CR-ID>/`` and its ``factory-state.json`` is the single source
of truth about where the run is. Two rules keep the factory honest:

* Only a recorded human decision can open a gate. Agents never approve anything.
* Any later stage (for example the Coder) must call ``require_gate_approved`` first and
  is refused while the gate is not APPROVED.

This module is plain Python on purpose: no LLM is involved in these checks.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
STATE_FILE = "factory-state.json"
CHANGE_REQUEST_FILE = "00-change-request.md"

# --- Run statuses (the order below follows a normal run) ------------------------------
INTAKE_PENDING = "INTAKE_PENDING"  # intake has to run (first time, or again after an answer)
AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"  # gate: Product Owner must clarify the CR
CR_REJECTED = "CR_REJECTED"  # the Product Owner rejected the Change Request
INTAKE_COMPLETE = "INTAKE_COMPLETE"  # checkpoint: intake said PROCEED, planning is pending
AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"  # gate: Tech Lead must decide on the plan
PLAN_APPROVED = "PLAN_APPROVED"  # the Coder may start
PLAN_CHANGES_REQUESTED = "PLAN_CHANGES_REQUESTED"
PLAN_REJECTED = "PLAN_REJECTED"

# --- Implementation slice (the coding runner moves between these) ---------------------
CODING_COMPLETE = "CODING_COMPLETE"  # Coder + Test Analyst finished one iteration
VERIFICATION_PASSED = "VERIFICATION_PASSED"  # deterministic gate is green; review comes next
VERIFICATION_FAILED = "VERIFICATION_FAILED"  # fix loop (<= MAX_FIX_ATTEMPTS) or stopped run

# --- Review and release slices ---------------------------------------------------------
AWAITING_REVIEW_DECISIONS = "AWAITING_REVIEW_DECISIONS"
EVIDENCE_CONSOLIDATED = "EVIDENCE_CONSOLIDATED"
AWAITING_RELEASE_DECISION = "AWAITING_RELEASE_DECISION"
READY_FOR_HUMAN_MERGE = "READY_FOR_HUMAN_MERGE"

# --- Human gates ---------------------------------------------------------------------
DECISIONS = ("APPROVED", "MODIFIED", "REJECTED", "DEFERRED")
ALL_GATES = ("requirements", "plan", "review", "release")


@dataclass(frozen=True)
class GateRule:
    """Who may decide a gate, when, where the evidence goes and what happens next."""

    required_status: str
    allowed_roles: tuple[str, ...]
    evidence_file: str
    status_after: dict[str, str]  # decision -> new status; a missing decision keeps the status


# Only the gates of the planning slice are wired. `review` and `release` come with the
# Reviewer/Security and release milestones; accepting them now would create fake evidence.
GATE_RULES = {
    "requirements": GateRule(
        required_status=AWAITING_CLARIFICATION,
        allowed_roles=("product_owner",),
        evidence_file="02-human-requirement-decision.json",
        status_after={
            "APPROVED": INTAKE_PENDING,  # clarified: intake runs again with the answer
            "MODIFIED": INTAKE_PENDING,
            "REJECTED": CR_REJECTED,
        },
    ),
    "plan": GateRule(
        required_status=AWAITING_PLAN_APPROVAL,
        allowed_roles=("tech_lead", "product_owner"),
        evidence_file="04-human-plan-approval.json",
        status_after={
            "APPROVED": PLAN_APPROVED,
            "MODIFIED": PLAN_CHANGES_REQUESTED,
            "REJECTED": PLAN_REJECTED,
        },
    ),
    "review": GateRule(
        required_status=AWAITING_REVIEW_DECISIONS,
        allowed_roles=("reviewer",),
        evidence_file="10-human-review-decisions.json",
        status_after={
            "APPROVED": EVIDENCE_CONSOLIDATED,
            "MODIFIED": CODING_COMPLETE,
            "REJECTED": CODING_COMPLETE,
            "DEFERRED": AWAITING_REVIEW_DECISIONS,
        },
    ),
    "release": GateRule(
        required_status=AWAITING_RELEASE_DECISION,
        allowed_roles=("release_manager",),
        evidence_file="15-release-decision.json",
        status_after={
            "APPROVED": READY_FOR_HUMAN_MERGE,
            "MODIFIED": AWAITING_RELEASE_DECISION,
            "REJECTED": AWAITING_RELEASE_DECISION,
            "DEFERRED": AWAITING_RELEASE_DECISION,
        },
    ),
}


# --- Errors --------------------------------------------------------------------------
class RunStateError(Exception):
    """Base class for every problem with a run's state."""


class RunNotFoundError(RunStateError):
    pass


class RunAlreadyExistsError(RunStateError):
    pass


class GateError(RunStateError):
    """A human decision could not be recorded."""


class GateNotApprovedError(RunStateError):
    """A stage tried to start while its gate is not APPROVED."""


# --- Reading and writing the state ----------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_folder(change_id: str, runs_dir: Path = RUNS_DIR) -> Path:
    return Path(runs_dir) / change_id.upper()


def new_state(change_id: str) -> dict:
    state = {
        "change_id": change_id,
        "created_at": _now(),
        "status": INTAKE_PENDING,
        "human_gates": {gate: "PENDING" for gate in ALL_GATES},
        "verification": "NOT_RUN",
        "review": "NOT_RUN",
        "security": "NOT_RUN",
        "iterations": 0,
        "history": [],
    }
    transition(state, INTAKE_PENDING, "run created")
    return state


def create_run(change_id: str, change_request: Path, runs_dir: Path = RUNS_DIR) -> Path:
    """Create ``runs/<CR-ID>/`` with a copy of the Change Request and a fresh state."""
    change_id = change_id.upper()
    folder = run_folder(change_id, runs_dir)
    if folder.exists():
        raise RunAlreadyExistsError(f"Run already exists: {folder}")
    folder.mkdir(parents=True)
    shutil.copy2(change_request, folder / CHANGE_REQUEST_FILE)
    save_state(change_id, new_state(change_id), runs_dir)
    return folder


def load_state(change_id: str, runs_dir: Path = RUNS_DIR) -> dict:
    path = run_folder(change_id, runs_dir) / STATE_FILE
    if not path.is_file():
        raise RunNotFoundError(f"Run not found: {change_id}")
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("history", [])  # runs created by the original starter have no history
    return state


def save_state(change_id: str, state: dict, runs_dir: Path = RUNS_DIR) -> None:
    path = run_folder(change_id, runs_dir) / STATE_FILE
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def transition(state: dict, new_status: str, note: str) -> None:
    """Change the status and leave a line in the audit trail."""
    state["status"] = new_status
    state["history"].append({"at": _now(), "to": new_status, "note": note})


def write_evidence(folder: Path, filename: str, content: str) -> Path:
    """Write an evidence file. An existing file is archived, never overwritten.

    ``01-intake-report.md`` becomes ``01-intake-report.attempt-1.md`` (then ``-2``...)
    so the history of what the agents said survives a re-run.
    """
    path = folder / filename
    if path.exists():
        path.rename(_next_archive_path(path))
    path.write_text(content, encoding="utf-8")
    return path


def _next_archive_path(path: Path) -> Path:
    attempt = 1
    while True:
        candidate = path.with_name(f"{path.stem}.attempt-{attempt}{path.suffix}")
        if not candidate.exists():
            return candidate
        attempt += 1


# --- Human gates ---------------------------------------------------------------------
def record_decision(
    change_id: str,
    gate: str,
    decision: str,
    reason: str,
    *,
    decided_by: str,
    role: str,
    runs_dir: Path = RUNS_DIR,
) -> Path:
    """Record a human decision on a gate and move the run accordingly.

    Returns the path of the evidence file. Raises ``GateError`` when the decision is not
    valid: unknown gate or decision, missing reason or name, a role that does not own the
    gate, or a run that is not waiting for this gate.
    """
    rule = _rule_for(gate)
    if decision not in DECISIONS:
        raise GateError(f"Invalid decision {decision!r}. Use one of {list(DECISIONS)}")
    if not reason.strip():
        raise GateError("A human decision needs a reason")
    if not decided_by.strip():
        raise GateError("decided_by (the person who decided) is required")
    if role not in rule.allowed_roles:
        raise GateError(
            f"gate {gate!r} cannot be decided by role {role!r}; allowed: {list(rule.allowed_roles)}"
        )

    state = load_state(change_id, runs_dir)
    if state["status"] != rule.required_status:
        raise GateError(
            f"gate {gate!r} can only be decided when the run is {rule.required_status} "
            f"(currently {state['status']})"
        )

    evidence = {
        "change_id": state["change_id"],
        "gate": gate,
        "decision": decision,
        "reason": reason.strip(),
        "decided_by": decided_by.strip(),
        "role": role,
        "recorded_at": _now(),
    }
    folder = run_folder(change_id, runs_dir)
    path = write_evidence(folder, rule.evidence_file, json.dumps(evidence, indent=2))

    state["human_gates"][gate] = decision
    new_status = rule.status_after.get(decision, state["status"])
    transition(state, new_status, f"{gate} gate: {decision} by {decided_by.strip()} ({role})")
    save_state(change_id, state, runs_dir)
    return path


def require_gate_approved(change_id: str, gate: str, runs_dir: Path = RUNS_DIR) -> None:
    """Guard for later stages: raise unless a human APPROVED this gate."""
    decision = load_state(change_id, runs_dir)["human_gates"].get(gate)
    if decision != "APPROVED":
        raise GateNotApprovedError(
            f"{change_id}: gate {gate!r} is {decision}, not APPROVED. "
            "A human must approve it before this stage can run."
        )


def _rule_for(gate: str) -> GateRule:
    if gate not in ALL_GATES:
        raise GateError(f"Unknown gate {gate!r}. Use one of {list(ALL_GATES)}")
    if gate not in GATE_RULES:
        raise GateError(f"gate {gate!r} is not available yet in this milestone")
    return GATE_RULES[gate]
