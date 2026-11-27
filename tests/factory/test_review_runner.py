import pytest

from factory_app import review_runner, run_state


class FakeAgent:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, prompt, state):
        self.calls.append((prompt, state))
        return self.answer


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


def create_verified_run(runs_dir, tmp_path):
    source = tmp_path / "CR-001.md"
    source.write_text("# CR-001\nWaitlist", encoding="utf-8")
    run_state.create_run("CR-001", source, runs_dir)
    folder = run_state.run_folder("CR-001", runs_dir)
    (folder / "03-implementation-plan.md").write_text("# Plan\nAdd waitlist", encoding="utf-8")
    (folder / "07-verification.txt").write_text("VERIFICATION: PASS\n", encoding="utf-8")
    state = run_state.load_state("CR-001", runs_dir)
    state["verification"] = "PASS"
    run_state.transition(state, run_state.VERIFICATION_PASSED, "verification passed")
    run_state.save_state("CR-001", state, runs_dir)


def fake_scanners(_repo_root):
    return {
        "11-semgrep.txt": "SCANNER: SKIPPED\n",
        "12-pip-audit.txt": "SCANNER: SKIPPED\n",
        "13-secret-scan.txt": "SECRET SCAN: PASS\n",
    }


def test_review_requires_verification_pass(runs_dir, tmp_path):
    source = tmp_path / "CR-002.md"
    source.write_text("# CR-002", encoding="utf-8")
    run_state.create_run("CR-002", source, runs_dir)

    with pytest.raises(run_state.RunStateError, match="VERIFICATION_PASSED"):
        review_runner.run_review(
            "CR-002",
            FakeAgent("review"),
            FakeAgent("security"),
            runs_dir,
            scanner_runner=fake_scanners,
            diff_fn=lambda: "diff",
        )


def test_review_runs_isolated_agents_and_moves_to_human_gate(runs_dir, tmp_path):
    create_verified_run(runs_dir, tmp_path)
    reviewer = FakeAgent("REVIEW REPORT")
    security = FakeAgent("SECURITY REPORT")

    result = review_runner.run_review(
        "CR-001",
        reviewer,
        security,
        runs_dir,
        scanner_runner=fake_scanners,
        diff_fn=lambda: "bounded diff",
    )

    assert result.status == run_state.AWAITING_REVIEW_DECISIONS
    state = run_state.load_state("CR-001", runs_dir)
    assert state["status"] == run_state.AWAITING_REVIEW_DECISIONS
    folder = run_state.run_folder("CR-001", runs_dir)
    assert (folder / "08-review-report.md").read_text(encoding="utf-8") == "REVIEW REPORT"
    assert (folder / "09-security-report.md").read_text(encoding="utf-8") == "SECURITY REPORT"
    assert (folder / "11-semgrep.txt").is_file()
    assert reviewer.calls[0][1] == {}
    assert security.calls[0][1] == {}
    assert "bounded diff" in reviewer.calls[0][0]
    assert "11-semgrep.txt" in security.calls[0][0]
