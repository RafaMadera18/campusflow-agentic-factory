from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
READABLE_ROOTS = {"docs", "change_requests", "campusflow", "tests", "runs"}
CODER_WRITE_ROOTS = {"campusflow", "tests"}
TESTER_WRITE_ROOTS = {"tests"}
WRITE_SUFFIXES = {".py"}  # a CR that needs fixtures widens this list explicitly, never silently
MAX_TEXT_CHARS = 40_000
UNTRACKED_LIMIT = 50
BINARY_SUFFIXES = {".db", ".png", ".jpg", ".jpeg", ".zip", ".pdf", ".pyc"}
BRANCH_PATTERN = re.compile(r"^CR-\d{3,4}$")


def _safe_repo_path(relative_path: str) -> Path:
    candidate = (REPO_ROOT / relative_path).resolve()
    if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
        raise ValueError("path escapes repository")
    return candidate


def _is_hidden(relative: Path) -> bool:
    """`.env`, `.git` and any dotted component are never readable or writable."""
    return any(part.startswith(".") for part in relative.parts)


def list_repo_files(prefix: str = "") -> dict:
    """List files under an allowlisted read-only area."""
    prefix = prefix.strip().strip("/")
    if prefix:
        top = prefix.split("/", 1)[0]
        if top not in READABLE_ROOTS:
            return {"ok": False, "error": f"read not allowed under {top!r}"}
        root = _safe_repo_path(prefix)
    else:
        root = REPO_ROOT
    if not root.exists():
        return {"ok": False, "error": "path does not exist"}
    items = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if not prefix and rel.parts[0] not in READABLE_ROOTS:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        items.append(str(rel))
    return {"ok": True, "files": items[:250]}


def read_scoped_file(relative_path: str) -> dict:
    """Read UTF-8 text from an allowlisted, non-hidden repository area.

    Escape attempts, hidden files (``.env``, ``.git``) and binary files are refused with
    ``{"ok": False}`` so the agent can see the refusal and adjust instead of crashing.
    """
    try:
        path = _safe_repo_path(relative_path)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    rel = path.relative_to(REPO_ROOT)
    if not rel.parts or rel.parts[0] not in READABLE_ROOTS:
        return {"ok": False, "error": "read not allowed for this path"}
    if _is_hidden(rel):
        return {"ok": False, "error": "hidden files are not readable"}
    if not path.is_file():
        return {"ok": False, "error": "file does not exist"}
    if path.suffix.lower() in {".db", ".png", ".jpg", ".jpeg", ".zip", ".pdf"}:
        return {"ok": False, "error": "binary file not supported"}
    text = path.read_text(encoding="utf-8")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n...[TRUNCATED]..."
    return {"ok": True, "path": str(rel), "content": text}


def read_repo_file(relative_path: str) -> dict:
    """Backwards-compatible name for ``read_scoped_file`` (the planning agents use it)."""
    return read_scoped_file(relative_path)


def _write_scoped_file(relative_path: str, content: str, allowed_roots: set[str]) -> dict:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return {"ok": False, "error": "relative path required"}
    try:
        path = _safe_repo_path(relative_path)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    rel = path.relative_to(REPO_ROOT)
    if not rel.parts:
        return {"ok": False, "error": "cannot write to the repository root"}
    if _is_hidden(rel):
        return {"ok": False, "error": "hidden paths are not writable"}
    if rel.parts[0] not in allowed_roots:
        return {"ok": False, "error": f"write not allowed under {rel.parts[0]!r}"}
    if path.suffix not in WRITE_SUFFIXES:
        return {"ok": False, "error": f"only {sorted(WRITE_SUFFIXES)} files can be written"}
    if path.exists() and not path.is_file():
        return {"ok": False, "error": "path is a directory"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(rel)}


def write_coder_file(relative_path: str, content: str) -> dict:
    """Coda write tool: only ``campusflow/`` and ``tests/``. Everything else is refused."""
    return _write_scoped_file(relative_path, content, CODER_WRITE_ROOTS)


def write_test_file(relative_path: str, content: str) -> dict:
    """Test Analyst write tool: only ``tests/``. It can never touch the product code."""
    return _write_scoped_file(relative_path, content, TESTER_WRITE_ROOTS)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )


def ensure_cr_branch(change_id: str) -> dict:
    """Create (or switch to) the isolated branch ``cr/<CR-ID>`` for one Change Request.

    Branch switching is the only git mutation the factory automates. Stashes, resets and
    force operations are irreversible, so they are never attempted: a failing checkout is
    returned as an error for a human to resolve.
    """
    change_id = (change_id or "").strip().upper()
    if not BRANCH_PATTERN.match(change_id):
        return {"ok": False, "error": f"invalid change id {change_id!r}; expected CR-001"}
    branch = f"cr/{change_id}"

    current = _git("rev-parse", "--abbrev-ref", "HEAD")
    if current.returncode == 0 and current.stdout.strip() == branch:
        return {"ok": True, "branch": branch, "created": False}

    exists = _git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if exists.returncode == 0:
        completed = _git("checkout", branch)
    else:
        completed = _git("checkout", "-b", branch)
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr.strip() or "git branch switch failed"}
    return {"ok": True, "branch": branch, "created": exists.returncode != 0}


def get_git_diff() -> dict:
    """Return ``git diff HEAD`` plus untracked new files and a porcelain status summary.

    ``git diff HEAD`` alone hides files the Coder just created, so untracked text files are
    appended explicitly. The result is truncated; the working tree is never mutated.
    """
    diff = _git("diff", "HEAD")
    if diff.returncode != 0:
        return {"ok": False, "error": diff.stderr.strip() or "git diff failed"}
    status = _git("status", "--porcelain", "-uall")
    if status.returncode != 0:
        return {"ok": False, "error": status.stderr.strip() or "git status failed"}

    text = diff.stdout
    untracked = [
        line[3:].strip()
        for line in status.stdout.splitlines()
        if line.startswith("?? ")
    ][:UNTRACKED_LIMIT]
    for name in untracked:
        path = REPO_ROOT / name
        if not path.is_file() or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text += f"\ndiff --git a/{name} b/{name}\n(new file, untracked)\n{content}"

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n...[TRUNCATED]..."
    return {"ok": True, "diff": text, "status": status.stdout.strip()}


def run_baseline_verification() -> dict:
    """Run an allowlisted deterministic baseline. No arbitrary shell input."""
    commands = [
        ["python", "-m", "pytest", "-q"],
        ["python", "-m", "ruff", "check", "campusflow", "tests", "factory_app", "scripts"],
    ]
    results = []
    all_ok = True
    for command in commands:
        completed = subprocess.run(
            command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=120, check=False
        )
        all_ok = all_ok and completed.returncode == 0
        results.append({
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-3000:],
        })
    return {"ok": all_ok, "results": results}


def write_run_evidence(change_id: str, filename: str, content: str) -> dict:
    """Write only evidence files under runs/<CR-ID>/; never product code."""
    if not change_id.startswith("CR-"):
        return {"ok": False, "error": "change_id must start with CR-"}
    if "/" in filename or "\\" in filename or not filename.endswith((".md", ".json", ".txt")):
        return {"ok": False, "error": "invalid evidence filename"}
    folder = REPO_ROOT / "runs" / change_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path.relative_to(REPO_ROOT))}
