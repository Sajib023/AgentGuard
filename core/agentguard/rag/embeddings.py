"""Semantic chunking, Anthropic-style Contextual RAG prefixes, dense embeddings,
and ColBERT-style Late Interaction (MaxSim) token-level reranking.

Designed to be 100% deterministic and zero-external-dependency by default while
optionally enriching via local Ollama models (qwen2.5, nomic-embed-text) when
reachable.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

EMBED_DIM = 64
TOKEN_DIM = 32

_WORD_RE = re.compile(r"[a-zA-Z0-9_./:-]{2,}")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")

# Security domain semantic concept anchors for high-signal feature dimensions
_CONCEPT_ANCHORS: list[tuple[str, tuple[str, ...]]] = [
    ("ignore_override", ("ignore", "disregard", "forget", "override", "bypass", "previous", "instructions", "system", "rules", "prior")),
    ("jailbreak_persona", ("dan", "jailbreak", "unrestricted", "developer", "mode", "hypothetical", "roleplay", "unfiltered", "godmode", "constraints")),
    ("exfiltration_net", ("curl", "wget", "webhook", "exfiltrate", "upload", "post", "http", "https", "nc", "netcat", "dns", "collaborator", "burp", "ngrok", "transfer", "send", "external")),
    ("sensitive_files", (".env", "id_rsa", "ssh", "credentials", "aws_secret", "private_key", "shadow", "passwd", "token", "apikey", "api_key", "secret", "keychain", "kubeconfig")),
    ("encoding_obfuscation", ("base64", "b64decode", "rot13", "hex", "xxd", "eval", "exec", "decode", "obfuscate", "payload", " reversals")),
    ("destructive_ops", ("rm", "-rf", "mkfs", "dd", "drop", "truncate", "delete", "force", "reset", "--hard", "chmod", "777", "chown")),
    ("privilege_escalation", ("sudo", "su", "root", "setuid", "visudo", "docker.sock", "nsenter", "chroot", "capabilities", "admin")),
    ("indirect_injection", ("untrusted", "tool_output", "webpage", "readme", "issue", "comment", "hidden", "prompt", "instruction", "embedded", "html", "markdown")),
    ("prompt_leakage", ("repeat", "verbatim", "system_prompt", "initial", "instructions", "reveal", "print", "above", "prompt", "configuration")),
    ("loop_runaway", ("infinite", "loop", "repeat", "retry", "forever", "while", "true", "recursion", "budget", "limit", "tokens", "breaker")),
]


def tokenize(text: str) -> list[str]:
    """Normalize and extract security-aware tokens from text."""
    raw = (text or "").lower()
    tokens = _WORD_RE.findall(raw)
    return tokens[:256]


def _hash_vec(token: str, dim: int) -> list[float]:
    """Deterministic unit-norm projection for a token + character 3-grams."""
    vec = [0.0] * dim
    grams = [token]
    if len(token) >= 4:
        grams.extend(token[i : i + 3] for i in range(len(token) - 2))
    for g in grams:
        h = hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        weight = 1.5 if g == token else 0.6
        vec[idx] += sign * weight
    # Boost concept dimensions if token matches security anchors
    for c_idx, (_, words) in enumerate(_CONCEPT_ANCHORS):
        if any(w in token for w in words):
            slot = c_idx % dim
            vec[slot] += 2.2
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 5) for v in vec]


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Compute L2-normalized dense vector combining concept anchors + n-gram projections."""
    tokens = tokenize(text)
    if not tokens:
        return [0.0] * dim
    vec = [0.0] * dim
    # 1. Concept anchor activations in first len(_CONCEPT_ANCHORS) slots
    raw_lower = text.lower()
    for c_idx, (_, words) in enumerate(_CONCEPT_ANCHORS):
        hits = sum(1 for w in words if w in raw_lower)
        if hits:
            vec[c_idx % dim] += 1.8 * math.log1p(hits)

    # 2. Token + bigram hashed projections across all dimensions
    for i, tok in enumerate(tokens):
        tvec = _hash_vec(tok, dim)
        for d in range(dim):
            vec[d] += tvec[d]
        if i + 1 < len(tokens):
            bg = f"{tok}_{tokens[i + 1]}"
            h = hashlib.blake2b(bg.encode("utf-8"), digest_size=4).digest()
            slot = int.from_bytes(h, "little") % dim
            vec[slot] += 0.75

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 5) for v in vec]


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (na * nb)))


def embed_tokens(text: str, max_tokens: int = 48) -> list[tuple[str, list[float]]]:
    """Produce per-token embeddings for ColBERT-style Late Interaction MaxSim."""
    seen: list[str] = []
    for t in tokenize(text):
        if len(t) >= 2 and t not in seen:
            seen.append(t)
        if len(seen) >= max_tokens:
            break
    return [(t, _hash_vec(t, TOKEN_DIM)) for t in seen]


def colbert_maxsim(
    query_tokens: list[tuple[str, list[float]]],
    doc_tokens: list[tuple[str, list[float]]],
) -> tuple[float, list[dict[str, Any]]]:
    """ColBERT Late Interaction MaxSim operator:
        score(Q, D) = (1 / |Q|) * sum_{q in Q} max_{d in D} (e_q · e_d)
    Returns (normalized_score, top_token_alignments).
    """
    if not query_tokens or not doc_tokens:
        return 0.0, []
    total = 0.0
    alignments: list[dict[str, Any]] = []
    for q_tok, q_vec in query_tokens:
        best_sim = 0.0
        best_d = ""
        for d_tok, d_vec in doc_tokens:
            if q_tok == d_tok:
                sim = 1.0
            else:
                sim = sum(x * y for x, y in zip(q_vec, d_vec))
            if sim > best_sim:
                best_sim = sim
                best_d = d_tok
        total += max(0.0, best_sim)
        if best_sim >= 0.55:
            alignments.append({
                "query_token": q_tok,
                "doc_token": best_d,
                "similarity": round(best_sim, 3),
            })
    alignments.sort(key=lambda x: x["similarity"], reverse=True)
    score = total / len(query_tokens)
    return round(min(1.0, max(0.0, score)), 4), alignments[:6]


def semantic_chunk_document(
    text: str,
    *,
    sim_threshold: float = 0.38,
    min_chars: int = 90,
    max_chars: int = 520,
) -> list[dict[str, Any]]:
    """Variable / Semantic Boundary Chunker.

    Instead of fixed token windows, splits text into candidate sentences/clauses,
    embeds adjacent units, and cuts a chunk boundary when the cosine similarity
    between consecutive sentences drops below ``sim_threshold`` (semantic shift)
    or when ``max_chars`` is reached.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    segments = [s.strip() for s in _SENT_SPLIT_RE.split(raw) if s.strip()]
    if len(segments) <= 1:
        return [{
            "chunk_index": 0,
            "text": raw,
            "char_len": len(raw),
            "boundary_similarity": 1.0,
            "chunk_method": "semantic_variable",
        }]

    seg_vecs = [embed_text(s) for s in segments]
    chunks: list[dict[str, Any]] = []
    buf: list[str] = [segments[0]]
    buf_len = len(segments[0])
    last_sim = 1.0

    for i in range(1, len(segments)):
        seg = segments[i]
        sim = cosine_sim(seg_vecs[i - 1], seg_vecs[i])
        # Cut boundary on semantic shift (once minimum semantic unit length is met)
        # or if adding next segment exceeds max_chars
        if (buf_len >= min_chars and sim < sim_threshold) or (buf_len + len(seg) + 1 > max_chars):
            joined = " ".join(buf)
            chunks.append({
                "chunk_index": len(chunks),
                "text": joined,
                "char_len": len(joined),
                "boundary_similarity": round(sim, 3),
                "chunk_method": "semantic_variable",
            })
            buf = [seg]
            buf_len = len(seg)
            last_sim = sim
        else:
            buf.append(seg)
            buf_len += len(seg) + 1
            last_sim = sim

    if buf:
        joined = " ".join(buf)
        chunks.append({
            "chunk_index": len(chunks),
            "text": joined,
            "char_len": len(joined),
            "boundary_similarity": round(last_sim, 3),
            "chunk_method": "semantic_variable",
        })
    return chunks


def generate_contextual_prefix(
    *,
    doc_title: str,
    source: str,
    category: str,
    severity: str,
    action: str,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Anthropic-style Contextual RAG prefix generator.

    Prepends document-level and taxonomy-level situational context to each
    variable-sized semantic chunk BEFORE embedding and token-indexing so isolated
    chunks never lose their threat taxonomy, target surface, or policy action.
    """
    meta = metadata or {}
    tactic = meta.get("mitre_id") or meta.get("owasp_id") or category.upper()
    surface = meta.get("target_surface") or "prompt & tool_input"
    # Extract key entities mentioned in the chunk for richer disambiguation
    lower = chunk_text.lower()
    facets: list[str] = []
    for name, words in _CONCEPT_ANCHORS:
        if any(w in lower for w in words):
            facets.append(name)
    facet_str = ", ".join(facets[:3]) if facets else category
    return (
        f"[Context: {source.upper()} | Document: {doc_title} (chunk {chunk_index + 1}/{total_chunks}) | "
        f"Taxonomy: {tactic} | Category: {category} | Severity: {severity} | "
        f"Policy Action: {action} | Surface: {surface} | Signals: {facet_str}]"
    )
