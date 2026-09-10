from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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

    @property
    def projects_dir(self) -> Path:
        return self.claude_home / "projects"


def load_config(path: Path | None = None) -> WatchdogConfig:
    cfg = WatchdogConfig()
    if path and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg
