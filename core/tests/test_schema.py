from agentguard.schema import (AgentKind, EventIn, EventType, new_event_from,
                               normalize_payload)


def test_event_in_defaults():
    e = EventIn(session_id="s1", type=EventType.session_start, data={})
    assert e.agent == AgentKind.generic
    assert e.ts is None


def test_normalize_llm_payload():
    ev = EventIn(session_id="s", type=EventType.llm_call,
                 data={"model": "gpt-5", "input_tokens": 10, "output_tokens": 5,
                       "cost_usd": 0.001, "iteration": 3, "extra_key": "kept"})
    d = normalize_payload(ev)
    assert d["input_tokens"] == 10
    assert d["extra_key"] == "kept"
    assert set(d) >= {"model", "input_tokens"}


def test_normalize_bad_payload_marks_schema_error():
    ev = EventIn(session_id="s", type=EventType.llm_call, data={"input_tokens": "not-int"})
    d = normalize_payload(ev)
    assert d.get("_schema_error") is True


def test_new_event_from_stamps_ts_and_id():
    out = new_event_from(EventIn(session_id="s", type=EventType.tool_call,
                                 data={"name": "read"}))
    assert out.id.startswith("ev_")
    assert out.ts > 0
    assert out.data["name"] == "read"

    # client-supplied ts preserved
    out2 = new_event_from(EventIn(session_id="s", type=EventType.tool_call,
                                  data={}, ts=123.5))
    assert out2.ts == 123.5
