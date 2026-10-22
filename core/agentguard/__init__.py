"""AgentGuard — local-first AI safety and observability for coding agents.

One monitoring / policy engine, agent-specific adapters:

* Real-time prompt-injection firewall (deterministic rules -> heuristics ->
  secrets scan -> optional Llama Guard 3 via Ollama).
* Event store + live WebSocket feed used by the observability dashboard.
* Circuit breaker with loop detection and budget enforcement.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
