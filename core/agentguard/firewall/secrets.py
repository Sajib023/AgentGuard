"""Secret / sensitive-data detection and redaction."""

from __future__ import annotations

import re
from typing import Any

# (type, regex, confidence) — tuned for coding-agent traffic: env dumps, tokens,
# config leaks. Each match is redact-able by span.
_SECRET_PATTERNS: list[tuple[str, str, float]] = [
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.95),
    ("aws_secret", r"\baws.{0,20}[0-9a-zA-Z/+]{40}\b", 0.5),
    ("github_pat", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b", 0.97),
    ("github_pat_fine", r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", 0.97),
    ("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b", 0.85),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b", 0.95),
    ("google_api", r"\bAIza[0-9A-Za-z_\-]{35}\b", 0.95),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b", 0.95),
    ("stripe_key", r"\b[srp]k_(?:live|test)_[A-Za-z0-9]{10,}\b", 0.9),
    ("npm_token", r"\bnpm_[A-Za-z0-9]{36}\b", 0.9),
    ("gitlab_pat", r"\bglpat-[A-Za-z0-9_\-]{20,}\b", 0.95),
    ("huggingface", r"\bhf_[A-Za-z0-9]{30,}\b", 0.95),
    ("sendgrid", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b", 0.9),
    ("twilio_key", r"\bSK(?:[0-9a-fA-F]{32})\b", 0.75),
    ("jwt", r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{5,}\b", 0.9),
    ("private_key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY(?: BLOCK)?-----", 0.99),
    ("postgres_url", r"\bpostgres(?:ql)?://[A-Za-z0-9_\-]+:[^@\s]{3,}@", 0.9),
    ("mysql_url", r"\bmysql://[A-Za-z0-9_\-]+:[^@\s]{3,}@", 0.9),
    ("env_secret", r"\b(?:AWS_SECRET_ACCESS_KEY|SECRET_KEY|API_KEY|API_TOKEN|ACCESS_TOKEN|"
                   r"DB_PASSWORD|PASSWORD)\s*[=:]\s*['\"]?[^\s'\"]{6,}", 0.65),
    ("kv_secret", r"\b(?:secret|token|passwd|password)\b['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{12,}", 0.5),
]

_COMPILED = [(t, re.compile(p, re.IGNORECASE), c) for t, p, c in _SECRET_PATTERNS]


def find_secrets(text: str) -> list[dict[str, Any]]:
    out = []
    seen_spans: set[int] = set()
    for typ, rx, conf in _COMPILED:
        for m in rx.finditer(text or ""):
            if any(s in seen_spans for s in range(m.start(), m.end())):
                continue
            for s in range(m.start(), m.end()):
                seen_spans.add(s)
            out.append({"type": typ, "span": (m.start(), m.end()),
                        "preview": m.group(0)[:40], "confidence": conf})
    return out


def redact(text: str, marks: list[dict[str, Any]], marker_fmt: str = "[REDACTED:{typ}]") -> tuple[str, int]:
    """Replace secret spans with redaction markers; returns (new_text, count)."""
    if not marks or not text:
        return text, 0
    chars: list[str] = list(text)
    spans = sorted((m["span"], m["type"]) for m in marks)
    replaced = 0
    covered: set[int] = set()
    for (start, end), typ in spans:
        if any(i in covered for i in range(start, end)):
            continue
        for i in range(start, end):
            covered.add(i)
        chars[start:end] = [marker_fmt.format(typ=typ)]
        replaced += 1
    return "".join(chars), replaced
