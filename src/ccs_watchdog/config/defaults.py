from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, fields, field
from pathlib import Path
from typing import Any


@dataclass
class WatchdogConfig:
    dry_run: bool = True
    auto_resume: bool = False
    threshold: int = 80
    suspicious_threshold: int = 60
    max_auto_resumes: int = 3
    cooldown_seconds: int = 10
    empty_consecutive_threshold: int = 2
    idle_grace_seconds: float = 2.0
    claude_home: Path = field(default_factory=lambda: Path.home() / ".claude")
    ccswitch_home: Path = field(default_factory=lambda: Path.home() / ".cc-switch")
    redact_secrets: bool = True
    log_dir: Path | None = None
    # --- hook channel (opt-in; see hooks/installer.py) ---
    resume_on_stop: bool = False
    max_blocks_per_session: int = 2
    hook_events: list[str] = field(default_factory=lambda: ["Stop", "SubagentStop"])
    hook_log_dir: Path | None = None

    @property
    def projects_dir(self) -> Path:
        return self.claude_home / "projects"


PATH_FIELDS = frozenset({"claude_home", "ccswitch_home", "log_dir", "hook_log_dir"})
FIELD_NAMES = tuple(f.name for f in fields(WatchdogConfig))


def load_config(path: Path | None = None) -> WatchdogConfig:
    cfg = WatchdogConfig()
    if not path or not path.exists():
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    known = set(FIELD_NAMES)
    for key, value in data.items():
        if key not in known:
            warnings.warn(f"忽略未知配置项 {key!r}（可用项：{', '.join(FIELD_NAMES)}）", UserWarning, stacklevel=2)
            continue
        setattr(cfg, key, _coerce(key, value))
    return cfg


def _coerce(key: str, value: Any) -> Any:
    if key in PATH_FIELDS:
        return Path(value) if value is not None else None
    return value
