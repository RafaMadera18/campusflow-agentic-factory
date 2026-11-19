"""Tests for the Intake -> Planner runner. Agents are replaced by fakes: no API calls."""

import pytest

from factory_app import run_state
from factory_app.planning_runner import RunStateError, parse_recommendation, run_planning
from factory_app.prompts import INTAKE_INSTRUCTION

PROCEED_REPORT = "Intake looks fine.\nRECOMMENDATION: PROCEED"
STOP_REPORT = (
    "The request does not say who gets priority.\nRECOMMENDATION: HUMAN_CLARIFICATION_REQUIRED"
)
PLAN = "# Plan\n1. Change service.py"


class FakeAgent:
    """Stands in for an LLM agent: records every call and returns a fixed answer."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []  # list of (prompt, session_state)

    def __call__(self, prompt, state):
        self.calls.append((prompt, state))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


@pytest.fixture
def start_run(runs_dir, tmp_path):
    def _start(change_id="CR-001", text="Waitlist when the event is full."):
        source = tmp_path / f"{change_id}.md"
        source.write_text(text, encoding="utf-8")
        run_state.create_run(change_id, source, runs_dir)
        return change_id

    return _start


def status_of(change_id, runs_dir):
    return run_state.load_state(change_id, runs_dir)["status"]


# --- reading the intake recommendation -------------------------------------------


def test_recommendation_is_read_from_the_last_marker_line():
    assert parse_recommendation(PROCEED_REPORT) == "PROCEED"
    assert parse_recommendation(STOP_REPORT) == "HUMAN_CLARIFICATION_REQUIRED"


def test_missing_recommendation_fails_closed():
    # If the agent forgets the marker we must stop, never assume PROCEED.
    assert parse_recommendation("Looks good to me!") == "HUMAN_CLARIFICATION_REQUIRED"
    assert parse_recommendation("") == "HUMAN_CLARIFICATION_REQUIRED"


def test_intake_instruction_asks_for_the_marker_the_runner_reads():
    # If someone rewords the prompt, the runner and the agent must keep speaking the same language.
    assert "RECOMMENDATION: PROCEED" in INTAKE_INSTRUCTION
    assert "RECOMMENDATION: HUMAN_CLARIFICATION_REQUIRED" in INTAKE_INSTRUCTION


# --- happy path --------------------------------------------------------------------


def test_clear_change_request_ends_waiting_for_plan_approval(start_run, runs_dir):
    change_id = start_run()
    intake, planner = FakeAgent(PROCEED_REPORT), FakeAgent(PLAN)

    result = run_planning(change_id, intake, planner, runs_dir)

    assert result.status == run_state.AWAITING_PLAN_APPROVAL
    assert status_of(change_id, runs_dir) == run_state.AWAITING_PLAN_APPROVAL


def test_intake_report_and_plan_are_saved_as_evidence(start_run, runs_dir):
    change_id = start_run()

    run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)

    run_folder = runs_dir / change_id
    assert (run_folder / "01-intake-report.md").read_text(encoding="utf-8") == PROCEED_REPORT
    assert (run_folder / "03-implementation-plan.md").read_text(encoding="utf-8") == PLAN


def test_intake_receives_the_change_request_text(start_run, runs_dir):
    change_id = start_run(text="Waitlist when the event is full.")
    intake = FakeAgent(PROCEED_REPORT)

    run_planning(change_id, intake, FakeAgent(PLAN), runs_dir)

    prompt, _state = intake.calls[0]
    assert "Waitlist when the event is full." in prompt


def test_planner_gets_the_intake_report_in_its_own_session(start_run, runs_dir):
    # Each agent runs in a separate session: the planner only sees the saved report.
    change_id = start_run()
    planner = FakeAgent(PLAN)

    run_planning(change_id, FakeAgent(PROCEED_REPORT), planner, runs_dir)

    _prompt, state = planner.calls[0]
    assert state == {"intake_report": PROCEED_REPORT}


def test_the_plan_is_not_approved_by_the_runner(start_run, runs_dir):
    # The whole point of the gate: planning ends, the Coder stays blocked.
    change_id = start_run()

    run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)

    with pytest.raises(run_state.GateNotApprovedError):
        run_state.require_gate_approved(change_id, "plan", runs_dir)


# --- ambiguity: stop and ask a human ---------------------------------------------------


def test_ambiguous_change_request_stops_before_planning(start_run, runs_dir):
    change_id = start_run("CR-005", text="Some users should receive priority.")
    planner = FakeAgent(PLAN)

    result = run_planning(change_id, FakeAgent(STOP_REPORT), planner, runs_dir)

    assert result.status == run_state.AWAITING_CLARIFICATION
    assert planner.calls == []  # the planner never ran
    assert not (runs_dir / change_id / "03-implementation-plan.md").exists()
    assert (runs_dir / change_id / "01-intake-report.md").exists()


def test_after_the_product_owner_clarifies_intake_runs_again_with_the_answer(
    start_run, runs_dir
):
    change_id = start_run("CR-005", text="Some users should receive priority.")
    run_planning(change_id, FakeAgent(STOP_REPORT), FakeAgent(PLAN), runs_dir)
    run_state.record_decision(
        change_id,
        "requirements",
        "APPROVED",
        "STAFF has priority only inside the waitlist. FIFO inside each group.",
        decided_by="Rafa",
        role="product_owner",
        runs_dir=runs_dir,
    )
    second_intake = FakeAgent(PROCEED_REPORT)

    result = run_planning(change_id, second_intake, FakeAgent(PLAN), runs_dir)

    prompt, _state = second_intake.calls[0]
    assert "STAFF has priority only inside the waitlist" in prompt
    assert result.status == run_state.AWAITING_PLAN_APPROVAL


def test_the_first_intake_report_is_archived_not_overwritten(start_run, runs_dir):
    change_id = start_run("CR-005")
    run_planning(change_id, FakeAgent(STOP_REPORT), FakeAgent(PLAN), runs_dir)
    run_state.record_decision(
        change_id,
        "requirements",
        "APPROVED",
        "STAFF goes first.",
        decided_by="Rafa",
        role="product_owner",
        runs_dir=runs_dir,
    )

    run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)

    run_folder = runs_dir / change_id
    assert (run_folder / "01-intake-report.md").read_text(encoding="utf-8") == PROCEED_REPORT
    archived = run_folder / "01-intake-report.attempt-1.md"
    assert archived.read_text(encoding="utf-8") == STOP_REPORT


# --- failures and resume -------------------------------------------------------------


def test_planner_failure_keeps_the_intake_checkpoint(start_run, runs_dir):
    change_id = start_run()
    broken_planner = FakeAgent(RuntimeError("503 UNAVAILABLE"))

    with pytest.raises(RuntimeError):
        run_planning(change_id, FakeAgent(PROCEED_REPORT), broken_planner, runs_dir)

    assert status_of(change_id, runs_dir) == run_state.INTAKE_COMPLETE


def test_resume_after_a_failure_does_not_repeat_intake(start_run, runs_dir):
    change_id = start_run()
    with pytest.raises(RuntimeError):
        run_planning(
            change_id,
            FakeAgent(PROCEED_REPORT),
            FakeAgent(RuntimeError("429 RESOURCE_EXHAUSTED")),
            runs_dir,
        )
    intake_again = FakeAgent(PROCEED_REPORT)

    result = run_planning(change_id, intake_again, FakeAgent(PLAN), runs_dir)

    assert intake_again.calls == []  # saved quota: intake result was already checkpointed
    assert result.status == run_state.AWAITING_PLAN_APPROVAL


def test_intake_failure_leaves_the_run_ready_to_retry(start_run, runs_dir):
    change_id = start_run()

    with pytest.raises(RuntimeError):
        run_planning(change_id, FakeAgent(RuntimeError("boom")), FakeAgent(PLAN), runs_dir)

    assert status_of(change_id, runs_dir) == run_state.INTAKE_PENDING


# --- states where planning must not run ------------------------------------------------


def test_planning_cannot_run_twice_on_a_plan_waiting_for_approval(start_run, runs_dir):
    change_id = start_run()
    run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)

    with pytest.raises(RunStateError, match="AWAITING_PLAN_APPROVAL"):
        run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)


def test_planning_waits_while_clarification_is_pending(start_run, runs_dir):
    change_id = start_run("CR-005")
    run_planning(change_id, FakeAgent(STOP_REPORT), FakeAgent(PLAN), runs_dir)

    with pytest.raises(RunStateError, match="AWAITING_CLARIFICATION"):
        run_planning(change_id, FakeAgent(PROCEED_REPORT), FakeAgent(PLAN), runs_dir)
