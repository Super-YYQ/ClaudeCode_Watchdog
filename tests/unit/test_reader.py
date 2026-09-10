from pathlib import Path

from ccs_watchdog.transcript.reader import IncrementalJsonlReader


def test_incremental_and_partial(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"type":"a","n":1}\n{"type":"b"', encoding="utf-8")
    reader = IncrementalJsonlReader(path)
    first = reader.read_new()
    assert [r["type"] for r in first] == ["a"]
    rest = ",\"n\":2}\n{\"type\":\"c\",\"n\":3}\n"
    path.write_text(path.read_text(encoding="utf-8") + rest, encoding="utf-8")
    second = reader.read_new()
    assert [r["type"] for r in second] == ["b", "c"]


def test_malformed_line_does_not_crash(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text('{not json\n{"type":"ok"}\n', encoding="utf-8")
    rows = IncrementalJsonlReader(path).read_new()
    assert rows[0]["_parse_error"] is True
    assert rows[1]["type"] == "ok"