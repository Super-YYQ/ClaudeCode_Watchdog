from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionHit:
    session_id: str
    path: Path
    mtime: float
    size: int
    project: str


class AmbiguousSession(Exception):
    def __init__(self, hits: list[SessionHit]):
        super().__init__("AMBIGUOUS_SESSION")
        self.hits = hits


def encode_cwd(cwd: Path) -> str:
    """Turn a working directory into Claude Code's project folder name.

    Claude Code replaces *every* character that is not ASCII alphanumeric or
    ``-`` with ``-`` -- so ``:`` and ``\\`` become ``-``, and so do CJK
    characters, dots, spaces and underscores. The parametrised test in
    ``tests/unit/test_discovery.py`` pins each of those character classes.
    """
    text = str(Path(cwd).resolve())
    return "".join(ch if (ch.isascii() and (ch.isalnum() or ch == "-")) else "-" for ch in text)


def discover_sessions(
    projects_dir: Path,
    cwd: Path | None = None,
    project: str | None = None,
) -> list[SessionHit]:
    """Find session transcripts.

    ``project`` is a case-insensitive fragment matched against the encoded
    project directory names and wins over ``cwd``. With neither, every project
    is scanned. A ``cwd`` that matches no project directory yields nothing --
    it deliberately does *not* fall back to a global scan, so ``watch`` never
    binds a transcript from an unrelated project.
    """
    if not projects_dir.exists():
        return []
    hits: list[SessionHit] = []
    dirs = []
    if project:
        needle = project.lower()
        dirs = [p for p in projects_dir.iterdir() if p.is_dir() and needle in p.name.lower()]
    elif cwd is not None:
        encoded = encode_cwd(cwd)
        exact = projects_dir / encoded
        if exact.exists():
            dirs = [exact]
        else:
            dirs = [p for p in projects_dir.iterdir() if p.is_dir() and encoded in p.name]
    if not dirs and project is None and cwd is None:
        dirs = [p for p in projects_dir.iterdir() if p.is_dir()]
    for folder in dirs:
        for path in folder.glob("*.jsonl"):
            stat = path.stat()
            hits.append(SessionHit(path.stem, path, stat.st_mtime, stat.st_size, folder.name))
    hits.sort(key=lambda h: h.mtime, reverse=True)
    return hits


def pick_session(hits: list[SessionHit], explicit: str | None = None) -> SessionHit:
    if explicit:
        for hit in hits:
            if explicit in {hit.session_id, str(hit.path), hit.path.name}:
                return hit
            if explicit in str(hit.path):
                return hit
        raise FileNotFoundError(explicit)
    if not hits:
        raise FileNotFoundError("no Claude session jsonl found")
    newest = hits[0]
    recent = [h for h in hits if newest.mtime - h.mtime < 30 and h.path != newest.path]
    if recent:
        raise AmbiguousSession([newest, *recent])
    return newest
