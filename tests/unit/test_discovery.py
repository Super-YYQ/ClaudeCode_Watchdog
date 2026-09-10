from pathlib import Path

from ccs_watchdog.discovery.sessions import AmbiguousSession, discover_sessions, pick_session


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
