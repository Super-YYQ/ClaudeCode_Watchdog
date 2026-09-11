"""CLI surface for the hook channel: ``ccw hook`` / ``install-hook`` / ``uninstall-hook``.

``hook`` is special: Claude Code runs it inside the turn, so it must always exit
0 and always print one JSON object, even when stdin is empty or nonsense.
"""
import io
import json
from pathlib import Path

from ccs_watchdog.cli.main import main, normalize_argv
from ccs_watchdog.hooks.installer import MARKER

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _cfg_file(tmp_path: Path, **extra) -> Path:
    home = tmp_path / "claude_home"
    home.mkdir(parents=True, exist_ok=True)
    payload = {"claude_home": str(home), "hook_log_dir": str(tmp_path / "log")}
    payload.update(extra)
    path = tmp_path / "ccw.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _payload(**over) -> str:
    data = {
        "hook_event_name": "Stop",
        "session_id": "s-hook-tail",
        "transcript_path": str(FIXTURES / "hook-feedback-tail.jsonl"),
        "cwd": str(FIXTURES),
        "stop_hook_active": False,
    }
    data.update(over)
    return json.dumps(data)


# --- argv handling ----------------------------------------------------------

def test_hook_is_not_rewritten_into_watch():
    assert normalize_argv(["hook", "stop"]) == ["hook", "stop"]


def test_install_hook_is_not_rewritten_into_watch():
    assert normalize_argv(["install-hook"]) == ["install-hook"]


def test_uninstall_hook_is_not_rewritten_into_watch():
    assert normalize_argv(["uninstall-hook"]) == ["uninstall-hook"]


# --- ccw hook <event> -------------------------------------------------------

def test_hook_prints_one_json_object_and_exits_zero(tmp_path: Path, monkeypatch, capsys):
    cfg = _cfg_file(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload()))
    assert main(["--config", str(cfg), "hook", "stop"]) == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out.splitlines()[-1])
    assert "SUSPECTED_SILENT_INTERRUPTION" in payload["systemMessage"]


def test_hook_with_empty_stdin_stays_silent(tmp_path: Path, monkeypatch, capsys):
    cfg = _cfg_file(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["--config", str(cfg), "hook", "stop"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"suppressOutput": True}


def test_hook_with_garbage_stdin_stays_silent(tmp_path: Path, monkeypatch, capsys):
    cfg = _cfg_file(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json at all"))
    assert main(["--config", str(cfg), "hook", "stop"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"suppressOutput": True}


def test_hook_survives_a_broken_payload_shape(tmp_path: Path, monkeypatch, capsys):
    cfg = _cfg_file(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"hook_event_name": "Stop", "cwd": 42}'))
    assert main(["--config", str(cfg), "hook", "stop"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"suppressOutput": True}


def test_hook_rejects_an_unknown_event_name(tmp_path: Path):
    cfg = _cfg_file(tmp_path)
    try:
        main(["--config", str(cfg), "hook", "nonsense"])
    except SystemExit as exc:  # argparse choices
        assert exc.code == 2
    else:
        raise AssertionError("expected argparse to reject the event name")


# --- ccw install-hook / uninstall-hook --------------------------------------

def test_install_hook_writes_the_settings_file(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path)
    assert main(["--config", str(cfg), "install-hook"]) == 0
    out = capsys.readouterr().out
    settings = tmp_path / "claude_home" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert MARKER in json.dumps(data["hooks"]["Stop"], ensure_ascii=False)
    assert "settings.json" in out
    assert "uninstall-hook" in out  # tells the user how to undo it


def test_install_hook_honours_configured_events(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path, hook_events=["Stop"])
    main(["--config", str(cfg), "install-hook"])
    capsys.readouterr()
    data = json.loads((tmp_path / "claude_home" / "settings.json").read_text(encoding="utf-8"))
    assert set(data["hooks"]) == {"Stop"}


def test_install_hook_bakes_the_config_path_into_the_command(tmp_path: Path, capsys):
    """Otherwise the hook would run on defaults and ignore resume_on_stop."""
    cfg = _cfg_file(tmp_path, resume_on_stop=True)
    main(["--config", str(cfg), "install-hook"])
    capsys.readouterr()
    data = json.loads((tmp_path / "claude_home" / "settings.json").read_text(encoding="utf-8"))
    args = data["hooks"]["Stop"][0]["hooks"][0]["args"]
    assert args[args.index("--config") + 1] == str(cfg)


def test_hook_uses_the_config_it_was_installed_with(tmp_path: Path, monkeypatch, capsys):
    """End-to-end of the above: the registered argv must reach a real block."""
    cfg = _cfg_file(tmp_path, resume_on_stop=True, threshold=60)
    main(["--config", str(cfg), "install-hook"])
    capsys.readouterr()
    entry = json.loads((tmp_path / "claude_home" / "settings.json").read_text(encoding="utf-8"))
    # argv[0] is "-c", argv[1] the bootstrap; the rest is the real command line
    argv = entry["hooks"]["Stop"][0]["hooks"][0]["args"][2:]
    assert argv[0] == "hook" and argv[1] == "stop"
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload()))
    assert main(argv) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["decision"] == "block"


def test_install_hook_refuses_rather_than_damaging_bad_json(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path)
    settings = tmp_path / "claude_home" / "settings.json"
    settings.write_text("{broken", encoding="utf-8")
    assert main(["--config", str(cfg), "install-hook"]) == 2
    out = capsys.readouterr().out
    assert "安装失败" in out or "JSON" in out
    assert settings.read_text(encoding="utf-8") == "{broken"


def test_uninstall_hook_removes_only_our_entries(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path)
    settings = tmp_path / "claude_home" / "settings.json"
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other.exe"}]}]}}),
        encoding="utf-8",
    )
    main(["--config", str(cfg), "install-hook"])
    capsys.readouterr()
    assert main(["--config", str(cfg), "uninstall-hook"]) == 0
    capsys.readouterr()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "other.exe"}]}]


def test_uninstall_hook_on_a_clean_file_says_so(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path)
    assert main(["--config", str(cfg), "uninstall-hook"]) == 0
    assert "没有" in capsys.readouterr().out


# --- doctor ------------------------------------------------------------------

def test_doctor_reports_hook_installation_state(tmp_path: Path, capsys):
    cfg = _cfg_file(tmp_path)
    assert main(["--config", str(cfg), "doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hook_installed"]["Stop"] is False
    main(["--config", str(cfg), "install-hook"])
    capsys.readouterr()
    assert main(["--config", str(cfg), "doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hook_installed"]["Stop"] is True
    assert "settings.json" in report["hook_settings_path"]
