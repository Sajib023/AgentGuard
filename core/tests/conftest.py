import time

import pytest

from agentguard.config import Config
from agentguard.db import Database
from agentguard.schema import AgentKind, Event, EventIn, EventType, new_event_from


@pytest.fixture(autouse=True)
def tmp_agentguard_home(tmp_path, monkeypatch):
    """Isolate ~/.agentguard state (access_code, tunnel_url, ...) per test.

    Tests that need their own AGENTGUARD_HOME simply monkeypatch.setenv again.
    """
    monkeypatch.setenv("AGENTGUARD_HOME", str(tmp_path / "agentguard_home"))


@pytest.fixture
def engine_cfg_no_llm() -> Config:
    cfg = Config.load()
    cfg.firewall.llm_guard.enabled = False   # deterministic unit tests, no ollama dependency
    return cfg


@pytest.fixture
def tmp_db(tmp_path) -> Database:
    return Database(tmp_path / "events.db")


def make_event(session_id: str, etype: EventType, agent: str = "opencode", **data) -> Event:
    return Event(
        agent=AgentKind(agent),
        session_id=session_id,
        type=etype,
        ts=ts_now(),
        data=data,
    )


def ts_now() -> float:
    return time.time()
