"""``ccw hook <event>`` -- the in-band channel.

Fires in every Claude Code window (including ones opened after the watchdog
started), reads the hook payload on stdin, judges the turn that just ended, and
prints a JSON object on stdout. Hard rules: it always exits 0, and it never
blocks while ``stop_hook_active`` is set.
"""
import json
from pathlib import Path

from ccs_watchdog.config.defaults import WatchdogConfig
from ccs_watchdog.hooks.payload import parse_hook_input
from ccs_watchdog.hooks.runner import handle_hook

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _payload(fixture: str, **over) -> dict:
    data = {
        "hook_event_name": "Stop",
        "session_id": "s-hook-tail",
        "transcript_path": str(FIXTURES / fixture),
        "cwd": str(FIXTURES),
        "stop_hook_active": False,
    }
    data.update(over)
    return data


def _run(tmp_path: Path, fixture: str = "hook-feedback-tail.jsonl", **over):
    cfg = WatchdogConfig(log_dir=tmp_path / "log", hook_log_dir=tmp_path / "log")
    hook = parse_hook_input(_payload(fixture, **over))
    return handle_hook(hook, cfg)


# --- the core judgement -----------------------------------------------------

def test_suspicious_turn_notifies_without_blocking(tmp_path: Path):
    run = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), WatchdogConfig(log_dir=tmp_path))
    assert run.exit_code == 0
    assert run.blocked is False
    assert "decision" not in run.output
    assert "SUSPECTED_SILENT_INTERRUPTION" in run.output["systemMessage"]


def test_quiet_turn_is_silent(tmp_path: Path):
    run = handle_hook(parse_hook_input(_payload("normal-tool-loop.jsonl")), WatchdogConfig(log_dir=tmp_path))
    assert run.output == {"suppressOutput": True}
    assert run.blocked is False


def test_injected_hook_feedback_never_becomes_the_verdict(tmp_path: Path):
    """The tail of this fixture is hook feedback, not Claude. Anchor on Claude."""
    run = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), WatchdogConfig(log_dir=tmp_path))
    assert run.verdict is not None
    # the real assistant sentence is what got judged
    assert "前端状态管理" in run.verdict.last_text
    # ...and our own feedback text never leaks into the user-facing message
    assert "design-not-done" not in run.output.get("systemMessage", "")


# --- blocking is opt-in and triple-guarded ----------------------------------

def test_blocking_requires_resume_on_stop(tmp_path: Path):
    cfg = WatchdogConfig(resume_on_stop=True, threshold=60, log_dir=tmp_path)
    run = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), cfg)
    assert run.blocked is True
    assert run.output["decision"] == "block"
    assert "不要重复已经成功执行的" in run.output["reason"]


def test_stop_hook_active_short_circuits_the_block(tmp_path: Path):
    cfg = WatchdogConfig(resume_on_stop=True, threshold=60, log_dir=tmp_path)
    run = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl", stop_hook_active=True)), cfg)
    assert run.blocked is False
    assert "decision" not in run.output


def test_block_budget_is_spent_then_respected(tmp_path: Path):
    cfg = WatchdogConfig(
        resume_on_stop=True, threshold=60, max_blocks_per_session=1, log_dir=tmp_path,
        hook_log_dir=tmp_path,
    )
    first = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), cfg)
    second = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), cfg)
    assert first.blocked is True
    assert second.blocked is False
    assert "decision" not in second.output


# --- never break the user's turn -------------------------------------------

def test_missing_transcript_is_silent(tmp_path: Path):
    hook = parse_hook_input(_payload("no-such-file.jsonl"))
    run = handle_hook(hook, WatchdogConfig(log_dir=tmp_path))
    assert run.exit_code == 0
    assert run.output == {"suppressOutput": True}


def test_unreadable_transcript_is_silent(tmp_path: Path):
    run = handle_hook(parse_hook_input(_payload(".", )), WatchdogConfig(log_dir=tmp_path))
    assert run.output == {"suppressOutput": True}


def test_none_hook_is_silent(tmp_path: Path):
    run = handle_hook(None, WatchdogConfig(log_dir=tmp_path))
    assert run.exit_code == 0
    assert run.output == {"suppressOutput": True}


def test_unwritable_log_dir_does_not_crash(tmp_path: Path):
    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    run = handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), WatchdogConfig(log_dir=blocker))
    assert run.exit_code == 0


# --- logging ----------------------------------------------------------------

def test_verdict_is_logged_for_later_triage(tmp_path: Path):
    handle_hook(parse_hook_input(_payload("hook-feedback-tail.jsonl")), WatchdogConfig(hook_log_dir=tmp_path))
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["classification"] == "SUSPECTED_SILENT_INTERRUPTION"
    assert entry["session_id"] == "s-hook-tail"
    assert entry["source"] == "hook"


def test_uninteresting_verdict_is_not_logged(tmp_path: Path):
    """A turn ending mid-tool-loop is normal; it must not fill the log."""
    run = handle_hook(parse_hook_input(_payload("normal-tool-loop.jsonl")), WatchdogConfig(hook_log_dir=tmp_path))
    assert run.output == {"suppressOutput": True}
    assert not (tmp_path / "events.jsonl").exists()
