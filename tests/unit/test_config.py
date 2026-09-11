import json
from dataclasses import fields
from pathlib import Path

import pytest

from ccs_watchdog.config.defaults import FIELD_NAMES, WatchdogConfig, load_config


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "ccw.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_config_converts_path_fields_to_path(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"claude_home": "D:/somewhere/.claude"}))
    assert isinstance(cfg.claude_home, Path)
    assert cfg.claude_home == Path("D:/somewhere/.claude")
    assert cfg.projects_dir == Path("D:/somewhere/.claude") / "projects"


def test_load_config_path_fields_stay_usable_with_slash_operator(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"ccswitch_home": "D:/cc-switch", "log_dir": str(tmp_path)}))
    assert isinstance(cfg.log_dir, Path)
    assert (cfg.ccswitch_home / "config.json").parent.name == "cc-switch"


def test_load_config_ignores_read_only_properties(tmp_path: Path):
    with pytest.warns(UserWarning, match="projects_dir"):
        cfg = load_config(_write(tmp_path, {"projects_dir": "D:/nope"}))
    assert cfg.projects_dir == WatchdogConfig().projects_dir


def test_load_config_warns_but_does_not_crash_on_unknown_keys(tmp_path: Path):
    with pytest.warns(UserWarning, match="threshold2"):
        cfg = load_config(_write(tmp_path, {"threshold2": 90, "threshold": 50}))
    assert cfg.threshold == 50


def test_field_names_lists_writable_fields_only():
    writable = {f.name for f in fields(WatchdogConfig)}
    assert "projects_dir" not in FIELD_NAMES
    assert set(FIELD_NAMES) == writable


def test_boolean_and_int_fields_keep_their_types(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"dry_run": False, "threshold": 55, "idle_grace_seconds": 3.5}))
    assert cfg.dry_run is False
    assert cfg.threshold == 55
    assert cfg.idle_grace_seconds == 3.5
