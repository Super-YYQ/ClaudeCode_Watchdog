from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Events we know how to act on. Others (PreToolUse, Notification, ...) parse to
# None so the CLI can exit 0 silently rather than guess.
STOP_EVENTS = frozenset({"Stop", "SubagentStop", "StopFailure"})


@dataclass
class HookInput:
    event_name: str
    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    stop_hook_active: bool = False
    last_assistant_message: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def parse_hook_input(data: Any) -> HookInput | None:
    """Turn a decoded hook-stdin object into a :class:`HookInput`.

    Returns ``None`` for anything that is not a stop-family event, so callers
    can no-op safely. Never raises on missing/odd fields.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("hook_event_name")
    if name not in STOP_EVENTS:
        return None
    return HookInput(
        event_name=name,
        session_id=_str_or_none(data.get("session_id")),
        transcript_path=_str_or_none(data.get("transcript_path")),
        cwd=_str_or_none(data.get("cwd")),
        stop_hook_active=bool(data.get("stop_hook_active")),
        last_assistant_message=_str_or_none(data.get("last_assistant_message")),
        error=_str_or_none(data.get("error")),
        raw=data,
    )


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
