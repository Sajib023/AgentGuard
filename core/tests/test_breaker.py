import time


def _sid() -> str:
    return f"s{int(time.time() * 1000) % 10**9}"


def test_loop_detection_fires(tmp_db):
    from agentguard.config import Config
    from agentguard.breaker.service import CircuitBreaker
    from agentguard.schema import AgentKind, Event, EventType

    br = CircuitBreaker(Config.load().breaker, None, None)
    br.config.on_breach = "alert"
    sid = _sid()
    start = Event(agent=AgentKind.opencode, session_id=sid,
                  type=EventType.session_start, data={})
    for d in br.observe_event(start):
        assert d is not None if d else True
    for _ in range(3):
        ev = Event(agent=AgentKind.opencode, session_id=sid, type=EventType.tool_call,
                   data={"name": "grep", "args_digest": "xyz", "status": "success"})
        derived = br.observe_event(ev)
        if derived:
            assert derived[0].data["metric"] == "loop"
            return
    pytest.fail("loop detector never fired after 3 identical tool calls")


def test_token_budget_warning_and_stop(tmp_db):
    from agentguard.config import Config
    from agentguard.breaker.service import CircuitBreaker
    from agentguard.schema import AgentKind, Event, EventType

    br = CircuitBreaker(Config.load().breaker, None, None)
    br.config.on_breach = "alert"
    sid = _sid()
    br.observe_event(Event(agent=AgentKind.opencode, session_id=sid,
                           type=EventType.session_start, data={}))
    br.sessions[sid].limits["max_tokens"] = 1000
    warned = stopped = False
    for i in range(6):
        for d in br.observe_event(Event(agent=AgentKind.opencode, session_id=sid,
                                        type=EventType.llm_call,
                                        data={"input_tokens": 300, "iteration": i})):
            if d.type is EventType.breaker_alert:
                warned = True
            if d.type is EventType.breaker_stop:
                stopped = True
    assert warned and stopped


def test_kill_refuses_unknown_pid(tmp_db):
    from agentguard.config import Config
    from agentguard.breaker.service import CircuitBreaker
    from agentguard.schema import AgentKind, Event, EventType

    br = CircuitBreaker(Config.load().breaker, None, None)
    br.config.on_breach = "kill"
    sid = _sid()
    br.observe_event(Event(agent=AgentKind.codex, session_id=sid,
                           type=EventType.session_start, data={"pid": 9999999}))
    st = br.sessions[sid]
    st.limits["max_tokens"] = 1
    st.input_tokens = 10
    events = br._check_budgets(st)
    stops = [e for e in events if e.type is EventType.breaker_stop]
    assert stops and stops[0].data["result"] in ("refused_not_agent_pid", "failed")
