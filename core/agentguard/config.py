"""Configuration: YAML file + environment overrides.

Config search order:
  1. ``AGENTGUARD_CONFIG`` env var
  2. ``--config`` CLI flag
  3. ``./agentguard.yaml`` (cwd)
  4. built-in defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .schema import FirewallAction

DEFAULT_CONFIG_PATHS = ("agentguard.yaml", "agentguard.yml")

FirewallPolicyAction = FirewallAction


class LlamaGuardConfig(BaseModel):
    provider: Literal["ollama"] = "ollama"
    model: str = "llama-guard3:1b"
    endpoint: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 20.0
    # what to do when the LLM tier errors or times out: continue with
    # rules+heuristics ("allow_pass"), or treat as failure and block ("block")
    on_failure: Literal["allow_pass", "block"] = "allow_pass"
    enabled: bool = True
    # map hazard code -> FirewallAction. Unknown hazards use `default`.
    # High-severity hazards block; the 1B model false-positives on short
    # opaque strings, so low-severity hazards downgrade to sanitize.
    hazard_actions: dict[str, str] = Field(
        default_factory=lambda: {
            "default": "sanitize",
            "S2": "sanitize",
            "S3": "block",
            "S4": "block",
            "S9": "block",
            "S13": "block",
            "S14": "block",
            "S15": "block",
        }
    )


class FirewallConfig(BaseModel):
    enabled: bool = True
    # global switch for observe mode: decisions are computed and recorded but
    # never enforced (hook tools are told to allow).
    observe_mode: bool = False
    llm_guard: LlamaGuardConfig = Field(default_factory=LlamaGuardConfig)
    # action per violation category
    category_actions: dict[str, str] = Field(
        default_factory=lambda: {
            "injection": "block",
            "jailbreak": "block",
            "override": "block",
            "encoded_payload": "sanitize",
            "secret": "sanitize",
            "unsafe_content": "block",
        }
    )
    # risk thresholds 0..100
    block_threshold: float = 70.0
    sanitize_threshold: float = 25.0
    scan_outbound: bool = True
    use_heuristics: bool = True
    # store full prompt text in the local event DB (disable → hashes + previews only)
    store_prompt_content: bool = True
    # how long an approval request may sit before the firewall denies it (s).
    approval_timeout_seconds: float = 300.0


class BreakerDefaults(BaseModel):
    max_iterations: int = 60
    max_tool_calls: int = 200
    max_cost_usd: float = 5.0
    max_tokens: int = 200_000
    max_wall_seconds: float = 3600.0
    max_consecutive_tool_errors: int = 8
    loop_window: int = 12            # how many recent tool calls to consider
    loop_repeats: int = 3            # stops after same signature repeats N times in window


class BreakerConfig(BaseModel):
    enabled: bool = True
    # what to do when a limit trips: alert / pause (approval required) / kill
    on_breach: Literal["alert", "pause", "kill"] = "kill"
    warn_fraction: float = 0.8       # emit warning event at 80% of budget
    defaults: BreakerDefaults = Field(default_factory=BreakerDefaults)
    # per-agent overrides, e.g. {"codex": {"max_cost_usd": 2.0}}
    agent_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8907
    db_path: str = ""                # empty -> ~/.agentguard/events.db
    retention_hours: float = 72.0    # events older than this are pruned on startup
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])


class DashboardConfig(BaseModel):
    dir: str = ""                    # empty -> ../dashboard/dist relative to this file


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    firewall: FirewallConfig = Field(default_factory=FirewallConfig)
    breaker: BreakerConfig = Field(default_factory=BreakerConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        candidate: Path | None = None
        if path:
            candidate = Path(path).expanduser()
        else:
            env = os.environ.get("AGENTGUARD_CONFIG")
            if env:
                candidate = Path(env).expanduser()
            else:
                for name in DEFAULT_CONFIG_PATHS:
                    p = Path.cwd() / name
                    if p.is_file():
                        candidate = p
                        break
        if candidate is None or not candidate.is_file():
            return cls()
        try:
            raw = yaml.safe_load(candidate.read_text()) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - config typo feedback
            raise ValueError(f"Invalid YAML in {candidate}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Config {candidate} must be a mapping at top level")
        return cls.model_validate(raw)


def default_db_path() -> str:
    base = os.environ.get("AGENTGUARD_HOME")
    if base:
        return str(Path(base).expanduser() / "events.db")
    return str(Path.home() / ".agentguard" / "events.db")
