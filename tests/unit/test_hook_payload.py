"""Parsing the JSON Claude Code pipes to a hook on stdin.

Field names verified against the CLI 2.1.268 bundle's zod schemas for
Stop / SubagentStop / StopFailure. Parsing must never raise on a missing or
malformed field -- a hook that crashes would stall the user's turn.
"""
from ccs_watchdog.hooks.payload import parse_hook_input


def test_parses_a_stop_payload():
    data = {
        "hook_event_name": "Stop",
        "session_id": "abc",
        "transcript_path": "C:/x/abc.jsonl",
        "cwd": "C:/x",
        "stop_hook_active": False,
        "last_assistant_message": "I'll continue.",
    }
    hook = parse_hook_input(data)
    assert hook is not None
    assert hook.event_name == "Stop"
    assert hook.session_id == "abc"
    assert hook.transcript_path == "C:/x/abc.jsonl"
    assert hook.last_assistant_message == "I'll continue."
    assert hook.stop_hook_active is False


def test_missing_optional_fields_do_not_crash():
    hook = parse_hook_input({"hook_event_name": "Stop"})
    assert hook is not None
    assert hook.session_id is None
    assert hook.transcript_path is None
    assert hook.last_assistant_message is None
    assert hook.stop_hook_active is False


def test_stop_hook_active_true_is_read():
    hook = parse_hook_input({"hook_event_name": "Stop", "stop_hook_active": True})
    assert hook.stop_hook_active is True


def test_unknown_event_returns_none():
    assert parse_hook_input({"hook_event_name": "PreToolUse"}) is None
    assert parse_hook_input({}) is None
    assert parse_hook_input("not a dict") is None


def test_stopfailure_carries_error():
    hook = parse_hook_input({"hook_event_name": "StopFailure", "error": "boom", "last_assistant_message": "x"})
    assert hook.event_name == "StopFailure"
    assert hook.error == "boom"
