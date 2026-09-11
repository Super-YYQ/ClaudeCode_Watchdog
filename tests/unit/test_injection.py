"""Injected / meta transcript turns must not be mistaken for real conversation.

When a Stop hook blocks a turn, Claude Code writes a ``type=user, isMeta=true``
record whose text starts with ``Stop hook feedback:``. Compaction writes an
``isCompactSummary`` user record. Neither is something the human typed, so they
must not clear ``awaiting_user`` (via USER_PROMPT) nor have their text read as an
assistant "promise" (``future_action``). The hook path also needs to find the
last *real* assistant turn, skipping these.
"""
from ccs_watchdog.events.normalize import last_real_assistant, normalize_record


def test_stop_hook_feedback_is_injected_not_a_prompt():
    rec = {
        "type": "user",
        "isMeta": True,
        "message": {"role": "user", "content": "Stop hook feedback:\n[design-not-done]: keep going"},
    }
    event = normalize_record(rec)
    assert event.injected is True
    assert event.kind == "META"


def test_session_scoped_hook_notice_is_injected():
    rec = {
        "type": "user",
        "isMeta": True,
        "message": {"role": "user", "content": 'A session-scoped Stop hook is now active with condition: "x"'},
    }
    event = normalize_record(rec)
    assert event.injected is True
    assert event.kind == "META"


def test_compact_summary_is_injected_and_never_future_action():
    rec = {
        "type": "user",
        "isCompactSummary": True,
        "message": {"role": "user", "content": "Summary: 接下来让我继续开发下一步，然后运行测试。"},
    }
    event = normalize_record(rec)
    assert event.injected is True
    assert event.kind == "META"
    # the summary text is full of future-action phrases; it must not count as a promise
    assert event.future_action is False


def test_real_typed_prompt_is_not_injected():
    rec = {
        "type": "user",
        "promptSource": "typed",
        "message": {"role": "user", "content": "继续开发方案 C"},
    }
    event = normalize_record(rec)
    assert event.injected is False
    assert event.kind == "USER_PROMPT"


def test_tool_result_is_not_flagged_injected():
    rec = {
        "type": "user",
        "toolUseResult": {"stdout": "ok"},
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}]},
    }
    event = normalize_record(rec)
    assert event.injected is False
    assert event.kind == "TOOL_RESULT"


def test_last_real_assistant_skips_injected_tail():
    records = [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "real answer"}], "stop_reason": "end_turn"}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n[x]: go on"}},
    ]
    events = [normalize_record(r) for r in records]
    found = last_real_assistant(events)
    assert found is not None
    assert found.text == "real answer"


def test_last_real_assistant_returns_none_without_assistant():
    events = [normalize_record({"type": "user", "promptSource": "typed", "message": {"role": "user", "content": "hi"}})]
    assert last_real_assistant(events) is None
