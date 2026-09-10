from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class RouteSnapshot:
    routing_enabled: bool | None = None
    listen: str | None = None
    current_provider_id: str | None = None
    current_provider_name: str | None = None
    live_takeover_active: bool | None = None
    ccswitch_version: str | None = None
    base_url_host: str | None = None


def mask_provider(provider_id: str | None) -> str | None:
    if not provider_id:
        return None
    if len(provider_id) <= 12:
        return provider_id
    return provider_id[:8] + "…" + provider_id[-4:]


def read_route_snapshot(ccswitch_home: Path, claude_settings: Path | None = None) -> RouteSnapshot:
    snap = RouteSnapshot()
    settings = ccswitch_home / "settings.json"
    if settings.exists():
        data = json.loads(settings.read_text(encoding="utf-8"))
        snap.routing_enabled = bool(data.get("enableLocalProxy"))
        snap.current_provider_id = mask_provider(data.get("currentProviderClaude"))
    db = ccswitch_home / "cc-switch.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT proxy_enabled, listen_address, listen_port, live_takeover_active FROM proxy_config WHERE app_type='claude'"
            ).fetchone()
            if row:
                snap.routing_enabled = bool(row[0] and row[0] != 0)
                snap.listen = f"{row[1]}:{row[2]}"
                snap.live_takeover_active = bool(row[3])
            name_row = None
            if data_id := None:
                pass
            raw_id = None
            if settings.exists():
                raw_id = json.loads(settings.read_text(encoding="utf-8")).get("currentProviderClaude")
            if raw_id:
                name_row = con.execute("SELECT name FROM providers WHERE id=?", (raw_id,)).fetchone()
                if name_row:
                    snap.current_provider_name = name_row[0]
        finally:
            con.close()
    crash = ccswitch_home / "crash.log"
    if crash.exists():
        text = crash.read_text(encoding="utf-8", errors="replace")[:2000]
        for line in text.splitlines():
            if line.startswith("App Version:"):
                snap.ccswitch_version = line.split(":", 1)[1].strip()
                break
    if claude_settings and claude_settings.exists():
        env = json.loads(claude_settings.read_text(encoding="utf-8")).get("env") or {}
        base = env.get("ANTHROPIC_BASE_URL")
        if base:
            parsed = urlsplit(base)
            snap.base_url_host = parsed.hostname
            if parsed.port:
                snap.listen = snap.listen or f"{parsed.hostname}:{parsed.port}"
    return snap
