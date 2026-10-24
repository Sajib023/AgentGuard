"""Firewall pipeline.

Rules -> heuristics -> secrets -> (optional) Llama Guard 3 -> policy decision.

The decision function is deliberately boring: category-based actions first
(configured policy), then risk thresholds. Everything is recorded so the
dashboard can replay why a decision happened.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from ..config import FirewallConfig
from ..schema import FirewallAction
from . import heuristics, rules, secrets
from .llm_guard import LlamaGuardClient, RESPONSE_FORMAT_NOTE

ALL_ACTIONS = {a.value for a in FirewallAction}


class Violation(BaseModel):
    kind: str
    rule: str
    snippet: str = ""
    span: tuple[int, int] | None = None
    confidence: float = 0.0
    weight: float = 0.0
    description: str = ""
    details: str = ""


class FirewallResult(BaseModel):
    action: FirewallAction
    risk_score: float
    violations: list[Violation] = Field(default_factory=list)
    sanitized_text: str = ""
    redaction_count: int = 0
    decision_reason: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class FirewallEngine:
    def __init__(self, config: FirewallConfig, rag: Any | None = None):
        self.config = config
        self.rag = rag
        lg = config.llm_guard
        self.llm = LlamaGuardClient(
            endpoint=lg.endpoint,
            model=lg.model,
            timeout=lg.timeout_seconds,
            on_failure=lg.on_failure,
        ) if lg.enabled else None

    @property
    def llm_enabled(self) -> bool:
        return self.llm is not None and self.config.llm_guard.enabled

    async def inspect(
        self,
        text: str,
        *,
        direction: str = "inbound",
        context_type: str = "prompt",
        session_id: str | None = None,
    ) -> FirewallResult:
        t0 = time.perf_counter()
        cfg = self.config
        text = text or ""
        if not text.strip() or not cfg.enabled:
            return FirewallResult(action=FirewallAction.allow, risk_score=0.0,
                                  decision_reason="empty input or disabled",
                                  meta={"skipped": not text.strip()})

        violations: list[Violation] = []
        meta: dict[str, Any] = {"direction": direction, "context_type": context_type}

        # 1) deterministic rules
        for f in rules.scan_rules(text):
            violations.append(Violation(**f))
        meta["rules_hits"] = sum(1 for v in violations)

        # 2) heuristics (paraphrase + obfuscation net)
        if cfg.use_heuristics:
            for f in heuristics.analyze(text):
                if "decoded" in f:
                    decoded = f.pop("decoded")
                    meta["decoded_b64"] = decoded[:200]
                    # nested scan: treat decoded content as another inspection surface
                    for f2 in rules.scan_rules(decoded):
                        f2["confidence"] = round(f2["confidence"] * 0.8, 3)
                        f2["rule"] = f"b64::{f2['rule']}"
                        f2["snippet"] = f2["snippet"][:160]
                        violations.append(Violation(**f2))
                violations.append(Violation(**f))

        # 3) secrets scan (always on for inbound; outbound if scan_outbound)
        if direction == "inbound" or cfg.scan_outbound:
            for m in secrets.find_secrets(text):
                violations.append(Violation(
                    kind="secret", rule=f"secret.{m['type']}", snippet=m["preview"],
                    span=m["span"], confidence=m["confidence"], weight=40.0,
                    description=f"sensitive material: {m['type']}"))

        # 3.5) Contextual RAG + ColBERT Late-Interaction + GraphRAG multi-hop lineage
        if self.rag is not None and text.strip():
            rag_info = self.rag.inspect_for_firewall(
                text, session_id=session_id, context_type=context_type
            )
            meta["rag"] = {
                "top_matches": rag_info.get("hits", []),
                "sensitive_touched": rag_info.get("sensitive_touched", []),
                "network_sinks": rag_info.get("network_sinks", []),
                "exfiltration_chains": len(rag_info.get("exfiltration_chains", [])),
            }
            for chain in rag_info.get("exfiltration_chains", []):
                violations.append(Violation(
                    kind="exfiltration",
                    rule=f"graphrag.{chain['tactic']}",
                    snippet=f"{chain['sensitive_artifact']} -> {chain['external_sink']}",
                    confidence=chain["confidence"],
                    weight=chain["weight"],
                    description=chain["tactic_name"],
                    details=" | ".join(chain["hops"]),
                ))

        # 4) Llama Guard 3 tier (beside rules+heuristics, never replacing them)
        if self.llm_enabled and text.strip():
            verdict = await self.llm.classify(text)
            meta["llm_guard"] = {"safe": verdict["safe"], "hazards": verdict.get("hazards"),
                                 "error": verdict.get("tier_error"),
                                 "elapsed_ms": verdict.get("elapsed_ms")}
            if not verdict["safe"]:
                lg_cfg = cfg.llm_guard
                for hz in verdict.get("hazards") or ["default"]:
                    act = lg_cfg.hazard_actions.get(hz, lg_cfg.hazard_actions.get("default", "block"))
                    violations.append(Violation(
                        kind="unsafe_content", rule=f"llama_guard.{hz}", snippet="",
                        confidence=0.9, weight=50.0,
                        description=RESPONSE_FORMAT_NOTE,
                        details=f"action={act}"))

        # 5) score & decide
        # Cap each kind's contribution at its strongest single hit so that
        # overlapping spans of one category cannot escalate past policy.
        kind_scores: dict[str, float] = {}
        for v in violations:
            kind_scores[v.kind] = max(kind_scores.get(v.kind, 0.0), v.weight * v.confidence)
        score = min(100.0, sum(kind_scores.values()))
        action, reason = self._decide_action(violations, score, direction, kind_scores)
        redacted, redaction_count = (text, 0)
        if action in (FirewallAction.sanitize, FirewallAction.allow) or viol_secrets(violations):
            redacted, redaction_count = secrets.redact(text, secrets.find_secrets(text))

        meta["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return FirewallResult(
            action=action,
            risk_score=round(score, 1),
            violations=violations,
            sanitized_text=redacted if action == FirewallAction.sanitize else "",
            redaction_count=redaction_count,
            decision_reason=reason,
            meta=meta,
        )

    # -- policy -------------------------------------------------------------
    def _decide_action(self, violations: list[Violation], score: float, direction: str,
                       kind_scores: dict[str, float] | None = None) -> tuple[FirewallAction, str]:
        cfg = self.config
        if cfg.observe_mode:
            return FirewallAction.allow, f"observe_mode (score={score:.0f})"

        if direction == "outbound":
            # outbound scanning is a warning-only surface by design
            return FirewallAction.sanitize if violations else FirewallAction.allow, "outbound scan"

        strengths = {"allow": 0, "sanitize": 1, "approve": 2, "block": 3}
        # Category votes: only kinds with an explicit configured action vote.
        voted: dict[str, str] = {}
        residual = 0.0     # score from kinds without a configured action → threshold path
        for v in violations:
            if v.kind == "unsafe_content":
                hz = v.rule.split(".")[-1]
                fallback = cfg.llm_guard.hazard_actions.get("default", "sanitize")
                act = cfg.llm_guard.hazard_actions.get(hz, fallback)
            else:
                act = cfg.category_actions.get(v.kind)
            if act is None:      # unconfigured kind → residual/threshold path only
                continue
            voted[v.kind] = max(voted.get(v.kind, "allow"), act,
                                key=lambda a: strengths.get(a, 0))
        if kind_scores:
            for kind, kse in kind_scores.items():
                if kind not in voted and kind not in cfg.category_actions:
                    residual += kse
        residual = min(100.0, residual)

        if voted:
            strongest = max(voted.values(), key=lambda a: strengths.get(a, 0))
            if strongest != "allow":
                label = ", ".join(sorted(f"{k}→{a}" for k, a in voted.items() if a != "allow"))
                return FirewallAction(strongest), f"policy: {strongest} ({label})"

        if residual >= cfg.block_threshold:
            return FirewallAction.block, f"risk {residual:.0f} ≥ block threshold {cfg.block_threshold:.0f}"
        if residual >= cfg.sanitize_threshold:
            return FirewallAction.sanitize, f"risk {residual:.0f} ≥ sanitize threshold {cfg.sanitize_threshold:.0f}"
        if violations:
            return FirewallAction.allow, f"below action thresholds (score={score:.0f}, kinds={list(voted)})"
        return FirewallAction.allow, f"no violations (score={score:.0f})"


def viol_secrets(violations: list[Violation]) -> bool:
    return any(v.kind == "secret" for v in violations)
