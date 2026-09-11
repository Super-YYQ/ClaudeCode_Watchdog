"""Config fields the hook channel reads (all off-by-default)."""
import json
from pathlib import Path

from ccs_watchdog.config.defaults import WatchdogConfig, load_config


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "ccw.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_hook_defaults_are_conservative():
    cfg = WatchdogConfig()
    assert cfg.resume_on_stop is False
    assert cfg.max_blocks_per_session == 2
    assert cfg.hook_events == ["Stop", "SubagentStop"]
    assert cfg.hook_log_dir is None


def test_resume_on_stop_is_loadable(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"resume_on_stop": True, "max_blocks_per_session": 1}))
    assert cfg.resume_on_stop is True
    assert cfg.max_blocks_per_session == 1


def test_hook_log_dir_is_a_path_field(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"hook_log_dir": "D:/hooks/log"}))
    assert isinstance(cfg.hook_log_dir, Path)
    assert cfg.hook_log_dir == Path("D:/hooks/log")


def test_hook_events_are_loadable(tmp_path: Path):
    cfg = load_config(_write(tmp_path, {"hook_events": ["Stop", "SubagentStop", "StopFailure"]}))
    assert cfg.hook_events == ["Stop", "SubagentStop", "StopFailure"]
