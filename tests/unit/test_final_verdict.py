"""``final_verdict`` judges how a session's *last* real turn ended.

The Stop hook fires at a turn boundary, so it needs the verdict anchored on the
last assistant turn (and any idle that follows it) -- not the loudest event from
somewhere back in history. Reuses the exact replay pipeline.
"""
from pathlib import Path

from ccs_watchdog.replay.engine import final_verdict

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def test_final_verdict_flags_a_tail_interruption():
    v = final_verdict(FIXTURES / "unfinished-text-then-done.jsonl")
    assert v is not None
    assert v.score >= 60
    assert "SILENT" in v.classification


def test_final_verdict_is_quiet_on_a_normal_loop():
    v = final_verdict(FIXTURES / "normal-tool-loop.jsonl")
    assert v is None or v.score < 30


def test_final_verdict_none_on_missing_file(tmp_path: Path):
    assert final_verdict(tmp_path / "nope.jsonl") is None


def test_final_verdict_none_on_empty_file(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert final_verdict(p) is None
