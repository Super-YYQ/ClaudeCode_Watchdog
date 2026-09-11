from __future__ import annotations

import json
from pathlib import Path

from ccs_watchdog.events.normalize import ASSISTANT_KINDS, normalize_record
from ccs_watchdog.scoring.score import RECORD_THRESHOLD, score_event, Verdict
from ccs_watchdog.state.machine import SessionStateMachine


INTERESTING = {
    "SUSPECTED_SILENT_INTERRUPTION",
    "REPEATED_EMPTY_RESPONSE",
    "EMPTY_RESPONSE",
    "API_INTERRUPTED",
    "ROUTE_SWITCH_SUSPECTED",
    "SIDE_EFFECT_UNKNOWN",
    "NORMAL_END",
}


def final_verdict(path: Path) -> Verdict | None:
    """Judge how the session's last real turn ended (the Stop-hook question).

    Replays the whole transcript through the normal pipeline, then returns the
    verdict of the last real assistant turn plus any turn-ending records after
    it. Returns ``None`` when there is no last assistant turn to judge (empty
    file, missing file, or injected-only tail). ``TOOL_RUNNING``-style tails
    (assistant clearly mid-loop) yield a verdict the caller can score-gate.
    """
    machine = SessionStateMachine()
    events: list = []
    try:
        handle = Path(path).open(encoding="utf-8")
    except OSError:
        return None
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = normalize_record(record)
            snap = machine.apply(event)
            events.append((event, snap))
    for event, snap in reversed(events):
        if event.injected:
            continue
        if event.kind in ASSISTANT_KINDS:
            # the tail after the last assistant turn may itself carry the
            # turn-ending verdict (turn_duration idle); score those first
            later = [pair for pair in events if pair[1].events > snap.events]
            for tail_event, tail_snap in later:
                if tail_event.injected:
                    continue
                tail = score_event(tail_event, tail_snap)
                if tail.score > 0 and tail.classification != "TOOL_RUNNING":
                    return tail
            return score_event(event, snap)
    return None


def replay_path(path: Path) -> list[Verdict]:
    machine = SessionStateMachine()
    verdicts: list[Verdict] = []
    last_model = None
    last_model_ts = None
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = normalize_record(record)
            snap = machine.apply(event)
            switch_age = None
            if event.model and last_model and event.model != last_model:
                last_model = event.model
                last_model_ts = event.timestamp
            elif event.model and last_model is None:
                last_model = event.model
                last_model_ts = event.timestamp
            verdict = score_event(event, snap, switch_age)
            if verdict.classification in INTERESTING or verdict.score >= RECORD_THRESHOLD:
                verdicts.append(verdict)
    return verdicts


def format_verdicts(verdicts: list[Verdict]) -> str:
    lines = []
    for v in verdicts:
        lines.append(
            f"{v.timestamp or '-'}  {v.classification:32} score={v.score:3} stop={v.stop_reason} empty={v.empty_count} model={v.model}\n  evidence: {'; '.join(v.evidence)}\n  text: {v.last_text.replace(chr(10), ' ')[:180]}\n  action: {v.recommended_action}"
        )
    return "\n\n".join(lines)
