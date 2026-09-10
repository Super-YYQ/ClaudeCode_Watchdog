from ccs_watchdog.resume.controller import CircuitBreaker, resume_prompt


def test_circuit_breaker():
    br = CircuitBreaker(max_failures=3)
    assert br.allow()
    br.record(False); br.record(False); br.record(False)
    assert not br.allow()
    br.record(True)
    assert br.allow()


def test_resume_prompt_mentions_no_repeat():
    assert "不要重复" in resume_prompt()
    assert "空 assistant" in resume_prompt(empty=True)
