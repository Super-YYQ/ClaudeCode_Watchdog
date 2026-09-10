from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ccs_watchdog import __version__
from ccs_watchdog.config.defaults import WatchdogConfig, load_config
from ccs_watchdog.discovery.sessions import AmbiguousSession, discover_sessions, pick_session
from ccs_watchdog.doctor.checks import doctor_report
from ccs_watchdog.events.normalize import normalize_record
from ccs_watchdog.logging.writer import EventLog
from ccs_watchdog.provider.ccswitch import read_route_snapshot
from ccs_watchdog.replay.engine import format_verdicts, replay_path
from ccs_watchdog.resume.controller import CircuitBreaker, resume_prompt
from ccs_watchdog.scoring.score import score_event
from ccs_watchdog.state.machine import SessionStateMachine
from ccs_watchdog.transcript.reader import IncrementalJsonlReader


def _cfg(args) -> WatchdogConfig:
    cfg = load_config(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "auto_resume", False):
        cfg.auto_resume = True
        cfg.dry_run = False
    if getattr(args, "dry_run", False):
        cfg.dry_run = True
        cfg.auto_resume = False
    return cfg


def cmd_doctor(args) -> int:
    report = doctor_report(_cfg(args), Path.cwd())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_replay(args) -> int:
    path = Path(args.session)
    verdicts = replay_path(path)
    print(format_verdicts(verdicts) or "(no interesting verdicts)")
    interesting = [v for v in verdicts if v.score >= 60]
    print(f"\n{len(verdicts)} interesting events, {len(interesting)} score>=60")
    return 0


def cmd_status(args) -> int:
    cfg = _cfg(args)
    hits = discover_sessions(cfg.projects_dir, Path.cwd())
    route = read_route_snapshot(cfg.ccswitch_home, cfg.claude_home / "settings.json")
    print(json.dumps({
        "watchdog_version": __version__,
        "dry_run": cfg.dry_run,
        "newest_session": hits[0].session_id if hits else None,
        "session_path": str(hits[0].path) if hits else None,
        "routing_enabled": route.routing_enabled,
        "listen": route.listen,
        "provider": route.current_provider_name,
        "ccswitch_version": route.ccswitch_version,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_watch(args) -> int:
    cfg = _cfg(args)
    hits = discover_sessions(cfg.projects_dir, Path.cwd())
    try:
        hit = pick_session(hits, args.session)
    except AmbiguousSession as exc:
        print("AMBIGUOUS_SESSION; pass --session with one of:")
        for item in exc.hits:
            print(" ", item.session_id, item.path)
        return 2
    print(f"watching {hit.path} dry_run={cfg.dry_run}")
    reader = IncrementalJsonlReader(hit.path)
    # catch up without scoring the entire history unless --from-start
    if not args.from_start:
        reader.read_new()
    machine = SessionStateMachine()
    breaker = CircuitBreaker(max_failures=cfg.max_auto_resumes)
    log = EventLog(Path(args.log_dir) if args.log_dir else Path.cwd() / ".ccs-watchdog")
    last_emit = None
    while True:
        records = reader.read_new()
        for record in records:
            event = normalize_record(record)
            snap = machine.apply(event)
            verdict = score_event(event, snap)
            if verdict.score >= 30:
                fingerprint = (verdict.classification, verdict.uuid, verdict.score)
                if fingerprint != last_emit:
                    log.emit(verdict, {"session_id": hit.session_id})
                    last_emit = fingerprint
                    print(f"{verdict.classification} score={verdict.score} {'; '.join(verdict.evidence)}")
                    if cfg.auto_resume and verdict.score >= cfg.threshold and breaker.allow():
                        if verdict.recommended_action == "manual_review":
                            print("manual_review: not auto-resuming")
                        else:
                            print("auto-resume is experimental; prompt would be:")
                            print(resume_prompt(verdict.classification == "REPEATED_EMPTY_RESPONSE"))
                            breaker.record(False)
        if args.once:
            break
        time.sleep(0.5)
    return 0


def main(argv: list[str] | None = None) -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="ccs-watchdog")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--session")
    p_watch.add_argument("--dry-run", action="store_true")
    p_watch.add_argument("--auto-resume", action="store_true")
    p_watch.add_argument("--from-start", action="store_true")
    p_watch.add_argument("--once", action="store_true")
    p_watch.add_argument("--log-dir")
    p_watch.set_defaults(func=cmd_watch)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("session")
    p_replay.add_argument("--verbose", action="store_true")
    p_replay.set_defaults(func=cmd_replay)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor")
    p_doctor.set_defaults(func=cmd_doctor)

    sub.add_parser("stop").set_defaults(func=lambda args: print("no daemon pid file; stop the watch process") or 0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
