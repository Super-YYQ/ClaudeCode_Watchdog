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

SUBCOMMANDS = ("watch", "replay", "status", "doctor", "last", "stop")


def _cfg(args) -> WatchdogConfig:
    cfg = load_config(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "auto_resume", False):
        cfg.auto_resume = True
        cfg.dry_run = False
    if getattr(args, "dry_run", False):
        cfg.dry_run = True
        cfg.auto_resume = False
    return cfg


def normalize_argv(argv: list[str]) -> list[str]:
    """Default a bare invocation to ``watch`` without touching flag order.

    ``watch`` is inserted after the leading global options (``--config X``) and
    before everything else, so ``ccw``, ``ccw --once``, ``ccw --config c.json
    --auto-resume`` all behave the same as their explicit-``watch`` forms.
    """
    if any(token in SUBCOMMANDS for token in argv) or any(t in ("-h", "--help") for t in argv):
        return list(argv)
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--config":
            index += 2
        elif token.startswith("--config="):
            index += 1
        else:
            break
    return [*argv[:index], "watch", *argv[index:]]


def _sessions_from(args, cfg: WatchdogConfig) -> list:
    """Resolve ``--project`` / ``--any-project`` / cwd into candidate sessions."""
    if getattr(args, "project", None):
        return discover_sessions(cfg.projects_dir, project=args.project)
    if getattr(args, "any_project", False):
        return discover_sessions(cfg.projects_dir)
    return discover_sessions(cfg.projects_dir, Path.cwd())


def _print_ambiguous(exc: AmbiguousSession) -> None:
    print("AMBIGUOUS_SESSION; 30 秒内有多个会话被写过，选一个：")
    for item in exc.hits:
        print(f'  ccw watch --session {item.session_id}   # {item.project}')


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
    hits = _sessions_from(args, cfg)
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


def cmd_last(args) -> int:
    """One-command triage: newest session -> full replay -> only suspicious events."""
    cfg = _cfg(args)
    hits = _sessions_from(args, cfg)
    if not hits and not args.project and not args.any_project:
        # nothing for this cwd; "last" means last *anywhere*, so widen the search
        hits = discover_sessions(cfg.projects_dir)
    if not hits:
        print("no session found（试一下 --any-project 或 --project <片段>）")
        return 2
    hit = hits[0]
    print(f"session {hit.session_id}  project={hit.project}  {hit.path}")
    verdicts = replay_path(hit.path)
    shown = [v for v in verdicts if v.score >= cfg.suspicious_threshold]
    print(format_verdicts(shown) or f"(no event >= {cfg.suspicious_threshold})")
    print(f"\n{len(verdicts)} interesting events, {len(shown)} score>={cfg.suspicious_threshold}")
    print(f'等价长命令：ccw replay "{hit.path}"')
    print(f"实时守护这一个会话：ccw watch --session {hit.session_id}")
    return 0


def cmd_watch(args) -> int:
    cfg = _cfg(args)
    hits = _sessions_from(args, cfg)
    if not hits:
        print("no session found（当前目录没有会话；试一下 --any-project 或 --project <片段>）")
        return 2
    try:
        hit = pick_session(hits, args.session)
    except AmbiguousSession as exc:
        _print_ambiguous(exc)
        return 2
    print(f"watching {hit.path} dry_run={cfg.dry_run}")
    reader = IncrementalJsonlReader(hit.path)
    # catch up without scoring the entire history unless --from-start
    if not args.from_start:
        reader.read_new()
    machine = SessionStateMachine()
    breaker = CircuitBreaker(max_failures=cfg.max_auto_resumes)
    log_dir = Path(args.log_dir) if args.log_dir else (cfg.log_dir or Path.cwd() / ".ccs-watchdog")
    log = EventLog(log_dir)
    min_score = args.min_score if args.min_score is not None else 30
    last_emit = None
    while True:
        records = reader.read_new()
        for record in records:
            event = normalize_record(record)
            snap = machine.apply(event)
            verdict = score_event(event, snap)
            if verdict.score >= min_score:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccw",
        description="ClaudeCode Watchdog —— 无参数即开始守护当前项目最近的会话。",
        epilog="常用：ccw doctor / ccw last / ccw（= ccw watch）。ccs-watchdog 是等价长命令。",
    )
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command")

    def add_config(target: argparse.ArgumentParser) -> None:
        # SUPPRESS so an absent value never clobbers the top-level --config;
        # this lets users write `ccw doctor --config x.json` as well as
        # `ccw --config x.json doctor`.
        target.add_argument("--config", default=argparse.SUPPRESS)

    def add_shared(target: argparse.ArgumentParser) -> None:
        add_config(target)
        target.add_argument("--project", default=None, help="按项目目录名片段过滤会话")
        target.add_argument("--any-project", action="store_true", help="跨所有项目查找会话")

    p_watch = sub.add_parser("watch", help="实时守护（默认子命令）")
    add_shared(p_watch)
    p_watch.add_argument("--session")
    p_watch.add_argument("--dry-run", action="store_true")
    p_watch.add_argument("--auto-resume", action="store_true")
    p_watch.add_argument("--from-start", action="store_true")
    p_watch.add_argument("--once", action="store_true")
    p_watch.add_argument("--log-dir")
    p_watch.add_argument("--min-score", type=int, default=None)
    p_watch.set_defaults(func=cmd_watch)

    p_last = sub.add_parser("last", help="复盘最近一个会话，只列可疑事件")
    add_shared(p_last)
    p_last.set_defaults(func=cmd_last)

    p_replay = sub.add_parser("replay", help="离线复盘一份 transcript")
    p_replay.add_argument("session")
    p_replay.add_argument("--verbose", action="store_true")
    p_replay.set_defaults(func=cmd_replay)

    p_status = sub.add_parser("status", help="查看当前目录最近的 session")
    add_shared(p_status)
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor", help="体检环境与 ccSwitch 路由")
    add_config(p_doctor)
    p_doctor.set_defaults(func=cmd_doctor)

    p_stop = sub.add_parser("stop")
    add_config(p_stop)
    p_stop.set_defaults(func=lambda args: print("no daemon pid file; stop the watch process") or 0)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(normalize_argv(sys.argv[1:] if argv is None else list(argv)))
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
