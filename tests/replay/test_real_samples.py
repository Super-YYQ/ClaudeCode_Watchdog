from pathlib import Path

from ccs_watchdog.replay.engine import replay_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_sample_a_unfinished_then_done():
    verdicts = replay_path(FIXTURES / "unfinished-text-then-done.jsonl")
    silent = [v for v in verdicts if v.score >= 60]
    assert silent, [ (v.classification, v.score, v.evidence) for v in verdicts ]
    assert any("开始开发" in (v.last_text or "") or "然后开始" in (v.last_text or "") or "让我看" in (v.last_text or "") for v in silent)


def test_sample_b_repeated_empty_end_turn():
    verdicts = replay_path(FIXTURES / "repeated-empty-then-end-turn.jsonl")
    hits = [v for v in verdicts if v.score >= 60]
    assert hits
    assert any("正在为镜像功能写测试" in (v.last_text or "") for v in hits)


def test_normal_tool_loop_not_high():
    verdicts = replay_path(FIXTURES / "normal-tool-loop.jsonl")
    assert all(v.score < 80 for v in verdicts)
