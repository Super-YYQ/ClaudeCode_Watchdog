from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HookDecision:
    output: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False


def silent_output() -> dict[str, Any]:
    """Nothing worth surfacing -- just keep our JSON out of the transcript."""
    return {"suppressOutput": True}


def notify_output(message: str) -> dict[str, Any]:
    """Show the user a one-line warning; do not interfere with the turn."""
    return {"systemMessage": message, "suppressOutput": True}


def block_output(reason: str) -> dict[str, Any]:
    """Prevent the turn from stopping and feed ``reason`` back to Claude."""
    return {"decision": "block", "reason": reason, "suppressOutput": True}


def decide(
    score: int,
    *,
    resume_on_stop: bool,
    stop_hook_active: bool,
    blocks_used: int,
    max_blocks: int,
    notify_min: int,
    block_min: int,
    message: str,
    reason: str,
) -> HookDecision:
    """Choose block / notify / silent from primitives (no IO, fully testable).

    Blocking requires ALL of: it is opted in (``resume_on_stop``), the score
    clears ``block_min``, we have not already blocked this turn
    (``stop_hook_active`` is the platform's own loop guard), and we are under the
    per-session budget. Otherwise we notify at ``notify_min`` or stay silent.
    """
    can_block = (
        resume_on_stop
        and not stop_hook_active
        and score >= block_min
        and blocks_used < max_blocks
    )
    if can_block:
        return HookDecision(block_output(reason), blocked=True)
    if score >= notify_min:
        return HookDecision(notify_output(message), blocked=False)
    return HookDecision(silent_output(), blocked=False)
