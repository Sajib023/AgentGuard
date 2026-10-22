"""Small utilities shared across the service."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any


def now() -> float:
    """Current Unix time in seconds (float)."""
    return time.time()


def new_id(prefix: str = "ev") -> str:
    """Short unique id like ``ev_ab12cd34``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def canonical_json(value: Any) -> str:
    """Deterministic JSON string used for tool-call signatures."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def truncate(text: str, limit: int = 200) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"…(+{len(text) - limit} chars)"


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
