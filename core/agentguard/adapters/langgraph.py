"""LangGraph / LangChain instrumentation → AgentGuard event schema.

Attach as a callback handler and everything (nodes, transitions, LLM token
usage, tool calls, errors) streams to the local service:

    from agentguard.adapters.langgraph import AgentGuardLangGraphHandler

    handler = AgentGuardLangGraphHandler(
        base_url="http://127.0.0.1:8907",
        session_id=graph_config["configurable"].get("thread_id", "lg-default"),
    )
    graph.invoke(inputs, config={"callbacks": [handler]})

Graph nodes arrive as ``graph_event`` (enter/exit + iteration); LangChain chat
models report prompt/completion tokens via ``on_llm_end`` while tool calls and
errors map straight onto the shared schema — everything the dashboard and the
circuit breaker need.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..utils import sha256_text, new_id

try:  # LangChain installed alongside LangGraph
    from langchain_core.callbacks import BaseCallbackHandler  # type: ignore
    from langchain_core.outputs import LLMResult  # type: ignore
except Exception:  # pragma: no cover - degrade to a no-op base class
    BaseCallbackHandler = object  # type: ignore
    LLMResult = Any  # type: ignore


class _Poster:
    """Thread-safe sync poster — callbacks fire on executor threads."""

    def __init__(self, base_url: str, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        try:
            import httpx

            self._client = httpx.Client(timeout=timeout)
        except Exception:
            self._client = None
        self.failed = 0

    def post(self, path: str, payload: dict) -> None:
        if self._client is None:
            return
        try:
            self._client.post(self.base_url + path, json=payload, timeout=self.timeout)
        except Exception:
            self.failed += 1

    def event(self, agent, sid, etype, data) -> None:
        self.post(
            "/v1/events",
            {"events": [{"agent": agent, "session_id": sid, "type": etype, "data": data}]},
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class AgentGuardLangGraphHandler(BaseCallbackHandler):  # type: ignore[misc, valid-type]
    """Callback handler bridging LangGraph/LangChain runs into AgentGuard."""

    raise_on_error = False   # monitoring must never break the graph
    run_inline = False

    def __init__(self, session_id: str, *, base_url: str = "http://127.0.0.1:8907",
                 agent: str = "langgraph", metadata: dict | None = None):
        self.sid = session_id
        self.agent = agent
        self.poster = _Poster(base_url)
        self.iteration = 0
        self.started = time.time()
        self._run_depth: dict[str, int] = {}
        self._node_for_run: dict[str, str] = {}
        self.metadata = dict(metadata or {})
        self.poster.event(self.agent, self.sid, "session_start",
                          {**self.metadata, "tokamak": None} if self.metadata else {"model": "langgraph"})

    # ------------------------------------------------------------------ utils
    def _send(self, etype: str, data: dict) -> None:
        self.poster.event(self.agent, self.sid, etype, data)

    # ------------------------------------------------------------------ chain (nodes)
    def on_chain_start(self, serialized: dict | None, inputs: dict, *,
                       run_id: str = "", parent_run_id: str | None = None,
                       tags: list | None = None, name: str | None = None,
                       **kwargs: Any) -> None:
        node = (name or (serialized or {}).get("name") or (serialized or {}).get("id") or "node")
        node = str(node).split(".")[-1]
        is_root = parent_run_id in (None, "", "none")
        if is_root:
            self.iteration += 1
        self._run_depth[run_id] = 0 if is_root else (self._run_depth.get(parent_run_id, 1) + 1)
        self._node_for_run[run_id] = node
        if self._run_depth[run_id] <= 1:
            self._send("graph_event", {
                "node": node, "phase": "enter", "iteration": self.iteration,
            })

    def on_chain_end(self, outputs: dict, *, run_id: str = "", **kwargs: Any) -> None:
        node = self._node_for_run.pop(run_id, None)
        depth = self._run_depth.pop(run_id, None)
        if node and depth in (0, 1):
            self._send("graph_event", {"node": node, "phase": "exit", "iteration": self.iteration})

    def on_chain_error(self, error: BaseException, *, run_id: str = "", **kwargs: Any) -> None:
        node = self._node_for_run.get(run_id, "?")
        self._send("error", {"message": str(error)[:300], "kind": "chain_error", "tool": node})

    # ------------------------------------------------------------------ llm
    def on_llm_end(self, response: LLMResult, *, run_id: str = "", **kwargs: Any) -> None:
        usage: dict[str, Any] = {}
        try:
            usage = (response.llm_output or {}).get("token_usage") or {}
        except AttributeError:
            usage = {}
        data = {
            "input_tokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            "iteration": self.iteration or None,
            "latency_ms": None,
            "model": (response.llm_output or {}).get("model_name"),
        }
        if data["input_tokens"] or data["output_tokens"]:
            self._send("llm_call", data)
        else:
            # token schemas vary by provider: best effort from generations
            self._send("llm_call", {"iteration": self.iteration or None, "model": data.get("model")})

    def on_llm_error(self, error: BaseException, *, run_id: str = "", **kwargs: Any) -> None:
        self._send("error", {"message": str(error)[:300], "kind": "llm_error", "tool": "llm"})

    # ------------------------------------------------------------------ tools
    def on_tool_start(self, serialized: dict | None, input_str: str, *,
                      run_id: str = "", **kwargs: Any) -> None:
        tool = str((serialized or {}).get("name") or "tool")
        self._send("tool_call", {
            "name": tool,
            "args_digest": sha256_text(input_str)[:16],
            "args_preview": input_str[:240],
            "status": "started",
            "call_id": new_id("tc")[:12],
        })

    def on_tool_end(self, output: Any, *, run_id: str = "", **kwargs: Any) -> None:
        out = output if isinstance(output, str) else json.dumps(output, default=str)
        self._send("tool_call", {"name": "tool", "status": "success",
                                 "result_preview": out[:240]})

    def on_tool_error(self, error: BaseException, *, run_id: str = "", **kwargs: Any) -> None:
        self._send("tool_call", {"name": "tool", "status": "error",
                                 "result_preview": str(error)[:240]})

    # ------------------------------------------------------------------ state
    def mark_state(self, state: str, previous: str | None = None) -> None:
        """Optionally let applications checkpoint graph state transitions."""
        self._send("state_change", {"state": state, "previous_state": previous})

    def on_session_end(self) -> None:
        self._send("session_end", {"iteration": self.iteration})
        self.poster.close()
