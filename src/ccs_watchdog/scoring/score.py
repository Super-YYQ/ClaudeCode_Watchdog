from __future__ import annotations

from dataclasses import dataclass, field

from ccs_watchdog.events.normalize import NormalizedEvent, SIDE_EFFECT_TOOLS
from ccs_watchdog.state.machine import SessionSnapshot


CLASS_NORMAL = "NORMAL"
CLASS_NORMAL_END = "NORMAL_END"
CLASS_TOOL_RUNNING = "TOOL_RUNNING"
CLASS_WAITING_USER = "WAITING_USER"
CLASS_API_INTERRUPTED = "API_INTERRUPTED"
CLASS_EMPTY_RESPONSE = "EMPTY_RESPONSE"
CLASS_REPEATED_EMPTY = "REPEATED_EMPTY_RESPONSE"
CLASS_SILENT = "SUSPECTED_SILENT_INTERRUPTION"
CLASS_SIDE_EFFECT = "SIDE_EFFECT_UNKNOWN"
CLASS_ROUTE_SWITCH = "ROUTE_SWITCH_SUSPECTED"
CLASS_UNKNOWN = "UNKNOWN"


@dataclass
class Verdict:
    classification: str
    score: int
    evidence: list[str] = field(default_factory=list)
    recommended_action: str = "none"
    event_kind: str = ""
    stop_reason: str | None = None
    empty_count: int = 0
    model: str | None = None
    timestamp: str | None = None
    uuid: str | None = None
    last_text: str = ""


def _clip(score: int) -> int:
    return max(0, min(100, score))


def score_event(event: NormalizedEvent, snap: SessionSnapshot, switch_age_s: float | None = None) -> Verdict:
    evidence: list[str] = []
    score = 0
    classification = CLASS_NORMAL

    if event.kind == "TOOL_USE_STARTED" or snap.pending_tool and event.kind not in {"TURN_IDLE", "ASSISTANT_EMPTY", "ASSISTANT_TEXT"}:
        if event.kind == "TOOL_USE_STARTED":
            return Verdict(CLASS_TOOL_RUNNING, 0, ["tool_use started"], "none", event.kind, event.stop_reason, snap.consecutive_empty, event.model, event.timestamp, event.uuid, event.text)

    if event.kind == "API_ERROR" or event.kind == "STOP_FAILURE":
        score += 25
        evidence.append("explicit API/StopFailure")
        classification = CLASS_API_INTERRUPTED

    if event.empty_assistant:
        score += 20
        evidence.append("assistant empty/thinking-only/zero-text")
        classification = CLASS_EMPTY_RESPONSE
        if snap.consecutive_empty >= 2:
            score += 35
            evidence.append(f"consecutive empty={snap.consecutive_empty}")
            classification = CLASS_REPEATED_EMPTY

    if event.kind == "TURN_IDLE":
        if snap.last_assistant_had_future and not snap.pending_tool:
            score += 30
            evidence.append("idle after future-action text without following tool_use in this idle")
            classification = CLASS_SILENT
        if snap.last_stop_reason == "end_turn" and snap.last_assistant_had_future:
            score += 20
            evidence.append("stop_reason=end_turn contradicts unfinished phrase")
            classification = CLASS_SILENT
        if snap.last_stop_reason is None and snap.last_assistant_had_future:
            score += 30
            evidence.append("stop_reason missing on unfinished assistant turn")
            classification = CLASS_SILENT
        if snap.consecutive_empty >= 2:
            score += 15
            evidence.append("idle after repeated empty")
            classification = CLASS_REPEATED_EMPTY
        if snap.last_tool_result and snap.last_assistant_had_future:
            score += 10
            evidence.append("recent tool_result then unfinished idle")
        if not evidence:
            classification = CLASS_NORMAL_END
            score -= 40
            evidence.append("turn_duration idle without unfinished signals")

    if event.kind == "ASSISTANT_TEXT" and event.future_action and event.stop_reason in {None, "end_turn"} and not event.tools:
        score += 30
        evidence.append("assistant promised next action but emitted no tool_use")
        if event.stop_reason == "end_turn":
            classification = CLASS_SILENT
            score += 30  # real sample B: end_turn on an explicit in-progress statement
            evidence.append("stop_reason=end_turn contradicts unfinished phrase")
        elif event.stop_reason is None:
            classification = CLASS_SILENT
            score += 30  # real sample A: message had no stop_reason at all
            evidence.append("stop_reason absent (proxy/conversion likely)")

    if switch_age_s is not None and switch_age_s >= 0 and switch_age_s <= 60 and score >= 30:
        score += 10
        evidence.append(f"provider/model switch {int(switch_age_s)}s before event")
        if classification == CLASS_SILENT:
            classification = CLASS_ROUTE_SWITCH

    if snap.last_side_effect_tool and snap.last_side_effect_tool in SIDE_EFFECT_TOOLS and score >= 60:
        if snap.last_side_effect_tool not in {"Read", "Grep", "Glob"}:
            # Bash is mixed; keep as unknown only if last tool was write-like
            if snap.last_side_effect_tool in {"Edit", "Write", "NotebookEdit"}:
                classification = CLASS_SIDE_EFFECT
                evidence.append(f"last side-effect tool={snap.last_side_effect_tool}")

    score = _clip(score)
    if score >= 80:
        action = "auto_resume_if_enabled"
    elif score >= 60:
        action = "dry_run_prompt"
    elif score >= 30:
        action = "record_only"
    else:
        action = "none"
    if classification == CLASS_SIDE_EFFECT:
        action = "manual_review"
    return Verdict(
        classification=classification,
        score=score,
        evidence=evidence,
        recommended_action=action,
        event_kind=event.kind,
        stop_reason=event.stop_reason or snap.last_stop_reason,
        empty_count=snap.consecutive_empty,
        model=event.model or snap.last_model,
        timestamp=event.timestamp,
        uuid=event.uuid,
        last_text=(event.text or snap.last_text)[:240],
    )
