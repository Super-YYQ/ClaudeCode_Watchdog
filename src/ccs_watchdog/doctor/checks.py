from __future__ import annotations

import shutil
from pathlib import Path

from ccs_watchdog.config.defaults import WatchdogConfig
from ccs_watchdog.discovery.sessions import discover_sessions
from ccs_watchdog.hooks.installer import hook_status
from ccs_watchdog.provider.ccswitch import read_route_snapshot


def doctor_report(cfg: WatchdogConfig, cwd: Path | None = None) -> dict:
    claude = shutil.which("claude")
    sessions = discover_sessions(cfg.projects_dir, cwd)
    settings_path = cfg.claude_home / "settings.json"
    route = read_route_snapshot(cfg.ccswitch_home, settings_path)
    return {
        "claude_path": claude,
        "claude_home": str(cfg.claude_home),
        "projects_dir_exists": cfg.projects_dir.exists(),
        "session_count": len(sessions),
        "newest_session": sessions[0].session_id if sessions else None,
        "python_ok": True,
        "routing_enabled": route.routing_enabled,
        "listen": route.listen,
        "provider": route.current_provider_name,
        "ccswitch_version": route.ccswitch_version,
        "base_url_host": route.base_url_host,
        "dry_run": cfg.dry_run,
        "hook_installed": hook_status(settings_path),
        "hook_settings_path": str(settings_path),
        "resume_on_stop": cfg.resume_on_stop,
    }
