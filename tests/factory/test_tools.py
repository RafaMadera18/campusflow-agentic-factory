"""Tests for the bounded tools. The repository root is swapped for a temp git repo, so no
test ever touches the real working tree and no model is involved."""

import subprocess

import pytest

from factory_app import tools


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real (temporary) git repository wired as the tools' REPO_ROOT."""
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(tools, "REPO_ROOT", root)
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    (root / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "factory@example.com")
    _git(root, "config", "user.name", "Factory")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "seed")
    (root / "docs").mkdir()
    (root / "docs" / "REQUIREMENTS.md").write_text("# Requirements\n", encoding="utf-8")
    (root / ".env").write_text("GOOGLE_API_KEY=super-secret\n", encoding="utf-8")
    return root


def _branch_of(root):
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


# --- scoped reads -------------------------------------------------------------------


def test_read_blocks_env_git_and_escapes(repo):
    assert tools.read_scoped_file(".env")["ok"] is False
    assert tools.read_scoped_file(".git/config")["ok"] is False
    assert tools.read_scoped_file("../outside.py")["ok"] is False
    assert tools.read_scoped_file("factory_app/tools.py")["ok"] is False
    assert tools.read_scoped_file("/etc/passwd")["ok"] is False


def test_read_allows_the_documented_areas(repo):
    outcome = tools.read_scoped_file("docs/REQUIREMENTS.md")

    assert outcome["ok"] is True
    assert outcome["content"] == "# Requirements\n"


def test_read_hides_files_nested_under_allowed_roots(repo):
    secret = repo / "runs" / "CR-001"
    secret.mkdir(parents=True)
    (secret / ".env").write_text("KEY=x", encoding="utf-8")

    assert tools.read_scoped_file("runs/CR-001/.env")["ok"] is False


def test_listing_skips_hidden_files(repo):
    files = tools.list_repo_files()["files"]

    assert "docs/REQUIREMENTS.md" in files
    assert not any(part.startswith(".") for path in files for part in path.split("/"))


# --- bounded writes -----------------------------------------------------------------


def test_coder_writes_only_campusflow_and_tests(repo):
    assert tools.write_coder_file("campusflow/new_rule.py", "RULE = 1\n")["ok"] is True
    assert (repo / "campusflow" / "new_rule.py").read_text(encoding="utf-8") == "RULE = 1\n"
    assert tools.write_coder_file("tests/test_new_rule.py", "def test_rule(): pass\n")["ok"]

    for forbidden in (
        "factory_app/hack.py",
        "docs/hack.py",
        "runs/hack.py",
        "scripts/hack.py",
        ".env",
        "README.md",
        "campusflow/../docs/hack.py",  # resolve() sees through the traversal
        "campusflow/.hidden.py",
        "campusflow/notes.md",  # only .py is writable
        "",
        "/tmp/absolute.py",
    ):
        outcome = tools.write_coder_file(forbidden, "x = 1\n")
        assert outcome["ok"] is False, f"expected refusal for {forbidden!r}"
    assert not (repo / "docs" / "hack.py").exists()
    assert not (repo / "factory_app").exists()


def test_tester_cannot_touch_the_product(repo):
    assert tools.write_test_file("tests/test_waitlist.py", "def test_ok(): pass\n")["ok"]

    for forbidden in ("campusflow/service.py", "factory_app/agents.py", "docs/SPEC.md"):
        assert tools.write_test_file(forbidden, "x = 1\n")["ok"] is False
    assert not (repo / "campusflow" / "service.py").exists()


def test_writes_create_missing_directories_inside_the_allowlist(repo):
    outcome = tools.write_coder_file("campusflow/nested/deep/module.py", "X = 1\n")

    assert outcome["ok"] is True
    assert (repo / "campusflow" / "nested" / "deep" / "module.py").is_file()


# --- git ----------------------------------------------------------------------------


def test_ensure_cr_branch_creates_then_reuses(repo):
    created = tools.ensure_cr_branch("CR-001")

    assert created == {"ok": True, "branch": "cr/CR-001", "created": True}
    assert _branch_of(repo) == "cr/CR-001"

    again = tools.ensure_cr_branch("cr-001")  # case is normalized

    assert again == {"ok": True, "branch": "cr/CR-001", "created": False}
    assert _branch_of(repo) == "cr/CR-001"


def test_ensure_cr_branch_refuses_malformed_ids(repo):
    before = _branch_of(repo)
    for bad in ("", "CR", "CR-abc", "../../etc", "CR-001;rm -rf"):
        assert tools.ensure_cr_branch(bad)["ok"] is False
    assert _branch_of(repo) == before  # a refused call never switches branch


def test_git_diff_includes_tracked_changes_and_new_files(repo):
    (repo / "campusflow").mkdir()
    (repo / "campusflow" / "service.py").write_text("OLD = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "service")
    clean = tools.get_git_diff()
    assert clean["ok"] is True
    assert clean["diff"].strip() == ""

    (repo / "campusflow" / "service.py").write_text("OLD = 1\nNEW = 2\n", encoding="utf-8")
    (repo / "campusflow" / "waitlist.py").write_text("WAITLIST = True\n", encoding="utf-8")

    outcome = tools.get_git_diff()

    assert outcome["ok"] is True
    assert "+NEW = 2" in outcome["diff"]
    assert "waitlist.py" in outcome["diff"]  # untracked files are not invisible
    assert "?? campusflow/waitlist.py" in outcome["status"]


def test_git_diff_never_reports_secrets_from_env(repo):
    # .env is untracked and secret-bearing; the diff must not leak it.
    assert "GOOGLE_API_KEY" not in tools.get_git_diff()["diff"]
    assert ".env" not in tools.get_git_diff()["status"]
