"""Tests for the run state machine and the human gates (no LLM involved)."""

import json

import pytest

from factory_app import run_state
from factory_app.run_state import (
    AWAITING_PLAN_APPROVAL,
    GateError,
    GateNotApprovedError,
    RunAlreadyExistsError,
    RunNotFoundError,
)


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


@pytest.fixture
def change_request(tmp_path):
    path = tmp_path / "CR-001-waitlist.md"
    path.write_text("# CR-001 - Event Waitlist", encoding="utf-8")
    return path


@pytest.fixture
def run(runs_dir, change_request):
    run_state.create_run("CR-001", change_request, runs_dir)
    return "CR-001"


def move_to_plan_approval(change_id, runs_dir):
    """Put a run in the state the planning runner leaves it in."""
    state = run_state.load_state(change_id, runs_dir)
    run_state.transition(state, AWAITING_PLAN_APPROVAL, "test setup")
    run_state.save_state(change_id, state, runs_dir)


def decide_plan(change_id, runs_dir, decision="APPROVED", **overrides):
    arguments = {
        "decision": decision,
        "reason": "Plan reviewed",
        "decided_by": "Rafa",
        "role": "tech_lead",
    }
    arguments.update(overrides)
    return run_state.record_decision(change_id, "plan", runs_dir=runs_dir, **arguments)


# --- creating a run --------------------------------------------------------------


def test_new_run_starts_with_every_gate_pending(run, runs_dir):
    state = run_state.load_state(run, runs_dir)

    assert state["status"] == run_state.INTAKE_PENDING
    assert set(state["human_gates"].values()) == {"PENDING"}


def test_new_run_keeps_a_copy_of_the_change_request(run, runs_dir):
    copy = runs_dir / run / "00-change-request.md"

    assert copy.read_text(encoding="utf-8") == "# CR-001 - Event Waitlist"


def test_creating_the_same_run_twice_is_refused(run, runs_dir, change_request):
    with pytest.raises(RunAlreadyExistsError):
        run_state.create_run(run, change_request, runs_dir)


def test_loading_an_unknown_run_fails(runs_dir):
    with pytest.raises(RunNotFoundError):
        run_state.load_state("CR-999", runs_dir)


# --- the guard that blocks later stages -----------------------------------------------


def test_guard_blocks_while_the_gate_is_pending(run, runs_dir):
    with pytest.raises(GateNotApprovedError, match="PENDING"):
        run_state.require_gate_approved(run, "plan", runs_dir)


def test_guard_passes_once_a_human_approved_the_plan(run, runs_dir):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, "APPROVED")

    run_state.require_gate_approved(run, "plan", runs_dir)  # must not raise


@pytest.mark.parametrize("decision", ["MODIFIED", "REJECTED", "DEFERRED"])
def test_guard_stays_closed_for_any_decision_other_than_approved(run, runs_dir, decision):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, decision)

    with pytest.raises(GateNotApprovedError):
        run_state.require_gate_approved(run, "plan", runs_dir)


# --- recording a human decision ---------------------------------------------------


def test_decision_is_saved_as_evidence_with_who_and_why(run, runs_dir):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, "APPROVED", reason="Scope is correct", decided_by="Rafa")

    evidence = json.loads(
        (runs_dir / run / "04-human-plan-approval.json").read_text(encoding="utf-8")
    )
    assert evidence["decision"] == "APPROVED"
    assert evidence["reason"] == "Scope is correct"
    assert evidence["decided_by"] == "Rafa"
    assert evidence["role"] == "tech_lead"
    assert evidence["recorded_at"]


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ("APPROVED", run_state.PLAN_APPROVED),
        ("MODIFIED", run_state.PLAN_CHANGES_REQUESTED),
        ("REJECTED", run_state.PLAN_REJECTED),
        ("DEFERRED", AWAITING_PLAN_APPROVAL),
    ],
)
def test_plan_decision_moves_the_run_to_the_matching_status(
    run, runs_dir, decision, expected_status
):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, decision)

    assert run_state.load_state(run, runs_dir)["status"] == expected_status


def test_plan_cannot_be_decided_before_a_plan_exists(run, runs_dir):
    # The run is still INTAKE_PENDING: there is nothing to approve yet.
    with pytest.raises(GateError, match="AWAITING_PLAN_APPROVAL"):
        decide_plan(run, runs_dir)


def test_an_approved_plan_cannot_be_decided_again(run, runs_dir):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, "APPROVED")

    with pytest.raises(GateError):
        decide_plan(run, runs_dir, "REJECTED")


def test_a_deferred_plan_can_be_decided_later(run, runs_dir):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, "DEFERRED")

    decide_plan(run, runs_dir, "APPROVED")

    run_state.require_gate_approved(run, "plan", runs_dir)


def test_decision_needs_a_reason_and_a_name(run, runs_dir):
    move_to_plan_approval(run, runs_dir)

    with pytest.raises(GateError, match="reason"):
        decide_plan(run, runs_dir, reason="  ")
    with pytest.raises(GateError, match="decided_by"):
        decide_plan(run, runs_dir, decided_by="")


def test_only_the_roles_that_own_a_gate_can_decide_it(run, runs_dir):
    move_to_plan_approval(run, runs_dir)

    with pytest.raises(GateError, match="role"):
        decide_plan(run, runs_dir, role="release_manager")


def test_unknown_decisions_and_gates_are_refused(run, runs_dir):
    move_to_plan_approval(run, runs_dir)

    with pytest.raises(GateError, match="decision"):
        decide_plan(run, runs_dir, decision="MAYBE")
    with pytest.raises(GateError, match="gate"):
        run_state.record_decision(
            run,
            "coffee",
            "APPROVED",
            "ok",
            decided_by="Rafa",
            role="tech_lead",
            runs_dir=runs_dir,
        )


def test_review_and_release_gates_require_their_actual_status(run, runs_dir):
    with pytest.raises(GateError, match="AWAITING_REVIEW_DECISIONS"):
        run_state.record_decision(
            run,
            "review",
            "APPROVED",
            "reviewed",
            decided_by="Ana",
            role="reviewer",
            runs_dir=runs_dir,
        )


def test_review_gate_accepts_only_reviewer_and_moves_to_evidence(run, runs_dir):
    state = run_state.load_state(run, runs_dir)
    run_state.transition(state, run_state.AWAITING_REVIEW_DECISIONS, "test setup")
    run_state.save_state(run, state, runs_dir)

    run_state.record_decision(
        run,
        "review",
        "APPROVED",
        "review complete",
        decided_by="Ana",
        role="reviewer",
        runs_dir=runs_dir,
    )

    state = run_state.load_state(run, runs_dir)
    assert state["status"] == run_state.EVIDENCE_CONSOLIDATED
    evidence = json.loads(
        (runs_dir / run / "10-human-review-decisions.json").read_text(encoding="utf-8")
    )
    assert evidence["role"] == "reviewer"


def test_release_gate_accepts_only_release_manager_and_tops_at_merge_ready(run, runs_dir):
    state = run_state.load_state(run, runs_dir)
    run_state.transition(state, run_state.AWAITING_RELEASE_DECISION, "test setup")
    run_state.save_state(run, state, runs_dir)

    run_state.record_decision(
        run,
        "release",
        "APPROVED",
        "release complete",
        decided_by="Luis",
        role="release_manager",
        runs_dir=runs_dir,
    )

    state = run_state.load_state(run, runs_dir)
    assert state["status"] == run_state.READY_FOR_HUMAN_MERGE
    evidence = json.loads(
        (runs_dir / run / "15-release-decision.json").read_text(encoding="utf-8")
    )
    assert evidence["role"] == "release_manager"

    with pytest.raises(GateError, match="AWAITING_RELEASE_DECISION"):
        run_state.record_decision(
            run,
            "release",
            "APPROVED",
            "release checked",
            decided_by="Luis",
            role="release_manager",
            runs_dir=runs_dir,
        )


# --- audit trail ------------------------------------------------------------------


def test_every_status_change_is_kept_in_the_history(run, runs_dir):
    move_to_plan_approval(run, runs_dir)
    decide_plan(run, runs_dir, "APPROVED")

    history = run_state.load_state(run, runs_dir)["history"]

    assert [entry["to"] for entry in history] == [
        run_state.INTAKE_PENDING,
        AWAITING_PLAN_APPROVAL,
        run_state.PLAN_APPROVED,
    ]
