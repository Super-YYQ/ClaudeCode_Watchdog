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
from ccs_watchdog.hooks.installer import InstallError, default_python, install_hook, uninstall_hook
from ccs_watchdog.hooks.output import silent_output
from ccs_watchdog.hooks.payload import parse_hook_input
from ccs_watchdog.hooks.runner import handle_hook
from ccs_watchdog.logging.writer import EventLog
from ccs_watchdog.provider.ccswitch import read_route_snapshot
from ccs_watchdog.replay.engine import format_verdicts, replay_path
from ccs_watchdog.resume.controller import CircuitBreaker, resume_prompt
from ccs_watchdog.scoring.score import RECORD_THRESHOLD, score_event
from ccs_watchdog.state.machine import SessionStateMachine
from ccs_watchdog.transcript.reader import IncrementalJsonlReader

SUBCOMMANDS = ("watch", "replay", "status", "doctor", "last", "stop", "hook", "install-hook", "uninstall-hook")

HOOK_CLI_EVENTS = ("stop", "subagentstop", "stopfailure")


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
    min_score = args.min_score if args.min_score is not None else RECORD_THRESHOLD
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


def _read_stdin_json():
    """Decode the hook payload; ``None`` for empty/garbage stdin."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def cmd_hook(args) -> int:
    """Entry point Claude Code calls at a turn boundary.

    Contract: always exit 0, always print exactly one JSON object. Anything that
    goes wrong downgrades to "stay silent" -- never to "stall the user's turn".
    """
    output = silent_output()
    try:
        cfg = _cfg(args)
        output = handle_hook(parse_hook_input(_read_stdin_json()), cfg).output
    except Exception:
        output = silent_output()
    print(json.dumps(output, ensure_ascii=False))
    return 0


def _settings_path(args, cfg: WatchdogConfig) -> Path:
    return Path(args.settings) if getattr(args, "settings", None) else cfg.claude_home / "settings.json"


def cmd_install_hook(args) -> int:
    cfg = _cfg(args)
    path = _settings_path(args, cfg)
    config_path = getattr(args, "config", None)
    try:
        result = install_hook(
            path,
            events=list(cfg.hook_events),
            python=args.python or default_python(),
            config_path=config_path,
        )
    except InstallError as exc:
        print(f"安装失败：{exc}")
        return 2
    if not result.changed:
        print(f"已经装过了，未做改动：{path}")
        return 0
    print(f"已写入 {path}")
    if result.backup_path:
        print(f"原文件已备份：{result.backup_path}")
    print(f"已注册事件：{', '.join(result.installed)}")
    if config_path:
        print(f"已把配置路径写进 hook 命令：{config_path}")
    else:
        print("未指定 --config：hook 将使用默认配置（resume_on_stop=false，只记录并提示）")
    print("重启 Claude Code 后生效；之后新开的窗口/会话同样生效，不需要再单独启动 watch。")
    if not cfg.resume_on_stop:
        print("当前 resume_on_stop=false：只记录并提示，不会拦停回合。")
    print("卸载：ccw uninstall-hook（只删本工具写入的条目，其它 hook 不动）")
    return 0


def cmd_uninstall_hook(args) -> int:
    cfg = _cfg(args)
    path = _settings_path(args, cfg)
    try:
        result = uninstall_hook(path)
    except InstallError as exc:
        print(f"卸载失败：{exc}")
        return 2
    if not result.changed:
        print(f"没有安装记录，未做改动：{path}")
        return 0
    print(f"已从 {path} 移除：{', '.join(result.removed)}")
    if result.backup_path:
        print(f"原文件已备份：{result.backup_path}")
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

    p_hook = sub.add_parser("hook", help="给 Claude Code 的 Stop hook 调用（内部用）")
    add_config(p_hook)
    p_hook.add_argument("event", choices=HOOK_CLI_EVENTS, help="触发的事件名")
    p_hook.set_defaults(func=cmd_hook)

    for name, func, help_text in (
        ("install-hook", cmd_install_hook, "把本工具注册进 ~/.claude/settings.json（可选）"),
        ("uninstall-hook", cmd_uninstall_hook, "移除本工具写入的 hook 条目"),
    ):
        p = sub.add_parser(name, help=help_text)
        add_config(p)
        p.add_argument("--settings", default=None, help="settings.json 路径（默认 ~/.claude/settings.json）")
        p.add_argument("--python", default=None, help="注册用的 python 解释器（默认当前解释器）")
        p.set_defaults(func=func)
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
