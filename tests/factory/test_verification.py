"""Tests for the deterministic verification gate. Each case runs the real commands against
a minimal project under tmp_path, never against the repository being tested."""

from factory_app import verification


def _mini_project(root, *, failing: bool):
    for name in ("campusflow", "tests", "factory_app", "scripts"):
        (root / name).mkdir()
        (root / name / "module.py").write_text("X = 1\n", encoding="utf-8")
    (root / "tests" / "test_sample.py").write_text(
        "def test_green():\n    assert True\n" if not failing else
        "def test_red():\n    assert False\n",
        encoding="utf-8",
    )
    return root


def test_the_fix_budget_is_the_two_retries_of_the_specification():
    assert verification.MAX_FIX_ATTEMPTS == 2


def test_gate_passes_on_a_green_project(tmp_path):
    project = _mini_project(tmp_path, failing=False)

    result = verification.run_verification_gate(project)

    assert result["ok"] is True
    assert [entry["returncode"] for entry in result["results"]] == [0, 0]
    assert verification.render_verification(result).startswith("VERIFICATION: PASS")


def test_gate_fails_and_keeps_the_raw_evidence_on_a_red_project(tmp_path):
    project = _mini_project(tmp_path, failing=True)

    result = verification.run_verification_gate(project)

    assert result["ok"] is False
    rendered = verification.render_verification(result)
    assert rendered.startswith("VERIFICATION: FAIL")
    assert "test_red" in rendered  # the failure reaches the Coder through the evidence
    assert result["results"][0]["returncode"] != 0


def test_render_names_every_command_it_ran(tmp_path):
    project = _mini_project(tmp_path, failing=False)

    rendered = verification.render_verification(verification.run_verification_gate(project))

    assert "python" in rendered and "pytest" in rendered
    assert "ruff" in rendered
