"""Judge the turn that just ended and answer Claude Code.

The whole point of the in-band channel: Claude Code calls us at the turn
boundary, so we see every window -- including ones opened after any ``ccw watch``
was started. Two invariants hold no matter what:

1. **Always exit 0.** A crash here would stall the user's turn, so every side
   effect (logging, budget bookkeeping) is best-effort.
2. **Never block while ``stop_hook_active`` is set.** That flag means we already
   blocked this turn; blocking again is how a hook traps a session in a loop.
   Claude Code also caps this (``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``) -- we simply
   do not rely on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ccs_watchdog.config.defaults import WatchdogConfig
from ccs_watchdog.hooks.budget import blocks_used, record_block
from ccs_watchdog.hooks.output import decide, silent_output
from ccs_watchdog.hooks.payload import HookInput
from ccs_watchdog.logging.writer import EventLog
from ccs_watchdog.replay.engine import final_verdict
from ccs_watchdog.resume.controller import resume_prompt
from ccs_watchdog.scoring.score import CLASS_REPEATED_EMPTY, RECORD_THRESHOLD, Verdict


@dataclass
class HookRun:
    output: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    verdict: Verdict | None = None
    exit_code: int = 0


def log_dir_for(cfg: WatchdogConfig) -> Path:
    """One sink for every project's hook events (``~/.claude/watchdog``)."""
    if cfg.hook_log_dir:
        return Path(cfg.hook_log_dir)
    if cfg.log_dir:
        return Path(cfg.log_dir)
    return Path(cfg.claude_home) / "watchdog"


def handle_hook(hook: HookInput | None, cfg: WatchdogConfig) -> HookRun:
    if hook is None or not hook.transcript_path:
        return HookRun(silent_output())
    directory = log_dir_for(cfg)
    verdict = final_verdict(Path(hook.transcript_path))
    if verdict is None or verdict.score < RECORD_THRESHOLD:
        return HookRun(silent_output())

    _log_quietly(directory, verdict, hook)
    decision = decide(
        verdict.score,
        resume_on_stop=cfg.resume_on_stop,
        stop_hook_active=hook.stop_hook_active,
        blocks_used=blocks_used(directory, hook.session_id),
        max_blocks=cfg.max_blocks_per_session,
        notify_min=cfg.suspicious_threshold,
        block_min=cfg.threshold,
        message=summary(verdict),
        reason=block_reason(verdict),
    )
    if decision.blocked:
        record_block(directory, hook.session_id)
    return HookRun(decision.output, decision.blocked, verdict)


def summary(verdict: Verdict) -> str:
    """One line for the user. Deliberately excludes transcript text."""
    evidence = "；".join(verdict.evidence) or "-"
    return (
        f"ClaudeCode Watchdog: 疑似中断 {verdict.classification} score={verdict.score} "
        f"—— {evidence}（ccw last 可复核；需要自动续跑请设 resume_on_stop）"
    )


def block_reason(verdict: Verdict) -> str:
    """Fed back to Claude as ``Stop hook feedback`` when we block a Stop."""
    prefix = f"ClaudeCode Watchdog 判定上一轮为 {verdict.classification}（score={verdict.score}）。"
    return prefix + resume_prompt(verdict.classification == CLASS_REPEATED_EMPTY)


def _log_quietly(directory: Path, verdict: Verdict, hook: HookInput) -> None:
    try:
        EventLog(directory).emit(
            verdict,
            {"session_id": hook.session_id, "source": "hook", "hook_event": hook.event_name},
        )
    except Exception:
        pass  # read-only filesystem, a file where a directory should be, ...
