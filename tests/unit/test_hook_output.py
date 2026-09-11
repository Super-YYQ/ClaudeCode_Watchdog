"""The stdout a hook returns, and the pure decision of what to return.

Output field names verified against the CLI bundle: ``decision:"block"`` +
``reason`` blocks a Stop and feeds ``reason`` back to Claude; ``systemMessage``
is shown to the user; ``suppressOutput`` hides our stdout from the transcript.
Blocking is gated so a bug can never trap the user in a turn.
"""
from ccs_watchdog.hooks.output import block_output, decide, notify_output, silent_output


def _decide(score, **kw):
    base = dict(
        resume_on_stop=False,
        stop_hook_active=False,
        blocks_used=0,
        max_blocks=2,
        notify_min=60,
        block_min=80,
        message="msg",
        reason="reason",
    )
    base.update(kw)
    return decide(score, **base)


def test_low_score_is_silent():
    d = _decide(40)
    assert d.blocked is False
    assert "systemMessage" not in d.output
    assert "decision" not in d.output
    assert d.output.get("suppressOutput") is True


def test_suspicious_score_notifies_without_blocking():
    d = _decide(60)
    assert d.blocked is False
    assert d.output["systemMessage"] == "msg"
    assert "decision" not in d.output


def test_high_score_blocks_when_resume_enabled():
    d = _decide(90, resume_on_stop=True)
    assert d.blocked is True
    assert d.output["decision"] == "block"
    assert d.output["reason"] == "reason"


def test_high_score_only_notifies_when_resume_disabled():
    d = _decide(90, resume_on_stop=False)
    assert d.blocked is False
    assert "decision" not in d.output
    assert d.output["systemMessage"] == "msg"


def test_stop_hook_active_never_blocks_but_still_notifies():
    d = _decide(90, resume_on_stop=True, stop_hook_active=True)
    assert d.blocked is False
    assert "decision" not in d.output
    assert d.output["systemMessage"] == "msg"


def test_block_budget_exhausted_falls_back_to_notify():
    d = _decide(90, resume_on_stop=True, blocks_used=2, max_blocks=2)
    assert d.blocked is False
    assert "decision" not in d.output
    assert d.output["systemMessage"] == "msg"


def test_notify_output_shape():
    out = notify_output("hello")
    assert out["systemMessage"] == "hello"
    assert out["suppressOutput"] is True


def test_block_output_shape():
    out = block_output("go on")
    assert out["decision"] == "block"
    assert out["reason"] == "go on"


def test_silent_output_shape():
    assert silent_output() == {"suppressOutput": True}
