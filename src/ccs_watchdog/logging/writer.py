from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ccs_watchdog.logging.redact import redact
from ccs_watchdog.scoring.score import Verdict


class EventLog:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.jsonl = directory / "events.jsonl"
        self.text = directory / "watchdog.log"

    def emit(self, verdict: Verdict, extra: dict | None = None) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "watchdog_version": "0.1.0",
            "classification": verdict.classification,
            "interruption_score": verdict.score,
            "evidence": verdict.evidence,
            "stop_reason": verdict.stop_reason,
            "empty_assistant_count": verdict.empty_count,
            "model": verdict.model,
            "last_assistant_text_summary": redact(verdict.last_text[:240]),
            "resume_attempt": False,
            "recommended_action": verdict.recommended_action,
        }
        if extra:
            payload.update(extra)
        line = json.dumps(payload, ensure_ascii=False)
        with self.jsonl.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        with self.text.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{payload['timestamp']} {verdict.classification} score={verdict.score} {redact('; '.join(verdict.evidence))}\n"
            )
