"""Per-session block budget.

Claude Code already caps consecutive Stop blocks (CLAUDE_CODE_STOP_HOOK_BLOCK_CAP),
but we keep our own budget so a single session cannot be nudged in a loop.
Stored as an append-only JSONL of ``{session_id, ts}``; entries older than the
window are ignored *and* pruned on write, so the file cannot grow forever.
"""
from pathlib import Path

from ccs_watchdog.hooks.budget import blocks_used, record_block

NOW = 1_800_000_000.0


def test_unknown_session_has_no_blocks(tmp_path: Path):
    assert blocks_used(tmp_path, "s1", now=NOW) == 0


def test_record_block_counts_up(tmp_path: Path):
    assert record_block(tmp_path, "s1", now=NOW) == 1
    assert record_block(tmp_path, "s1", now=NOW) == 2
    assert blocks_used(tmp_path, "s1", now=NOW) == 2


def test_sessions_are_isolated(tmp_path: Path):
    record_block(tmp_path, "s1", now=NOW)
    assert blocks_used(tmp_path, "s2", now=NOW) == 0


def test_stale_entries_expire(tmp_path: Path):
    record_block(tmp_path, "s1", now=NOW - 10_000)
    assert blocks_used(tmp_path, "s1", now=NOW) == 0


def test_stale_entries_are_pruned_on_write(tmp_path: Path):
    record_block(tmp_path, "s1", now=NOW - 10_000)
    record_block(tmp_path, "s1", now=NOW)
    assert blocks_used(tmp_path, "s1", now=NOW) == 1
    # the stale line is gone from disk, not merely filtered
    assert len((tmp_path / "hook-blocks.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 1


def test_missing_directory_does_not_crash(tmp_path: Path):
    target = tmp_path / "does-not-exist"
    assert blocks_used(target, "s1", now=NOW) == 0
    assert record_block(target, "s1", now=NOW) == 1


def test_missing_session_id_is_ignored(tmp_path: Path):
    assert blocks_used(tmp_path, None, now=NOW) == 0
    assert record_block(tmp_path, None, now=NOW) == 0


def test_corrupt_line_is_skipped(tmp_path: Path):
    (tmp_path / "hook-blocks.jsonl").write_text("not json\n", encoding="utf-8")
    assert blocks_used(tmp_path, "s1", now=NOW) == 0
