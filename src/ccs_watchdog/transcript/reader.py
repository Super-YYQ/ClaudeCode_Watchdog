from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReaderState:
    path: Path
    offset: int = 0
    partial: str = ""
    fingerprint: str = ""


class IncrementalJsonlReader:
    """Read new JSONL records from a growing file without rereading the whole file."""

    def __init__(self, path: Path, offset: int = 0, partial: str = ""):
        self.state = ReaderState(path=Path(path), offset=offset, partial=partial)

    def _fingerprint(self, handle) -> str:
        pos = handle.tell()
        handle.seek(0)
        head = handle.read(64)
        handle.seek(pos)
        try:
            size = handle.seek(0, 2)
            handle.seek(pos)
        except Exception:
            size = -1
        return f"{len(head)}:{head[:16]!r}:{size}"

    def read_new(self) -> list[dict]:
        path = self.state.path
        if not path.exists():
            return []
        records: list[dict] = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.state.offset)
            data = handle.read()
            self.state.offset = handle.tell()
        blob = self.state.partial + data
        if not blob:
            return []
        lines = blob.split("\n")
        if blob.endswith("\n"):
            complete, self.state.partial = lines[:-1], ""
        else:
            complete, self.state.partial = lines[:-1], lines[-1]
        for line in complete:
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError:
                records.append({"_parse_error": True, "raw": text[:500], "type": "unknown"})
        return records
