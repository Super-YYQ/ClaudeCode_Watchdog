from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ccs_watchdog.events.normalize import NormalizedEvent, SAFE_TOOLS, SIDE_EFFECT_TOOLS


@dataclass
class SessionSnapshot:
    session_id: str | None = None
    last_kind: str | None = None
    last_text: str = ""
    last_model: str | None = None
    last_stop_reason: str | None = None
    last_tools: list[str] = field(default_factory=list)
    last_assistant_had_future: bool = False
    consecutive_empty: int = 0
    empty_total: int = 0
    pending_tool: bool = False
    last_tool_result: bool = False
    awaiting_user: bool = False
    idle: bool = False
    models_seen: list[str] = field(default_factory=list)
    last_side_effect_tool: str | None = None
    last_safe_tool: str | None = None
    human_interrupted: bool = False
    events: int = 0


class SessionStateMachine:
    def __init__(self) -> None:
        self.snap = SessionSnapshot()

    def apply(self, event: NormalizedEvent) -> SessionSnapshot:
        s = self.snap
        s.events += 1
        s.last_kind = event.kind
        if event.model:
            s.last_model = event.model
            if not s.models_seen or s.models_seen[-1] != event.model:
                s.models_seen.append(event.model)
        if event.stop_reason:
            s.last_stop_reason = event.stop_reason
        if event.kind == "ASSISTANT_EMPTY":
            s.consecutive_empty += 1
            s.empty_total += 1
            s.idle = False
        elif event.kind in {"ASSISTANT_TEXT", "TOOL_USE_STARTED", "API_ERROR"}:
            if event.kind != "API_ERROR":
                s.consecutive_empty = 0
            s.last_text = event.text
            s.last_assistant_had_future = event.future_action
            s.idle = False
        if event.kind == "TOOL_USE_STARTED":
            s.pending_tool = True
            s.last_tools = event.tools
            s.last_tool_result = False
            for tool in event.tools:
                if tool in SIDE_EFFECT_TOOLS:
                    s.last_side_effect_tool = tool
                if tool in SAFE_TOOLS:
                    s.last_safe_tool = tool
        if event.kind == "TOOL_RESULT":
            s.pending_tool = False
            s.last_tool_result = True
        if event.kind == "USER_PROMPT":
            s.awaiting_user = False
            s.human_interrupted = False
            text = (event.text or "").strip()
            if text in {"继续", "继续呀", "continue"}:
                s.human_interrupted = False
        if event.kind == "TURN_IDLE":
            s.idle = True
            s.pending_tool = False
        if event.kind in {"STOP_FAILURE", "API_ERROR"}:
            s.idle = True
        return s
