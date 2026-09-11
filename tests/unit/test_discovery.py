from pathlib import Path

import pytest

from ccs_watchdog.discovery.sessions import (
    AmbiguousSession,
    discover_sessions,
    encode_cwd,
    pick_session,
)

# Synthetic stand-ins covering every character class Claude Code collapses:
# drive letters, separators, dots, spaces, underscores, and CJK (one `-` per
# character, which is why a two-character name yields exactly two dashes).
REAL_ENCODINGS = [
    ("C:/Users/demo", "C--Users-demo"),
    ("E:/repos/测试/ClaudeCode_Watchdog", "E--repos----ClaudeCode-Watchdog"),
    ("D:/tmp/测试/apitemp", "D--tmp----apitemp"),
    ("D:/Files/示例目录/子目录/中文名称测试Excel处理", "D--Files----------------Excel--"),
    (
        "D:/tmp/tool/.claude/worktrees/demo-non0-groovy",
        "D--tmp-tool--claude-worktrees-demo-non0-groovy",
    ),
    ("D:/示例/中文目录名/a b_c", "D-----------a-b-c"),
]


@pytest.mark.parametrize("cwd,expected", REAL_ENCODINGS)
def test_encode_cwd_collapses_every_non_alphanumeric_char(cwd: str, expected: str):
    assert encode_cwd(Path(cwd)) == expected


def test_discover_newest(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    a = proj / "aaa.jsonl"
    a.write_text("{}", encoding="utf-8")
    import os

    old = a.stat().st_mtime - 120
    os.utime(a, (old, old))
    b = proj / "bbb.jsonl"
    b.write_text("{}", encoding="utf-8")
    hits = discover_sessions(tmp_path)
    chosen = pick_session(hits)
    assert chosen.path.name == "bbb.jsonl"


def test_discover_ambiguous_when_both_fresh(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    a = proj / "aaa.jsonl"
    a.write_text("{}", encoding="utf-8")
    b = proj / "bbb.jsonl"
    b.write_text("{}", encoding="utf-8")
    hits = discover_sessions(tmp_path)
    try:
        pick_session(hits)
        raised = False
    except AmbiguousSession:
        raised = True
    assert raised


def _make_project(projects_dir: Path, name: str, *sessions: str) -> Path:
    proj = projects_dir / name
    proj.mkdir(parents=True, exist_ok=True)
    for session in sessions:
        (proj / session).write_text("{}", encoding="utf-8")
    return proj


def test_cwd_scoped_search_does_not_fall_back_to_other_projects(tmp_path: Path):
    _make_project(tmp_path, "E--somewhere-else", "aaa.jsonl")
    assert discover_sessions(tmp_path, tmp_path / "E--demo") == []


def test_project_fragment_selects_matching_project_dirs(tmp_path: Path):
    _make_project(tmp_path, "E--github---ClaudeCode-Watchdog", "a.jsonl")
    _make_project(tmp_path, "D--other-game", "b.jsonl")
    hits = discover_sessions(tmp_path, project="watchdog")
    assert [h.path.name for h in hits] == ["a.jsonl"]


def test_project_fragment_is_ignored_when_nothing_matches(tmp_path: Path):
    _make_project(tmp_path, "E--demo", "a.jsonl")
    assert discover_sessions(tmp_path, project="nope") == []


def test_undirected_search_still_scans_every_project(tmp_path: Path):
    _make_project(tmp_path, "E--demo", "a.jsonl")
    _make_project(tmp_path, "D--other", "b.jsonl")
    assert {h.path.name for h in discover_sessions(tmp_path)} == {"a.jsonl", "b.jsonl"}

