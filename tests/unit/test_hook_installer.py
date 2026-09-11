"""Editing ~/.claude/settings.json must be surgical and reversible.

The user already runs a third-party notify hook on Stop / StopFailure /
Notification (verified in the real file: matcher-less groups whose ``hooks``
array holds ``{type, command, args, async}``). So installing ours may only
append a new group, must never drop someone else's, must be idempotent, and must
refuse to touch a file it cannot parse.
"""
import json
from pathlib import Path

import pytest

from ccs_watchdog.hooks.installer import (
    InstallError,
    hook_status,
    install_hook,
    uninstall_hook,
)

PY = r"C:\Python313\python.exe"

THIRD_PARTY = {
    "Stop": [
        {
            "hooks": [
                {"type": "command", "command": "pwsh.exe", "args": ["-File", "notify.ps1"], "async": True}
            ]
        }
    ]
}


def _settings(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "settings.json"
    if payload is not None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _our_groups(data: dict, event: str) -> list:
    from ccs_watchdog.hooks.installer import is_ours

    return [g for g in data["hooks"][event] if is_ours(g)]


def _install(path: Path, events=("Stop",)):
    return install_hook(path, events=list(events), python=PY)


# --- installing -------------------------------------------------------------

def test_install_appends_without_touching_the_existing_group(tmp_path: Path):
    path = _settings(tmp_path, {"theme": "dark", "hooks": THIRD_PARTY})
    install_hook(path, events=["Stop"], python=PY)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["hooks"]["Stop"][0] == THIRD_PARTY["Stop"][0]
    assert len(_our_groups(data, "Stop")) == 1
    assert len(data["hooks"]["Stop"]) == 2


def test_install_creates_hooks_and_event_keys_when_absent(tmp_path: Path):
    path = _settings(tmp_path, {"theme": "dark"})
    install_hook(path, events=["Stop", "SubagentStop"], python=PY)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(_our_groups(data, "Stop")) == 1
    assert len(_our_groups(data, "SubagentStop")) == 1
    assert data["theme"] == "dark"


def test_install_works_when_settings_does_not_exist_yet(tmp_path: Path):
    path = _settings(tmp_path)
    install_hook(path, events=["Stop"], python=PY)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(_our_groups(data, "Stop")) == 1


def test_install_is_idempotent(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": THIRD_PARTY})
    install_hook(path, events=["Stop"], python=PY)
    before = path.read_text(encoding="utf-8")
    result = install_hook(path, events=["Stop"], python=PY)
    assert len(_our_groups(json.loads(path.read_text(encoding="utf-8")), "Stop")) == 1
    assert result.changed is False
    assert path.read_text(encoding="utf-8") == before


def test_install_backs_up_before_writing(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": THIRD_PARTY})
    result = install_hook(path, events=["Stop"], python=PY)
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert json.loads(result.backup_path.read_text(encoding="utf-8")) == {"hooks": THIRD_PARTY}


def test_installed_entry_runs_this_package(tmp_path: Path):
    path = _settings(tmp_path, {})
    install_hook(path, events=["Stop"], python=PY)
    data = json.loads(path.read_text(encoding="utf-8"))
    hook = _our_groups(data, "Stop")[0]["hooks"][0]
    assert hook["type"] == "command"
    assert hook["command"] == PY
    assert "hook" in hook["args"] and "stop" in hook["args"]
    assert "\n" not in " ".join(hook["args"])  # single-line args survive JSON editing


# --- the registered command must carry the user's config --------------------

def _our_args(path: Path, event: str = "Stop") -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _our_groups(data, event)[0]["hooks"][0]["args"]


def test_install_bakes_in_the_config_path_when_given(tmp_path: Path):
    path = _settings(tmp_path, {})
    install_hook(path, events=["Stop"], python=PY, config_path="D:/cfg/ccw.json")
    args = _our_args(path)
    assert "--config" in args
    assert args[args.index("--config") + 1] == "D:/cfg/ccw.json"


def test_install_omits_the_config_flag_when_not_given(tmp_path: Path):
    path = _settings(tmp_path, {})
    install_hook(path, events=["Stop"], python=PY)
    assert "--config" not in _our_args(path)


def test_reinstall_with_a_different_config_replaces_our_entry(tmp_path: Path):
    path = _settings(tmp_path, {})
    install_hook(path, events=["Stop"], python=PY, config_path="D:/cfg/old.json")
    result = install_hook(path, events=["Stop"], python=PY, config_path="D:/cfg/new.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(_our_groups(data, "Stop")) == 1
    assert _our_args(path)[-1] == "D:/cfg/new.json"
    assert result.changed is True


# --- refusing to damage the file -------------------------------------------

def test_install_refuses_to_parse_broken_json(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"hooks": {', encoding="utf-8")
    with pytest.raises(InstallError, match="JSON"):
        install_hook(path, events=["Stop"], python=PY)
    assert path.read_text(encoding="utf-8") == '{"hooks": {'


def test_install_refuses_a_non_dict_hooks_value(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": ["nope"]})
    with pytest.raises(InstallError, match="hooks"):
        install_hook(path, events=["Stop"], python=PY)
    assert json.loads(path.read_text(encoding="utf-8")) == {"hooks": ["nope"]}


def test_install_refuses_a_non_list_event_value(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": {"Stop": {"hooks": []}}})
    with pytest.raises(InstallError, match="Stop"):
        install_hook(path, events=["Stop"], python=PY)


def test_install_refuses_an_unknown_event_name(tmp_path: Path):
    path = _settings(tmp_path, {})
    with pytest.raises(InstallError, match="event"):
        install_hook(path, events=["PreToolUse"], python=PY)


# --- uninstalling -----------------------------------------------------------

def test_uninstall_removes_only_our_group(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": THIRD_PARTY})
    install_hook(path, events=["Stop"], python=PY)
    result = uninstall_hook(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert _our_groups(data, "Stop") == []
    assert data["hooks"]["Stop"] == THIRD_PARTY["Stop"]
    assert "Stop" in result.removed


def test_uninstall_drops_the_event_key_when_it_becomes_empty(tmp_path: Path):
    path = _settings(tmp_path, {})
    install_hook(path, events=["Stop"], python=PY)
    uninstall_hook(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("hooks", {}) == {}


def test_uninstall_keeps_unrelated_events(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": {"Notification": THIRD_PARTY["Stop"]}})
    install_hook(path, events=["Stop"], python=PY)
    uninstall_hook(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"]["Notification"] == THIRD_PARTY["Stop"]


def test_uninstall_is_a_noop_when_not_installed(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": THIRD_PARTY})
    before = path.read_text(encoding="utf-8")
    result = uninstall_hook(path)
    assert result.changed is False
    assert result.removed == []
    assert path.read_text(encoding="utf-8") == before


def test_uninstall_on_a_missing_file_is_a_noop(tmp_path: Path):
    result = uninstall_hook(tmp_path / "settings.json")
    assert result.changed is False


# --- status -----------------------------------------------------------------

def test_hook_status_reports_per_event(tmp_path: Path):
    path = _settings(tmp_path, {"hooks": THIRD_PARTY})
    install_hook(path, events=["Stop"], python=PY)
    status = hook_status(path)
    assert status["Stop"] is True
    assert status["SubagentStop"] is False


def test_hook_status_on_missing_file(tmp_path: Path):
    status = hook_status(tmp_path / "settings.json")
    assert status["Stop"] is False
