from ccs_watchdog.events.normalize import normalize_record
from ccs_watchdog.scoring.score import score_event
from ccs_watchdog.state.machine import SessionStateMachine


def test_empty_assistant():
    event = normalize_record({"type":"assistant","message":{"role":"assistant","content":[],"model":"k3"}})
    assert event.kind == "ASSISTANT_EMPTY" and event.empty_assistant


def test_future_action_end_turn_is_silent():
    rec = {
        "type": "assistant",
        "timestamp": "t",
        "message": {
            "role": "assistant",
            "model": "k3",
            "stop_reason": "end_turn",
            "content": [{"type":"text","text":"空消息连续收到5条了，不猜测意图，继续按方案C开发。正在为镜像功能写测试。"}],
        },
    }
    event = normalize_record(rec)
    snap = SessionStateMachine().apply(event)
    verdict = score_event(event, snap)
    assert verdict.score >= 60
    assert "SILENT" in verdict.classification or verdict.classification == "SUSPECTED_SILENT_INTERRUPTION"


def test_missing_stop_reason_unfinished():
    rec = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "k3",
            "content": [{"type":"text","text":"明白了。多源轮询方案，通过配置项控制。让我看一下前端状态管理和 API 结构，然后开始开发。"}],
        },
    }
    event = normalize_record(rec)
    machine = SessionStateMachine()
    snap = machine.apply(event)
    idle = normalize_record({"type":"system","subtype":"turn_duration","durationMs":185000})
    snap = machine.apply(idle)
    verdict = score_event(idle, snap)
    assert verdict.score >= 60
    assert verdict.classification in {"SUSPECTED_SILENT_INTERRUPTION", "ROUTE_SWITCH_SUSPECTED"}


def test_normal_tool_loop_low_score():
    machine = SessionStateMachine()
    text = normalize_record({"type":"assistant","message":{"role":"assistant","stop_reason":"tool_use","content":[{"type":"text","text":"开始开发方案 C。先读核心文件"},{"type":"tool_use","name":"Bash","id":"1"}]}})
    snap = machine.apply(text)
    verdict = score_event(text, snap)
    assert verdict.classification == "TOOL_RUNNING"
    result = normalize_record({"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"1","content":"ok"}]}})
    machine.apply(result)


def test_secret_redaction():
    from ccs_watchdog.logging.redact import redact
    assert "<redacted>" in redact("Bearer sk-abc123456789")
