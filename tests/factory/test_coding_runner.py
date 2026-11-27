"""Tests for the implementation runner: gate, bounded fix loop and resume. Every side
effect is a fake (agents, verifier, branch, diff): no model calls, no git mutations."""

import pytest

from factory_app import run_state
from factory_app.coding_runner import MAX_FIX_ATTEMPTS, run_coding

PLAN = "# Plan\n1. Add a waitlist to CampusFlowService"
CR_TEXT = "# CR-001 - Event Waitlist"
CODER_REPORT = "CODER REPORT\n- campusflow/service.py: promote first waiting user"
TEST_REPORT = "TEST ANALYST REPORT\n- tests/test_waitlist.py added"
FAILURE_OUTPUT = "FAILED tests/test_waitlist.py::test_promotes_first_waiting"

GATE_OK = {
    "ok": True,
    "results": [
        {"command": "python -m pytest -q", "returncode": 0, "stdout": "5 passed", "stderr": ""}
    ],
}
GATE_FAIL = {
    "ok": False,
    "results": [
        {"command": "python -m pytest -q", "returncode": 1, "stdout": "", "stderr": FAILURE_OUTPUT}
    ],
}


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


class FakeVerifier:
    """Deterministic gate fake: returns each outcome once, then repeats the last one."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        ok = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        return GATE_OK if ok else GATE_FAIL


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


@pytest.fixture
def branch_calls():
    return []


@pytest.fixture
def fake_branch(branch_calls):
    def _branch(change_id):
        branch_calls.append(change_id)
        return {"ok": True, "branch": f"cr/{change_id}", "created": True}

    return _branch


def fake_diff():
    return {
        "ok": True,
        "status": " M campusflow/service.py",
        "diff": "diff --git a/campusflow/service.py b/campusflow/service.py\n+WAITLIST = True",
    }


@pytest.fixture
def start_approved_run(runs_dir, tmp_path):
    def _start(change_id="CR-001"):
        source = tmp_path / f"{change_id}.md"
        source.write_text(CR_TEXT, encoding="utf-8")
        run_state.create_run(change_id, source, runs_dir)
        folder = run_state.run_folder(change_id, runs_dir)
        (folder / "03-implementation-plan.md").write_text(PLAN, encoding="utf-8")

        state = run_state.load_state(change_id, runs_dir)
        run_state.transition(state, run_state.AWAITING_PLAN_APPROVAL, "test setup")
        run_state.save_state(change_id, state, runs_dir)
        run_state.record_decision(
            change_id,
            "plan",
            "APPROVED",
            "Plan reviewed: SQLite migration and atomic promote are in scope",
            decided_by="Rafa",
            role="tech_lead",
            runs_dir=runs_dir,
        )
        return change_id

    return _start


def _run(change_id, coder, tester, runs_dir, *, verifier=None, branch_fn=None):
    return run_coding(
        change_id,
        coder,
        tester,
        runs_dir,
        branch_fn=branch_fn or (lambda cid: {"ok": True, "branch": f"cr/{cid}"}),
        verifier=verifier or FakeVerifier([True]),
        diff_fn=fake_diff,
    )


def status_of(change_id, runs_dir):
    return run_state.load_state(change_id, runs_dir)["status"]


# --- gates and preconditions --------------------------------------------------------


def test_coding_is_blocked_until_the_plan_is_approved(runs_dir, tmp_path, branch_calls):
    source = tmp_path / "CR-001.md"
    source.write_text(CR_TEXT, encoding="utf-8")
    run_state.create_run("CR-001", source, runs_dir)
    coder = FakeAgent(CODER_REPORT)

    with pytest.raises(run_state.GateNotApprovedError):
        run_coding(
            "CR-001",
            coder,
            FakeAgent(TEST_REPORT),
            runs_dir,
            branch_fn=lambda cid: branch_calls.append(cid) or {"ok": True},
            verifier=FakeVerifier([True]),
            diff_fn=fake_diff,
        )

    assert coder.calls == []  # not one line of code without the gate
    assert branch_calls == []  # nor even a branch switch
    assert not (runs_dir / "CR-001" / "05-coder-report.md").exists()


def test_wrong_status_is_refused_even_with_an_approved_gate(start_approved_run, runs_dir):
    change_id = start_approved_run()
    state = run_state.load_state(change_id, runs_dir)
    run_state.transition(state, run_state.INTAKE_COMPLETE, "test setup")
    run_state.save_state(change_id, state, runs_dir)

    with pytest.raises(run_state.RunStateError, match="INTAKE_COMPLETE"):
        _run(change_id, FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT), runs_dir)


def test_missing_plan_file_is_reported_not_invented(start_approved_run, runs_dir):
    change_id = start_approved_run()
    (runs_dir / change_id / "03-implementation-plan.md").unlink()

    with pytest.raises(run_state.RunStateError, match="03-implementation-plan.md"):
        _run(change_id, FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT), runs_dir)


# --- happy path ---------------------------------------------------------------------


def test_approved_change_reaches_verification_passed(start_approved_run, runs_dir):
    change_id = start_approved_run()

    result = _run(change_id, FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT), runs_dir)

    assert result.status == run_state.VERIFICATION_PASSED
    assert result.attempts == 1
    state = run_state.load_state(change_id, runs_dir)
    assert state["status"] == run_state.VERIFICATION_PASSED
    assert state["verification"] == "PASS"
    assert state["iterations"] == 0


def test_evidence_files_are_written(
    start_approved_run, runs_dir, fake_branch, branch_calls
):
    change_id = start_approved_run()

    _run(
        change_id,
        FakeAgent(CODER_REPORT),
        FakeAgent(TEST_REPORT),
        runs_dir,
        branch_fn=fake_branch,
    )

    folder = runs_dir / change_id
    assert (folder / "05-coder-report.md").read_text(encoding="utf-8") == CODER_REPORT
    assert (folder / "06-test-analysis.md").read_text(encoding="utf-8") == TEST_REPORT
    verification = (folder / "07-verification.txt").read_text(encoding="utf-8")
    assert verification.startswith("VERIFICATION: PASS")
    assert branch_calls == [change_id]


def test_agents_receive_scoped_context_not_the_whole_repository(
    start_approved_run, runs_dir
):
    change_id = start_approved_run()
    coder, tester = FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT)

    _run(change_id, coder, tester, runs_dir)

    coder_prompt, coder_state = coder.calls[0]
    assert CR_TEXT in coder_prompt
    assert "+WAITLIST = True" in coder_prompt  # the bounded diff
    assert coder_state == {"implementation_plan": PLAN}
    assert "factory_app" not in coder_prompt
    assert "REQUIREMENTS.md" not in coder_prompt  # context engineering: no repo dump

    tester_prompt, tester_state = tester.calls[0]
    assert CR_TEXT in tester_prompt
    assert tester_state == {"implementation_plan": PLAN, "coder_report": CODER_REPORT}


# --- bounded fix loop ----------------------------------------------------------------


def test_failed_verification_returns_the_error_to_the_coder(start_approved_run, runs_dir):
    change_id = start_approved_run()
    verifier = FakeVerifier([False, False, True])  # two failures, then green
    coder = FakeAgent(CODER_REPORT)

    result = _run(
        change_id, coder, FakeAgent(TEST_REPORT), runs_dir, verifier=verifier
    )

    assert result.status == run_state.VERIFICATION_PASSED
    assert result.attempts == 3  # initial attempt + two fixes
    state = run_state.load_state(change_id, runs_dir)
    assert state["iterations"] == 2
    assert state["verification"] == "PASS"

    # the first attempt has no failure block; the fixes really see the red output
    assert FAILURE_OUTPUT not in coder.calls[0][0]
    assert FAILURE_OUTPUT in coder.calls[1][0]
    assert "Do not weaken tests" in coder.calls[1][0]
    assert FAILURE_OUTPUT in coder.calls[2][0]

    history = [entry["note"] for entry in run_state.load_state(change_id, runs_dir)["history"]]
    assert sum("verification failed" in note for note in history) == 2


def test_reports_and_verification_are_archived_per_attempt(start_approved_run, runs_dir):
    change_id = start_approved_run()

    _run(
        change_id,
        FakeAgent(CODER_REPORT),
        FakeAgent(TEST_REPORT),
        runs_dir,
        verifier=FakeVerifier([False, False, True]),
    )

    folder = runs_dir / change_id
    assert (folder / "05-coder-report.md").is_file()
    assert (folder / "05-coder-report.attempt-1.md").is_file()
    assert (folder / "05-coder-report.attempt-2.md").is_file()
    assert (folder / "07-verification.attempt-1.txt").is_file()


def test_runner_stops_when_fix_attempts_are_exhausted(start_approved_run, runs_dir):
    change_id = start_approved_run()
    verifier = FakeVerifier([False])  # always red
    coder = FakeAgent(CODER_REPORT)

    result = _run(
        change_id, coder, FakeAgent(TEST_REPORT), runs_dir, verifier=verifier
    )

    assert result.status == run_state.VERIFICATION_FAILED
    assert verifier.calls == MAX_FIX_ATTEMPTS + 1  # initial attempt + 2 retries
    assert len(coder.calls) == MAX_FIX_ATTEMPTS + 1
    state = run_state.load_state(change_id, runs_dir)
    assert state["status"] == run_state.VERIFICATION_FAILED
    assert state["verification"] == "FAIL"
    assert state["iterations"] == MAX_FIX_ATTEMPTS + 1


def test_resuming_after_human_intervention_starts_a_new_batch(
    start_approved_run, runs_dir, fake_branch
):
    change_id = start_approved_run()
    _run(
        change_id,
        FakeAgent(CODER_REPORT),
        FakeAgent(TEST_REPORT),
        runs_dir,
        verifier=FakeVerifier([False]),
    )
    assert status_of(change_id, runs_dir) == run_state.VERIFICATION_FAILED

    # A human intervenes and invokes the runner again: the exhausted counter must not
    # block the new cycle (that was the bug this test protects against).
    fresh_coder = FakeAgent(CODER_REPORT)
    result = _run(
        change_id,
        fresh_coder,
        FakeAgent(TEST_REPORT),
        runs_dir,
        branch_fn=fake_branch,
        verifier=FakeVerifier([True]),
    )

    assert result.status == run_state.VERIFICATION_PASSED
    assert result.attempts == 1  # a full new batch of retries is available
    assert len(fresh_coder.calls) == 1
    state = run_state.load_state(change_id, runs_dir)
    assert state["iterations"] == 0
    history = [entry["note"] for entry in state["history"]]
    assert "resumed: fix batch reset to 0" in history


def test_a_new_batch_really_can_retry_twice_again(start_approved_run, runs_dir):
    change_id = start_approved_run()
    _run(
        change_id,
        FakeAgent(CODER_REPORT),
        FakeAgent(TEST_REPORT),
        runs_dir,
        verifier=FakeVerifier([False]),
    )

    verifier = FakeVerifier([False])
    result = _run(
        change_id, FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT), runs_dir, verifier=verifier
    )

    assert result.status == run_state.VERIFICATION_FAILED
    assert verifier.calls == MAX_FIX_ATTEMPTS + 1  # retries were reset, not inherited


# --- the factory never decides for a human -------------------------------------------


def test_no_agent_state_is_ever_approved_or_merged_by_the_runner(
    start_approved_run, runs_dir
):
    change_id = start_approved_run()

    _run(change_id, FakeAgent(CODER_REPORT), FakeAgent(TEST_REPORT), runs_dir)

    state = run_state.load_state(change_id, runs_dir)
    assert state["human_gates"] == {
        "requirements": "PENDING",
        "plan": "APPROVED",
        "review": "PENDING",
        "release": "PENDING",
    }
    # The runner tops out at VERIFICATION_PASSED: release/merge belongs to a human.
    assert state["status"] == run_state.VERIFICATION_PASSED
    folder = runs_dir / change_id
    assert not (folder / "15-release-decision.json").exists()
