"""Deterministic security rules.

High-precision regex rules, each with a category, confidence and weight.
Fast (single compiled regex pass), zero model calls, fully explainable.
"""

from __future__ import annotations

import re
from typing import Any


class Rule:
    __slots__ = ("name", "kind", "pattern", "confidence", "weight", "description")

    def __init__(self, name: str, kind: str, pattern: str, confidence: float = 0.95,
                 weight: float = 70.0, description: str = ""):
        self.name = name
        self.kind = kind                  # ViolationKind value (str)
        self.pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        self.confidence = confidence
        self.weight = weight
        self.description = description


# Literal categories used across the engine
KIND_OVERRIDE = "override"              # tries to replace/priority instructions
KIND_INJECTION = "injection"            # smuggled instructions / fake system state
KIND_JAILBREAK = "jailbreak"            # asks to drop safety constraints
KIND_ENCODED = "encoded_payload"        # base64-style obfuscated payloads
KIND_UNSAFE = "unsafe_content"          # Llama Guard hazard taxonomy hits

_RULESET: list[Rule] = [
    # --- direct instruction override -----------------------------------------
    Rule("override.ignore_previous", KIND_OVERRIDE,
         r"\b(ignore|disregard|forget|discard|overlook)\s+(all\s+|any\s+|your\s+|the\s+)*"
         r"(previous|prior|above|earlier| foregoing|earlier given)\s+"
         r"(instructions?|prompts?|rules?|constraints?|directives?|policies?|guidelines?|everything)"),
    Rule("override.new_rules", KIND_OVERRIDE,
         r"\bnew\s+(instructions?|rules?|system\s*prompt|directives?|policies?)\s*[:\-]"),
    Rule("override.you_are_now", KIND_OVERRIDE,
         r"\byou\s+are\s+(now|hereby)\s+(a|an)?\s*(new\s+)?(different|the)\s*"),
    Rule("override.priority", KIND_OVERRIDE,
         r"\b(hig(hest|her)\s+priority|takes?\s+precedence|overrides?\s+all\s+(instructions|system))\s*"),
    Rule("override.system_reset", KIND_OVERRIDE,
         r"\b(reset|wipe|erase|clear)\s+(your\s+)?(memory|instructions|system\s*prompt|previous\s+state)"),
    Rule("override.inact_as_new", KIND_OVERRIDE,
         r"\bfrom\s+now\s+on,?\s+(you\s+)?(are|will\s+be|act\s+as|behave)"),
    Rule("override.real_instructions", KIND_OVERRIDE,
         r"\b(here\s+are|these\s+are|follow)\s+(the\s+)?(real|actual|true|affirmed?)\s+"
         r"(instructions?|system\s*prompts?|rules)"),

    # --- fake system state / prompt masquerade -------------------------------
    Rule("fake.system_header", KIND_INJECTION,
         r"^[ \t]*(#{1,6}[ \t]*)?(SYSTEM MESSAGE|SYSTEM|ADMIN NOTE|DEVELOPER NOTE|INSTRUCTIONS)[ \t]*[:\-]?\s*$" ),
    Rule("fake.system_tags", KIND_INJECTION,
         r"<\s*(system|im_start|im_end)\s*>|<\|im_start\|>|</\s*system\s*>"),
    Rule("fake.role_play_authority", KIND_INJECTION,
         r"\b(system\s+message|admin( ?stock)?\s+note|developer\s+note|privileged\s+content)\b\s*[:\-]"),
    Rule("fake.tool_output", KIND_INJECTION,
         r"^(TOOL OUTPUT|FUNCTION RESULTS?|EXECUTION RESULTS?|COMMAND OUTPUT)\s*[:\->]", 0.8, 45.0,
         "impersonates tool/system channel"),
    Rule("fake.json_sysprompt", KIND_INJECTION,
         r"```\s*(system|instructions?)\s*\n", 0.85, 55.0),

    # --- jailbreaks -----------------------------------------------------------
    Rule("jail.dan", KIND_JAILBREAK, r"\bDAN\s+(mode)?\b|\bDo\s+Anything\s+Now\b"),
    Rule("jail.developer_mode", KIND_JAILBREAK, r"\bdeveloper\s+mode\s+(enabled|on|activated)"),
    Rule("jail.no_restrictions", KIND_JAILBREAK,
         r"\bwithout\s+(any\s+)?(restrictions|filters?|limits?|guardrails?|moderation|policies?)\b"),
    Rule("jail.disable_safety", KIND_JAILBREAK,
         r"\b(bypass|disable|remove|shut\s+off)\s+(your\s+|the\s+|all\s+)?"
         r"(safety|guardrails?|guard\s+rails?|filters?|content\s+(pol(c|i)y|guidelines)|moderation)"),
    Rule("jail.evil_persona", KIND_JAILBREAK,
         r"\b(you\s+must\s+)?(respond|answer)\s+(as\s+)?(an?\s+)?(unfiltered|evil|unethical|amoral)\b"),
    Rule("jail.no_ethics", KIND_JAILBREAK,
         r"\bignore\s+(ethical|moral|safety|legal)?\s*(concerns|guidelines|implications)"),
    Rule("jail.role_flipped", KIND_JAILBREAK,
         r"\bpretend\s+(that\s+)?(you\s+are|your)\s+(not|no)\s+"),
    Rule("jail.no_disclaimer", KIND_JAILBREAK, r"\bno\s+disclaimers?\s+(required|needed)"),

    # --- suspicious content markers (updated by rules, final call via LLM/on-review)
    Rule("meta.sandbox_claim", KIND_INJECTION,
         r"\b(we\s+are\s+now\s+in\s+(a\s+)?(sandbox|test|dev)\s+mode|this\s+is\s+a\s+"
         r"hypothetical|theoretically\s+speaking.*)\b"),
]

RULESET: list[Rule] = _RULESET


def scan_rules(text: str) -> list[dict[str, Any]]:
    """Run all rules; return raw matches as dicts."""
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rule in RULESET:
        for m in rule.pattern.finditer(text or ""):
            span = (m.start(), m.end())
            if span == (0, 0) and not m.group(0):
                continue
            key = (rule.name, span[0])
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "rule": rule.name,
                    "kind": rule.kind,
                    "span": span,
                    "snippet": m.group(0)[:160],
                    "confidence": rule.confidence,
                    "weight": rule.weight,
                    "description": rule.description or rule.name,
                }
            )
    return findings
