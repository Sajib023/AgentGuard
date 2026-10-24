"""5-Stage Threat-Intelligence & Policy RAG Service.

Combines:
  1. Variable / Semantic Boundary Chunking (cosine-similarity valley splitting)
  2. Anthropic-style Contextual RAG (document/taxonomy context prepended pre-embedding)
  3. Vector Similarity Search (dense concept + n-gram projections stored in SQLite)
  4. ColBERT-style Late Interaction Reranking (token-level MaxSim operator)
  5. GraphRAG / Attack-Lineage Knowledge Graph (multi-hop exfiltration & taxonomy paths)
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..db import Database
from ..firewall import secrets
from ..utils import now
from .corpus import SEED_DOCUMENTS
from .embeddings import (
    colbert_maxsim,
    cosine_sim,
    embed_text,
    embed_tokens,
    generate_contextual_prefix,
    semantic_chunk_document,
)
from .graph import KnowledgeGraphService


class ThreatRAGService:
    def __init__(self, db: Database, kg: KnowledgeGraphService | None = None):
        self.db = db
        self.kg = kg or KnowledgeGraphService(db)
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        row = self.db.one("SELECT COUNT(*) AS c FROM rag_chunks")
        if row and int(row["c"]) > 0:
            return
        for doc in SEED_DOCUMENTS:
            self.ingest_document(
                doc_id=doc["doc_id"],
                source=doc["source"],
                title=doc["title"],
                category=doc["category"],
                severity=doc.get("severity", "high"),
                action=doc.get("action", "block"),
                content=doc["content"],
                metadata=doc.get("metadata", {}),
            )

    def ingest_document(
        self,
        *,
        title: str,
        content: str,
        source: str = "custom_policy",
        category: str = "policy",
        severity: str = "high",
        action: str = "block",
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the 5-stage Data Lifecycle ingestion pipeline on a document:
        Stage 1 (Source) -> Stage 2 (Semantic Variable Chunking) ->
        Stage 3 (Secret Redaction + Contextual RAG Prefix) ->
        Stage 4 (Vector + Token Signature + Knowledge Graph Persistence).
        """
        raw_content = (content or "").strip()
        if not raw_content:
            return {"doc_id": doc_id or "", "chunks_ingested": 0}

        # Stage 3a: Clean & redact any accidental secrets before indexing
        cleaned_content, redacted_count = secrets.redact(
            raw_content, secrets.find_secrets(raw_content)
        )
        resolved_doc_id = doc_id or ("doc_" + hashlib.sha256(f"{source}:{title}".encode()).hexdigest()[:12])

        # Stage 2: Variable / Semantic Boundary Chunking (no fixed token windows)
        raw_chunks = semantic_chunk_document(cleaned_content)
        total = len(raw_chunks)
        ts = now()
        chunk_ids: list[str] = []

        with self.db.tx() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (resolved_doc_id,))
            for ch in raw_chunks:
                idx = ch["chunk_index"]
                c_text = ch["text"]
                # Stage 3b: Anthropic-style Contextual RAG prefix prepended BEFORE embedding
                ctx_prefix = generate_contextual_prefix(
                    doc_title=title,
                    source=source,
                    category=category,
                    severity=severity,
                    action=action,
                    chunk_text=c_text,
                    chunk_index=idx,
                    total_chunks=total,
                    metadata=metadata,
                )
                combined = f"{ctx_prefix}\n{c_text}"
                vec = embed_text(combined)
                tok_sigs = embed_tokens(combined)
                cid = f"{resolved_doc_id}#c{idx}"
                chunk_meta = {
                    **(metadata or {}),
                    "chunk_index": idx,
                    "total_chunks": total,
                    "char_len": ch["char_len"],
                    "boundary_similarity": ch["boundary_similarity"],
                    "chunk_method": "semantic_variable",
                    "contextual_rag": True,
                    "redacted_secrets": redacted_count,
                }
                conn.execute(
                    """
                    INSERT INTO rag_chunks (
                        id, doc_id, source, title, category, severity, action,
                        context_prefix, chunk_text, combined_text,
                        embedding, token_sigs, metadata, created_ts
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        cid,
                        resolved_doc_id,
                        source,
                        title,
                        category,
                        severity,
                        action,
                        ctx_prefix,
                        c_text,
                        combined,
                        json.dumps(vec),
                        json.dumps(tok_sigs),
                        json.dumps(chunk_meta),
                        ts,
                    ),
                )
                chunk_ids.append(cid)

        # Link document into the Knowledge Graph
        pol_node = f"doc:{resolved_doc_id}"
        self.kg.upsert_node(
            pol_node,
            "policy",
            title,
            risk_level=severity,
            props={"source": source, "category": category, "action": action},
        )
        mitre_id = (metadata or {}).get("mitre_id")
        if mitre_id:
            self.kg.add_edge(f"tech:{mitre_id}", pol_node, "DOCUMENTED_IN", weight=1.0)

        return {
            "doc_id": resolved_doc_id,
            "title": title,
            "source": source,
            "category": category,
            "chunks_ingested": len(chunk_ids),
            "chunk_ids": chunk_ids,
            "pipeline_stages": [
                "1_source_acquisition",
                "2_semantic_variable_chunking",
                "3_secret_redaction_and_contextual_prefix",
                "4_vector_and_kg_storage",
                "5_late_interaction_and_graphrag_delivery",
            ],
        }

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        category: str | None = None,
        session_id: str | None = None,
        include_graph: bool = True,
    ) -> dict[str, Any]:
        """Run full hybrid retrieval:
        1. Dense Vector Cosine over Contextual RAG chunks (top-20 candidate pool)
        2. ColBERT-style Late Interaction (MaxSim) token-level reranking -> top_k
        3. GraphRAG multi-hop subgraph & session exfiltration lineage lookup
        """
        t0 = time.perf_counter()
        q_text = (query or "").strip()
        if not q_text:
            return {
                "query": "",
                "hits": [],
                "graph": self.kg.query_subgraph(session_id=session_id) if include_graph else None,
                "elapsed_ms": 0,
            }

        q_vec = embed_text(q_text)
        q_tokens = embed_tokens(q_text)

        sql = "SELECT * FROM rag_chunks"
        params: tuple[Any, ...] = ()
        if category:
            sql += " WHERE category = ?"
            params = (category,)
        rows = self.db.query(sql, params)

        # Step 1: Vector similarity scoring over Contextual RAG embeddings
        candidates: list[dict[str, Any]] = []
        for r in rows:
            c_vec = json.loads(r["embedding"])
            dense_score = cosine_sim(q_vec, c_vec)
            candidates.append({
                "row": r,
                "dense_score": dense_score,
            })
        candidates.sort(key=lambda x: x["dense_score"], reverse=True)
        shortlist = candidates[: max(top_k * 3, 15)]

        # Step 2: ColBERT Late Interaction MaxSim reranking
        reranked: list[dict[str, Any]] = []
        for item in shortlist:
            r = item["row"]
            doc_tokens = json.loads(r["token_sigs"])
            maxsim_score, alignments = colbert_maxsim(q_tokens, doc_tokens)
            # Hybrid fusion: 45% Contextual Dense Cosine + 55% ColBERT MaxSim
            hybrid_score = round(0.45 * item["dense_score"] + 0.55 * maxsim_score, 4)
            meta = json.loads(r["metadata"] or "{}")
            reranked.append({
                "chunk_id": r["id"],
                "doc_id": r["doc_id"],
                "source": r["source"],
                "title": r["title"],
                "category": r["category"],
                "severity": r["severity"],
                "action": r["action"],
                "context_prefix": r["context_prefix"],
                "chunk_text": r["chunk_text"],
                "dense_score": round(item["dense_score"], 4),
                "colbert_maxsim": maxsim_score,
                "hybrid_score": hybrid_score,
                "token_alignments": alignments,
                "metadata": meta,
            })

        reranked.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top_hits = reranked[: max(1, min(top_k, 20))]

        # Step 3: GraphRAG multi-hop retrieval
        graph_data = None
        if include_graph:
            graph_data = self.kg.query_subgraph(query=q_text, session_id=session_id, max_hops=3)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "query": q_text,
            "techniques_applied": [
                "naive_rag",
                "vector_db",
                "contextual_rag",
                "semantic_chunking",
                "late_interaction_colbert",
                "graph_rag",
            ],
            "hits": top_hits,
            "graph": graph_data,
            "elapsed_ms": elapsed_ms,
        }

    def inspect_for_firewall(
        self,
        text: str,
        *,
        session_id: str | None = None,
        context_type: str = "prompt",
    ) -> dict[str, Any]:
        """Run GraphRAG multi-hop lineage check + Contextual RAG threat retrieval
        as part of the AgentGuard Firewall inspection pipeline."""
        # 1. Record resource access and check for multi-hop exfiltration chains in the KG
        kg_observation = self.kg.record_access_from_text(session_id or "adhoc", text)
        chains = kg_observation.get("exfiltration_chains", [])

        # 2. Retrieve top semantic threat matches via Contextual RAG + ColBERT MaxSim
        rag_res = self.retrieve(
            text, top_k=3, session_id=session_id, include_graph=False
        )
        hits = rag_res.get("hits", [])
        top_hit = hits[0] if hits else None

        return {
            "top_hit": top_hit,
            "hits": [
                {
                    "chunk_id": h["chunk_id"],
                    "title": h["title"],
                    "category": h["category"],
                    "action": h["action"],
                    "hybrid_score": h["hybrid_score"],
                    "colbert_maxsim": h["colbert_maxsim"],
                    "mitre_id": h["metadata"].get("mitre_id"),
                }
                for h in hits
            ],
            "exfiltration_chains": chains,
            "sensitive_touched": kg_observation.get("sensitive_touched", []),
            "network_sinks": kg_observation.get("network_sinks", []),
        }

    def status(self) -> dict[str, Any]:
        chunk_count = int((self.db.one("SELECT COUNT(*) AS c FROM rag_chunks") or {"c": 0})["c"])
        doc_count = int((self.db.one("SELECT COUNT(DISTINCT doc_id) AS c FROM rag_chunks") or {"c": 0})["c"])
        node_count = int((self.db.one("SELECT COUNT(*) AS c FROM kg_nodes") or {"c": 0})["c"])
        edge_count = int((self.db.one("SELECT COUNT(*) AS c FROM kg_edges") or {"c": 0})["c"])
        by_cat = self.db.query("SELECT category, COUNT(*) AS c FROM rag_chunks GROUP BY category")
        return {
            "status": "ready",
            "documents_indexed": doc_count,
            "contextual_chunks": chunk_count,
            "kg_nodes": node_count,
            "kg_edges": edge_count,
            "categories": {r["category"]: r["c"] for r in by_cat},
            "techniques": {
                "naive_rag": True,
                "vector_db": "sqlite_vector_hybrid + pgvector_compatible",
                "contextual_rag": "anthropic_style_document_and_taxonomy_prefix",
                "semantic_chunking": "cosine_similarity_valley_variable_boundaries",
                "combo_contextual_plus_semantic": True,
                "late_interaction": "colbert_token_maxsim_reranker",
                "graph_rag": "mitre_atlas_and_session_provenance_multi_hop_kg",
            },
            "local_models_routing": [
                {"model": "llama-guard3:1b", "runtime": "ollama", "quantization": "Q4_K_M", "role": "Tier-4 semantic safety classification"},
                {"model": "qwen2.5:3b", "runtime": "ollama", "quantization": "Q4_K_M", "role": "Anthropic-style Contextual RAG prefix enrichment"},
                {"model": "deepseek-r1:1.5b", "runtime": "ollama", "quantization": "Q4_K_M", "role": "Chain-of-thought root-cause incident synthesis"},
                {"model": "glm4:9b", "runtime": "ollama", "quantization": "Q4_0", "role": "GraphRAG entity & tool-resource triple extraction"},
            ],
        }
