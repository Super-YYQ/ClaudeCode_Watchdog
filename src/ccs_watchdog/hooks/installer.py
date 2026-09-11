"""Install / remove our hook entries in ``~/.claude/settings.json``.

Design rules (all pinned by tests/unit/test_hook_installer.py):

* **append only** -- Claude Code's shape is ``hooks.<Event> = [group, ...]`` where
  a group is ``{"matcher"?: str, "hooks": [{type, command, args, ...}]}``. We add
  one more group and never touch anybody else's.
* **refuse, don't repair** -- unparseable JSON or an unexpected structure raises
  :class:`InstallError` and leaves the file byte-identical.
* **back up before writing** -- ``settings.json.bak-<timestamp>``.
* **idempotent** -- our group is recognised by a marker, so re-installing is a
  no-op with no backup and no write.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HOOK_EVENTS = ("Stop", "SubagentStop", "StopFailure")

#: Appears inside the ``-c`` bootstrap we register, which is how we recognise
#: our own entries again (and never a third-party one).
MARKER = "ccs_watchdog.cli.main"

BOOTSTRAP = (
    'import sys; sys.path.insert(0, r"{root}"); '
    "from ccs_watchdog.cli.main import main; sys.exit(main())"
)


class InstallError(Exception):
    """Raised instead of writing a settings.json we do not fully understand."""


@dataclass
class InstallResult:
    changed: bool = False
    settings_path: Path | None = None
    backup_path: Path | None = None
    installed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def default_python() -> str:
    return sys.executable or "python"


def default_package_root() -> str:
    """The directory to put on ``sys.path`` so ``ccs_watchdog`` imports."""
    import ccs_watchdog

    return str(Path(ccs_watchdog.__file__).resolve().parents[1])


def command_args(event: str, package_root: str, config_path: str | None = None) -> list[str]:
    """argv appended after the interpreter; argv[0] of ``-c`` is the script name.

    ``config_path`` is baked in because a hook is launched by Claude Code with a
    bare argv -- without it the hook would silently fall back to default config
    (and ``resume_on_stop`` would never take effect).
    """
    args = ["-c", BOOTSTRAP.format(root=package_root), "hook", event.lower()]
    if config_path:
        args += ["--config", config_path]
    return args


def entry_for(event: str, python: str, package_root: str, timeout: int, config_path: str | None) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": python,
                "args": command_args(event, package_root, config_path),
                "timeout": timeout,
            }
        ]
    }


def is_ours(group: object) -> bool:
    """True when a matcher group was written by us (marker anywhere inside)."""
    if not isinstance(group, dict):
        return False
    return MARKER in json.dumps(group, ensure_ascii=False)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallError(f"settings.json 不是合法 JSON，已放弃修改（{exc}）") from exc
    if not isinstance(data, dict):
        raise InstallError("settings.json 顶层不是对象，已放弃修改")
    return data


def _hooks_of(data: dict) -> dict:
    hooks = data.get("hooks")
    if hooks is None:
        hooks = {}
        data["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise InstallError('settings.json 的 "hooks" 不是对象，已放弃修改')
    return hooks


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
        counter += 1
    candidate.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return candidate


def _write(path: Path, data: dict) -> Path | None:
    backup = _backup(path) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


def _groups_for(hooks: dict, event: str) -> list:
    bucket = hooks.get(event)
    if bucket is None:
        bucket = []
        hooks[event] = bucket
    if not isinstance(bucket, list):
        raise InstallError(f'hooks."{event}" 不是数组，已放弃修改')
    return bucket


def install_hook(
    settings_path: Path,
    events: list[str],
    python: str | None = None,
    package_root: str | None = None,
    timeout: int = 15,
    config_path: str | None = None,
) -> InstallResult:
    """Append our Stop-family hook to ``events``; returns what changed."""
    unknown = [name for name in events if name not in HOOK_EVENTS]
    if unknown:
        raise InstallError(
            f"不支持的事件名 event: {', '.join(unknown)}（可选：{', '.join(HOOK_EVENTS)}）"
        )
    path = Path(settings_path)
    python = python or default_python()
    root = package_root or default_package_root()
    data = _load(path)
    hooks = _hooks_of(data)

    added = False
    for event in events:
        bucket = _groups_for(hooks, event)
        entry = entry_for(event, python, root, timeout, config_path)
        existing = [group for group in bucket if is_ours(group)]
        if existing == [entry]:
            continue
        for group in existing:
            # ours, but stale (e.g. a different --config): replace rather than
            # pile up a second copy
            bucket.remove(group)
            added = True
        bucket.append(entry)
        added = True

    if not added:
        return InstallResult(False, path, None, installed=_installed_events(path))
    backup = _write(path, data)
    return InstallResult(True, path, backup, installed=_installed_events(path))


def uninstall_hook(settings_path: Path) -> InstallResult:
    """Remove only our groups; drop event keys (and ``hooks``) that empty out."""
    path = Path(settings_path)
    if not path.exists():
        return InstallResult(False, path, None, installed=[])
    data = _load(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise InstallError('settings.json 的 "hooks" 不是对象，已放弃修改')

    removed: list[str] = []
    for event in list(hooks):
        bucket = hooks[event]
        if not isinstance(bucket, list):
            continue
        kept = [group for group in bucket if not is_ours(group)]
        if len(kept) == len(bucket):
            continue
        removed.append(event)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not removed:
        return InstallResult(False, path, None, installed=_installed_events(path))
    if not hooks:
        del data["hooks"]
    backup = _write(path, data)
    return InstallResult(True, path, backup, installed=_installed_events(path), removed=removed)


def hook_status(settings_path: Path) -> dict[str, bool]:
    """``{event: installed?}`` -- tolerant, so ``doctor`` never crashes on it."""
    path = Path(settings_path)
    status = {event: False for event in HOOK_EVENTS}
    try:
        data = _load(path)
    except InstallError:
        return status
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return status
    for event in HOOK_EVENTS:
        bucket = hooks.get(event)
        if isinstance(bucket, list):
            status[event] = any(is_ours(group) for group in bucket)
    return status


def _installed_events(path: Path) -> list[str]:
    return [event for event, ok in hook_status(path).items() if ok]
