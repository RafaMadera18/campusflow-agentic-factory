"""Independent Reviewer + Security stage after deterministic verification."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import run_state

AgentFn = Callable[[str, dict], str]
RunnerFn = Callable[..., dict]

ROOT = Path(__file__).resolve().parents[1]
SCANNER_TIMEOUT = 300


@dataclass(frozen=True)
class ReviewResult:
    change_id: str
    status: str


def run_review(
    change_id: str,
    reviewer: AgentFn,
    security: AgentFn,
    runs_dir: Path = run_state.RUNS_DIR,
    *,
    scanner_runner: RunnerFn | None = None,
    diff_fn: Callable[[], str] | None = None,
) -> ReviewResult:
    """Run deterministic scanners and two independent read-only agents."""
    change_id = change_id.upper()
    state = run_state.load_state(change_id, runs_dir)
    if state["status"] != run_state.VERIFICATION_PASSED:
        raise run_state.RunStateError(
            f"{change_id} is {state['status']}. Review requires VERIFICATION_PASSED."
        )
    if state["verification"] != "PASS":
        raise run_state.RunStateError(f"{change_id}: verification evidence is not PASS.")

    folder = run_state.run_folder(change_id, runs_dir)
    required = (
        "00-change-request.md",
        "03-implementation-plan.md",
        "07-verification.txt",
    )
    for filename in required:
        if not (folder / filename).is_file():
            raise run_state.RunStateError(f"{folder.name}: missing {filename}")

    scanner_runner = scanner_runner or run_scanners
    scanner_results = scanner_runner(ROOT)
    for filename, content in scanner_results.items():
        run_state.write_evidence(folder, filename, content)

    diff = (diff_fn or _git_diff_text)()
    change_request = (folder / "00-change-request.md").read_text(encoding="utf-8")
    plan = (folder / "03-implementation-plan.md").read_text(encoding="utf-8")
    verification = (folder / "07-verification.txt").read_text(encoding="utf-8")

    reviewer_prompt = _review_prompt(
        "Software Review",
        change_request,
        plan,
        diff,
        verification,
    )
    review_report = reviewer(reviewer_prompt, {})
    run_state.write_evidence(folder, "08-review-report.md", review_report)

    security_prompt = _review_prompt(
        "Security Review",
        change_request,
        plan,
        diff,
        verification,
        include_scanners=scanner_results,
    )
    security_report = security(security_prompt, {})
    run_state.write_evidence(folder, "09-security-report.md", security_report)

    state = run_state.load_state(change_id, runs_dir)
    run_state.transition(
        state,
        run_state.AWAITING_REVIEW_DECISIONS,
        "independent review and security evidence produced",
    )
    run_state.save_state(change_id, state, runs_dir)
    return ReviewResult(change_id, run_state.AWAITING_REVIEW_DECISIONS)


def run_scanners(repo_root: Path = ROOT) -> dict[str, str]:
    """Run available deterministic scanners; missing tools are explicit SKIPPED evidence."""
    return {
        "11-semgrep.txt": _run_scanner(
            repo_root,
            "semgrep",
            ["semgrep", "scan", "--config", "auto", "--json"],
        ),
        "12-pip-audit.txt": _run_scanner(
            repo_root,
            "pip-audit",
            ["pip-audit", "--format", "json", "--progress-spinner", "off"],
        ),
        "13-secret-scan.txt": _secret_scan(repo_root),
    }


def _run_scanner(repo_root: Path, executable: str, command: list[str]) -> str:
    if shutil.which(executable) is None:
        return f"SCANNER: SKIPPED\nTool: {executable}\nReason: executable not available\n"
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=SCANNER_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"SCANNER: SKIPPED\nTool: {executable}\nReason: {error}\n"
    return (
        f"SCANNER: {'PASS' if completed.returncode == 0 else 'FAIL'}\n"
        f"Tool: {executable}\n"
        f"Exit code: {completed.returncode}\n\n"
        f"{completed.stdout.rstrip()}\n"
        f"{completed.stderr.rstrip()}\n"
    )


def _secret_scan(repo_root: Path) -> str:
    command = [
        "git",
        "grep",
        "-nE",
        "(GOOGLE_API_KEY|GEMINI_API_KEY|API_KEY[[:space:]]*=|BEGIN .*PRIVATE KEY)",
        "--",
        "*.py",
        "*.toml",
        "*.json",
        "*.md",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"SECRET SCAN: SKIPPED\nReason: {error}\n"
    if completed.returncode == 1:
        return "SECRET SCAN: PASS\nNo known secret patterns found in tracked text files.\n"
    if completed.returncode != 0:
        return f"SECRET SCAN: SKIPPED\nReason: git grep failed\n{completed.stderr}\n"
    return f"SECRET SCAN: FAIL\nPotential secret patterns:\n{completed.stdout}\n"


def _git_diff_text() -> str:
    completed = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return "git diff unavailable"
    return completed.stdout[:40_000] or "(empty diff)"


def _review_prompt(
    role: str,
    change_request: str,
    plan: str,
    diff: str,
    verification: str,
    *,
    include_scanners: dict[str, str] | None = None,
) -> str:
    contract_files = []
    for name in ("docs/REQUIREMENTS.md", "docs/SPEC.md", "docs/ARCHITECTURE.md"):
        path = ROOT / name
        if path.is_file():
            contract_files.append(
                f"<{name}>\n{path.read_text(encoding='utf-8')[:40_000]}\n</{name}>"
            )
    prompt = (
        f"Perform a {role} of the Change Request using only the evidence below.\n\n"
        + "\n\n".join(contract_files)
        + "\n\n"
        "<change_request>\n"
        f"{change_request.strip()}\n"
        "</change_request>\n\n"
        "<implementation_plan>\n"
        f"{plan.strip()}\n"
        "</implementation_plan>\n\n"
        "<git_diff>\n"
        f"{diff}\n"
        "</git_diff>\n\n"
        "<verification>\n"
        f"{verification.strip()}\n"
        "</verification>\n"
    )
    if include_scanners:
        prompt += "\n<scanner_evidence>\n"
        for filename, content in include_scanners.items():
            prompt += f"{filename}:\n{content.strip()}\n\n"
        prompt += "</scanner_evidence>\n"
    prompt += (
        "\nClassify findings by severity, cite evidence, and do not modify code."
    )
    return prompt
