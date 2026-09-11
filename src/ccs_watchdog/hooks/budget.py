"""Per-session block budget backing ``max_blocks_per_session``.

Claude Code already caps consecutive Stop blocks
(``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``); this is our own, narrower budget so a
single session cannot be nudged in a loop by a mis-scored turn.

State is an append-only JSONL of ``{"session_id", "ts"}``. Reads ignore entries
older than :data:`WINDOW_SECONDS`; writes prune them, so the file stays small
and a long-dead session automatically gets its budget back.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

STATE_FILE = "hook-blocks.jsonl"
#: Budgets reset an hour after the last block: a session that has gone quiet for
#: that long is a fresh context, and a stale file shrinks instead of growing.
WINDOW_SECONDS = 3600


def _read(directory: Path) -> list[dict]:
    path = Path(directory) / STATE_FILE
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            entries.append(record)
    return entries


def _fresh(entries: list[dict], now: float) -> list[dict]:
    kept = []
    for entry in entries:
        ts = entry.get("ts")
        if isinstance(ts, (int, float)) and now - ts <= WINDOW_SECONDS:
            kept.append(entry)
    return kept


def blocks_used(directory: Path, session_id: str | None, now: float | None = None) -> int:
    if not session_id:
        return 0
    now = time.time() if now is None else now
    return sum(1 for e in _fresh(_read(directory), now) if e.get("session_id") == session_id)


def record_block(directory: Path, session_id: str | None, now: float | None = None) -> int:
    """Append one block for ``session_id`` and return the new total."""
    if not session_id:
        return 0
    now = time.time() if now is None else now
    directory = Path(directory)
    entries = _fresh(_read(directory), now)
    entries.append({"session_id": session_id, "ts": now})
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / STATE_FILE).write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
    except OSError:
        pass  # a bookkeeping failure must never break the hook path
    return sum(1 for e in entries if e.get("session_id") == session_id)
