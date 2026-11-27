import json

import pytest

from factory_app import evidence_runner, run_state


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


def create_evidence_ready_run(runs_dir, tmp_path):
    source = tmp_path / "CR-001.md"
    source.write_text("# CR-001\nWaitlist", encoding="utf-8")
    run_state.create_run("CR-001", source, runs_dir)
    folder = run_state.run_folder("CR-001", runs_dir)
    for filename, content in (
        ("03-implementation-plan.md", "# Plan"),
        ("07-verification.txt", "VERIFICATION: PASS"),
        ("08-review-report.md", "review"),
        ("09-security-report.md", "security"),
    ):
        (folder / filename).write_text(content, encoding="utf-8")
    state = run_state.load_state("CR-001", runs_dir)
    state["verification"] = "PASS"
    run_state.transition(state, run_state.EVIDENCE_CONSOLIDATED, "review accepted")
    run_state.save_state("CR-001", state, runs_dir)


def test_evidence_runner_requires_evidence_consolidated(runs_dir, tmp_path):
    source = tmp_path / "CR-001.md"
    source.write_text("# CR-001", encoding="utf-8")
    run_state.create_run("CR-001", source, runs_dir)

    with pytest.raises(run_state.RunStateError, match="EVIDENCE_CONSOLIDATED"):
        evidence_runner.run_evidence("CR-001", runs_dir)


def test_evidence_runner_writes_artifacts_and_opens_release(runs_dir, tmp_path):
    create_evidence_ready_run(runs_dir, tmp_path)

    result = evidence_runner.run_evidence("CR-001", runs_dir)

    assert result.status == run_state.AWAITING_RELEASE_DECISION
    folder = run_state.run_folder("CR-001", runs_dir)
    assert (folder / "14-evidence-summary.md").is_file()
    assert (folder / "traceability.md").is_file()
    factory_run = json.loads((folder / "factory-run.json").read_text(encoding="utf-8"))
    assert factory_run["status"] == run_state.AWAITING_RELEASE_DECISION
    assert factory_run["verification"] == "PASS"
