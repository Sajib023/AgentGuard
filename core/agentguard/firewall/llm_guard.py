"""Llama Guard 3 (Ollama) adapter.

Per design, Llama Guard 3 always sits BESIDE the deterministic rules and
heuristics — it layers hazard classification (MLCommons taxonomy S1..S14) on
top of injection-focused local detection. If the daemon or model is missing,
this tier silently drops out and the rules+heuristics verdict stands.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

HAZARD_RE = re.compile(r"\b(S\d{1,2})\b")

RESPONSE_FORMAT_NOTE = (
    "llama-guard3 returns plain text: 'safe' or 'unsafe' followed by hazard "
    "codes, e.g. 'unsafe S7 S10'."
)


class LlamaGuardClient:
    def __init__(self, *, endpoint: str, model: str, timeout: float, on_failure: str = "allow_pass"):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.on_failure = on_failure  # "allow_pass" | "block"
        self._available_until = 0.0
        self._available = False
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def is_available(self) -> bool:
        """Cheap cached daemon/model probe (30s TTL)."""
        if time.time() < self._available_until:
            return self._available
        try:
            client = await self._http()
            r = await client.get(f"{self.endpoint}/api/tags", timeout=2.5)
            models = [m.get("name", "") for m in (r.json() or {}).get("models", [])]
            base = self.model.split(":")[0]
            self._available = any(
                name == self.model or name.split(":")[0] == base
                for name in models
            )
        except Exception:
            self._available = False
        self._available_until = time.time() + 30.0
        return self._available

    async def classify(self, text: str) -> dict[str, Any]:
        """Classify a user prompt. Returns dict(safe, hazards, error?)."""
        if not await self.is_available():
            return {"safe": True, "hazards": [], "tier_error": "llama_guard_unavailable"}
        t0 = time.perf_counter()
        try:
            client = await self._http()
            resp = await client.post(
                f"{self.endpoint}/api/generate",
                json={
                    "model": self.model,
                    "prompt": text,          # policy/template embedded by modelfile
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 64},
                },
            )
            resp.raise_for_status()
            raw = (resp.json().get("response") or "").strip()
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return self._parse(raw, elapsed_ms)
        except Exception as exc:  # network / timeout / model error
            ok = self.on_failure == "allow_pass"
            return {"safe": ok, "hazards": [], "tier_error": f"{type(exc).__name__}: {exc}"[:200]}

    def _parse(self, raw: str, elapsed_ms: int) -> dict[str, Any]:
        low = raw.lower()
        unsafe = "unsafe" in low and "safe" != low.strip()
        hazards = sorted(set(HAZARD_RE.findall(raw)))
        # Some builds emit '<|safe|>'; strip markers before deciding
        if "|safe|" in low or low.startswith("safe"):
            unsafe = False if low.startswith("safe") else unsafe
        return {
            "safe": not unsafe,
            "hazards": hazards if unsafe else [],
            "raw": raw[:200],
            "elapsed_ms": elapsed_ms,
        }
