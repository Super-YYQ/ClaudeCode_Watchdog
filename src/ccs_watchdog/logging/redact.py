from __future__ import annotations

import re

SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|gAAAA[A-Za-z0-9+/=_-]{20,}|Bearer\s+[A-Za-z0-9._\-]{8,}|api[_-]?key\s*=\s*\S+)"
)


def redact(text: str) -> str:
    if not text:
        return text
    return SECRET_RE.sub("<redacted>", text)
