import json
import shutil
import tomllib
from pathlib import Path

import pytest

from ccs_watchdog.cli.main import build_parser, main, normalize_argv

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """A claude_home containing one real silent-interruption sample session."""
    home = tmp_path / "claude_home"
    proj = home / "projects" / "E--demo-proj"
    proj.mkdir(parents=True)
    shutil.copy(FIXTURES / "unfinished-text-then-done.jsonl", proj / "s-demo-0001.jsonl")
    path = tmp_path / "ccw.json"
    path.write_text(json.dumps({"claude_home": str(home)}), encoding="utf-8")
    return path


def _add_other_project(cfg_path: Path, session_name: str) -> Path:
    proj = Path(json.loads(cfg_path.read_text(encoding="utf-8"))["claude_home"]) / "projects" / "E--other-proj"
    proj.mkdir(parents=True, exist_ok=True)
    session = proj / session_name
    shutil.copy(FIXTURES / "normal-tool-loop.jsonl", session)
    return session


# --- subcommand defaulting ---------------------------------------------------

def test_bare_invocation_runs_watch():
    args = build_parser().parse_args(normalize_argv([]))
    assert args.command == "watch"


def test_watch_only_flags_work_without_the_subcommand():
    args = build_parser().parse_args(normalize_argv(["--once", "--dry-run"]))
    assert args.command == "watch"
    assert args.once is True and args.dry_run is True


def test_global_flags_keep_precedence_when_watch_is_inserted():
    assert normalize_argv(["--config", "x.json"]) == ["--config", "x.json", "watch"]


def test_watch_is_inserted_after_global_flags_but_before_its_own():
    assert normalize_argv(["--config", "x.json", "--once"]) == ["--config", "x.json", "watch", "--once"]


def test_config_is_accepted_after_a_subcommand(cfg_path: Path, capsys):
    assert main(["doctor", "--config", str(cfg_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["claude_home"].endswith("claude_home")


# --- ccw last ---------------------------------------------------------------

def test_last_is_a_known_subcommand():
    args = build_parser().parse_args(["last"])
    assert args.command == "last"


def test_last_reports_the_session_it_chose(cfg_path: Path, capsys):
    assert main(["--config", str(cfg_path), "last"]) == 0
    out = capsys.readouterr().out
    assert "s-demo-0001" in out


def test_last_shows_only_suspicious_verdicts(cfg_path: Path, capsys):
    assert main(["--config", str(cfg_path), "last"]) == 0
    out = capsys.readouterr().out
    assert "SUSPECTED_SILENT_INTERRUPTION" in out
    assert "record_only" not in out


def test_last_hints_the_equivalent_long_command(cfg_path: Path, capsys):
    main(["--config", str(cfg_path), "last"])
    out = capsys.readouterr().out
    assert "ccw replay" in out


def test_last_honours_suspicious_threshold_from_config(tmp_path: Path, cfg_path: Path, capsys):
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["suspicious_threshold"] = 100
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    assert main(["--config", str(cfg_path), "last"]) == 0
    out = capsys.readouterr().out
    assert "SUSPECTED_SILENT_INTERRUPTION" not in out
    assert "no event >= 100" in out


# --- project scoping --------------------------------------------------------

def test_any_project_scans_every_project(cfg_path: Path, capsys):
    newer = _add_other_project(cfg_path, "s-other-0002.jsonl")
    newer.touch()
    assert main(["--config", str(cfg_path), "last", "--any-project"]) == 0
    out = capsys.readouterr().out
    assert "s-other-0002" in out


def test_project_fragment_restricts_candidates(cfg_path: Path, capsys):
    _add_other_project(cfg_path, "s-other-0002.jsonl").touch()
    assert main(["--config", str(cfg_path), "last", "--project", "demo"]) == 0
    out = capsys.readouterr().out
    assert "s-demo-0001" in out
    assert "E--other-proj" not in out


def test_unknown_project_fragment_is_reported(cfg_path: Path, capsys):
    _add_other_project(cfg_path, "s-other-0002.jsonl")
    assert main(["--config", str(cfg_path), "last", "--project", "nosuchproject"]) == 2
    assert "no session" in capsys.readouterr().out


# --- ambiguity hint ---------------------------------------------------------

def test_ambiguous_session_prints_a_copy_pasteable_command(cfg_path: Path, capsys):
    other = _add_other_project(cfg_path, "s-demo-0002.jsonl")
    demo = Path(json.loads(cfg_path.read_text(encoding="utf-8"))["claude_home"]) / "projects" / "E--demo-proj" / "s-demo-0001.jsonl"
    other.touch()
    demo.touch()  # both written "just now" -> pick_session cannot guess
    assert main(["--config", str(cfg_path), "watch", "--any-project"]) == 2
    out = capsys.readouterr().out
    assert "AMBIGUOUS_SESSION" in out
    assert "--session s-demo-0001" in out or "--session s-demo-0002" in out


# --- graceful errors --------------------------------------------------------

def test_watch_without_any_session_exits_cleanly(tmp_path: Path, capsys):
    empty = tmp_path / "ccw.json"
    empty.write_text(json.dumps({"claude_home": str(tmp_path / "nothing")} ), encoding="utf-8")
    assert main(["--config", str(empty), "watch", "--any-project"]) == 2
    out = capsys.readouterr().out
    assert "no session" in out
    assert "Traceback" not in out


# --- packaging -------------------------------------------------------------

def test_pyproject_declares_the_ccw_alias():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["ccw"] == "ccs_watchdog.cli.main:main"
    assert scripts["ccs-watchdog"] == "ccs_watchdog.cli.main:main"
