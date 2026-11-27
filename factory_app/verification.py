"""Deterministic verification gate: pytest + ruff, no model in the loop.

LLM output is not verification, so this module runs the allowlisted commands itself and
returns their raw output. The coding runner writes that output to ``07-verification.txt``
and only a green gate can move the run to VERIFICATION_PASSED.

Commands use ``sys.executable -m ...`` so they run in the exact interpreter/venv of the
process that started the factory (equivalent to ``uv run pytest -q`` / ``uv run ruff ...``
without letting a nested invocation re-sync the environment). They are plain functions, not
ADK tools: no agent can invoke, skip or weaken them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MAX_FIX_ATTEMPTS = 2  # retries given to the Coder after a failed verification
COMMAND_TIMEOUT = 300

COMMANDS = (
    [sys.executable, "-m", "pytest", "-q"],
    [sys.executable, "-m", "ruff", "check", "campusflow", "tests", "factory_app", "scripts"],
)


def run_verification_gate(repo_root: Path = REPO_ROOT) -> dict:
    """Run the deterministic commands under ``repo_root``. Returns the raw evidence."""
    results = []
    all_ok = True
    for command in COMMANDS:
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                text=True,
                capture_output=True,
                timeout=COMMAND_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            all_ok = False
            results.append({
                "command": " ".join(command),
                "returncode": -1,
                "stdout": "",
                "stderr": str(error),
            })
            continue
        all_ok = all_ok and completed.returncode == 0
        results.append({
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-3000:],
        })
    return {"ok": all_ok, "results": results}


def render_verification(result: dict) -> str:
    """Human-readable evidence file (``07-verification.txt``)."""
    lines = [f"VERIFICATION: {'PASS' if result.get('ok') else 'FAIL'}", ""]
    for entry in result.get("results", []):
        lines.append(f"$ {entry['command']}")
        lines.append(f"exit code: {entry['returncode']}")
        stdout = (entry.get("stdout") or "").rstrip()
        stderr = (entry.get("stderr") or "").rstrip()
        if stdout:
            lines.append(stdout)
        if stderr:
            lines.append(stderr)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
