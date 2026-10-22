import time

from conftest import make_event


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


def test_reset_clears_usage_but_keeps_limits(tmp_db):
    from agentguard.config import Config
    from agentguard.breaker.service import CircuitBreaker
    from agentguard.store import Store
    from agentguard.schema import AgentKind, Event, EventType

    br = CircuitBreaker(Config.load().breaker, Store(tmp_db), None)
    br.config.on_breach = "alert"
    sid = _sid()
    br.observe_event(make_event(sid, EventType.session_start))
    br.set_session_limits(sid, {"max_tokens": 50_000_000})
    br.observe_event(make_event(sid, EventType.llm_call, input_tokens=300, output_tokens=100))
    assert br.sessions[sid].input_tokens == 300 and br.sessions[sid].output_tokens == 100

    br.reset(sid)
    st = br.sessions[sid]
    assert st.status == "healthy"
    assert st.input_tokens == 0 and st.output_tokens == 0
    assert st.tool_calls == 0 and st.llm_calls == 0
    assert st.limits["max_tokens"] == 50_000_000  # override preserved


def test_overrides_persist_across_service_restart(tmp_db):
    from agentguard.config import Config
    from agentguard.breaker.service import CircuitBreaker
    from agentguard.store import Store
    from agentguard.schema import AgentKind, Event, EventType

    store = Store(tmp_db)
    br = CircuitBreaker(Config.load().breaker, store, None)
    sid = _sid()
    br.observe_event(make_event(sid, EventType.session_start))
    br.set_session_limits(sid, {"max_tokens": 77_000, "max_wall_seconds": 9999})

    # simulate a service restart: brand-new breaker instance, same store
    br2 = CircuitBreaker(Config.load().breaker, store, None)
    br2.observe_event(make_event(sid, EventType.tool_call,
                                 name="read", args_digest="k", status="success"))
    st = br2.sessions[sid]
    assert st.limits["max_tokens"] == 77_000
    assert st.limits["max_wall_seconds"] == 9999
