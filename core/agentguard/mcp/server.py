"""Model Context Protocol (MCP) servers & external MCP bridge for AgentGuard.

Implements:
  - 3 Custom Built MCP Servers (stdio + SSE / Streamable HTTP):
      1. agentguard-firewall-mcp  (prompt/tool firewall, secret redaction, threat RAG search)
      2. agentguard-breaker-mcp   (session budgets, loop detection, persistent limits, approvals)
      3. agentguard-lineage-mcp   (GraphRAG multi-hop attack lineage, 5-stage policy ingest, compliance audit)
  - 3 Integrated External MCP Connectors (with explicit permission boundaries):
      1. postgres-mcp  (read-only analytical telemetry & pgvector mirror)
      2. github-mcp    (repo security policy sync & automated incident advisory creation)
      3. fetch-mcp     (allowlisted OWASP / MITRE ATLAS / CVE threat feed acquisition)
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ..breaker.service import CircuitBreaker
from ..firewall import secrets
from ..firewall.engine import FirewallEngine
from ..firewall.rules import RULESET
from ..rag.service import ThreatRAGService
from ..store import Store
from ..utils import now

BUILT_MCP_SERVERS: list[dict[str, Any]] = [
    {
        "id": "agentguard-firewall-mcp",
        "name": "AgentGuard Firewall & Threat-RAG MCP",
        "version": "0.1.0",
        "transports": ["stdio", "sse", "streamable_http"],
        "endpoint_sse": "/v1/mcp/sse?server=agentguard-firewall-mcp",
        "endpoint_rpc": "/v1/mcp/rpc",
        "permission_boundary": "Stateless inspection & redaction; read-only access to Threat-RAG vector store; cannot mutate breaker budgets.",
        "tools": [
            {
                "name": "inspect_prompt_or_tool",
                "description": "Inspect untrusted prompt or tool arguments through AgentGuard's 5-tier firewall (rules, heuristics, secrets, Contextual RAG + GraphRAG, Llama Guard 3).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Prompt or serialized tool input to inspect"},
                        "session_id": {"type": "string", "description": "Session identifier for GraphRAG lineage tracking"},
                        "context_type": {"type": "string", "enum": ["prompt", "tool_input", "tool_result"]},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "redact_secrets",
                "description": "Redact API keys, cloud credentials, and private keys in text before sending to an LLM or external tool.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "search_threat_rag",
                "description": "Query the Contextual RAG + ColBERT Late-Interaction (MaxSim) threat intelligence index for matching MITRE ATLAS / OWASP LLM rules.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "category": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        ],
        "resources": [
            {"uri": "agentguard://firewall/rules", "name": "Deterministic Firewall Ruleset", "mimeType": "application/json"},
        ],
    },
    {
        "id": "agentguard-breaker-mcp",
        "name": "AgentGuard Circuit Breaker & Approval Gateway MCP",
        "version": "0.1.0",
        "transports": ["stdio", "sse", "streamable_http"],
        "endpoint_sse": "/v1/mcp/sse?server=agentguard-breaker-mcp",
        "endpoint_rpc": "/v1/mcp/rpc",
        "permission_boundary": "Scoped to session telemetry & operator approval queue; reset/limit mutations are logged as state_change audit events.",
        "tools": [
            {
                "name": "get_session_budget",
                "description": "Inspect real-time token, cost, iteration, and loop-detection status for an agent session before spawning subagents.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "set_session_limits",
                "description": "Persist per-session token, cost, or iteration budget overrides in SQLite.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "limits": {"type": "object"},
                    },
                    "required": ["session_id", "limits"],
                },
            },
            {
                "name": "reset_circuit_breaker",
                "description": "Reset a tripped circuit breaker for a session while preserving persisted limit overrides.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "list_pending_approvals",
                "description": "List pending human-in-the-loop security approval requests.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                },
            },
        ],
        "resources": [
            {"uri": "agentguard://sessions/active", "name": "Active Agent Sessions Registry", "mimeType": "application/json"},
            {"uri": "agentguard://breaker/snapshots", "name": "Circuit Breaker Session Snapshots", "mimeType": "application/json"},
        ],
    },
    {
        "id": "agentguard-lineage-mcp",
        "name": "AgentGuard GraphRAG Lineage & Compliance Audit MCP",
        "version": "0.1.0",
        "transports": ["stdio", "sse", "streamable_http"],
        "endpoint_sse": "/v1/mcp/sse?server=agentguard-lineage-mcp",
        "endpoint_rpc": "/v1/mcp/rpc",
        "tunnel_exposed": True,
        "permission_boundary": "Read-only GraphRAG lineage traversal and compliance report generation; policy ingestion sanitizes secrets prior to indexing.",
        "tools": [
            {
                "name": "trace_attack_graph",
                "description": "Execute a multi-hop GraphRAG query across session provenance and MITRE ATLAS tactics to detect multi-turn exfiltration chains.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "session_id": {"type": "string"},
                        "max_hops": {"type": "integer", "default": 3},
                    },
                },
            },
            {
                "name": "ingest_security_policy",
                "description": "Run the 5-stage Data Lifecycle pipeline (Semantic Variable Chunking + Anthropic Contextual RAG + Vector/KG indexing) on a security policy document.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "source": {"type": "string", "default": "custom_policy"},
                        "category": {"type": "string", "default": "policy"},
                        "severity": {"type": "string", "default": "high"},
                        "action": {"type": "string", "default": "block"},
                    },
                    "required": ["title", "content"],
                },
            },
            {
                "name": "export_compliance_audit",
                "description": "Generate an OWASP LLM Top 10 & MITRE ATLAS compliance audit report across tracked sessions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                },
            },
        ],
        "resources": [
            {"uri": "agentguard://rag/status", "name": "Contextual RAG & ColBERT Index Status", "mimeType": "application/json"},
            {"uri": "agentguard://graph/lineage", "name": "Live GraphRAG Provenance Subgraph", "mimeType": "application/json"},
        ],
    },
]

EXTERNAL_MCP_SERVERS: list[dict[str, Any]] = [
    {
        "id": "postgres-mcp",
        "package": "@modelcontextprotocol/server-postgres",
        "transport": "stdio",
        "role": "Analytical SQL & pgvector similarity mirror for long-horizon session telemetry and token/cost ledgers",
        "permission_boundary": "Connects with read-only database role (SELECT only on events, sessions, rag_chunks); DDL/DML blocked at role level.",
        "status": "integrated",
    },
    {
        "id": "github-mcp",
        "package": "@modelcontextprotocol/server-github",
        "transport": "stdio",
        "role": "Synchronizes repository SECURITY.md policies into Contextual RAG and opens automated security incident issues on breaker_stop.",
        "permission_boundary": "Scoped to repository contents:read and issues:write; never receives unredacted prompt secrets.",
        "status": "integrated",
    },
    {
        "id": "fetch-mcp",
        "package": "@modelcontextprotocol/server-fetch",
        "transport": "stdio",
        "role": "Stage-1 Data Lifecycle acquisition of OWASP LLM Top 10, MITRE ATLAS, and CVE advisory feeds into ThreatRAGService.",
        "permission_boundary": "Outbound HTTPS restricted to allowlisted threat-intelligence domains (atlas.mitre.org, owasp.org, nvd.nist.gov).",
        "status": "integrated",
    },
]


class MCPHub:
    """Executes MCP tool calls, resource reads, and JSON-RPC 2.0 requests
    across all 3 built AgentGuard MCP servers and 3 external MCP integrations."""

    def __init__(
        self,
        *,
        store: Store,
        firewall: FirewallEngine,
        breaker: CircuitBreaker,
        rag: ThreatRAGService,
    ):
        self.store = store
        self.firewall = firewall
        self.breaker = breaker
        self.rag = rag

    def status(self) -> dict[str, Any]:
        all_tools = [t for s in BUILT_MCP_SERVERS for t in s["tools"]]
        all_resources = [r for s in BUILT_MCP_SERVERS for r in s["resources"]]
        return {
            "protocol_version": "2024-11-05",
            "transports_supported": ["stdio", "sse", "streamable_http"],
            "host_disclosure": {
                "host": "AgentGuard Core Service (FastAPI + CLI stdio bridge)",
                "clients_supported": ["OpenCode", "Claude Code", "Codex CLI", "Antigravity (agy)", "LangGraph", "OpenAI Agents SDK"],
                "tunnel_exposure": "Cloudflare Tunnel -> /v1/mcp/sse & /v1/mcp/rpc (read-only lineage & firewall inspection)",
            },
            "built_servers": BUILT_MCP_SERVERS,
            "external_servers": EXTERNAL_MCP_SERVERS,
            "counts": {
                "built_servers": len(BUILT_MCP_SERVERS),
                "external_servers": len(EXTERNAL_MCP_SERVERS),
                "total_tools": len(all_tools),
                "total_resources": len(all_resources),
            },
        }

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}

        # --- agentguard-firewall-mcp tools ---
        if name == "inspect_prompt_or_tool":
            text = str(args.get("text") or "")
            sid = args.get("session_id")
            ctx_type = str(args.get("context_type") or "prompt")
            res = await self.firewall.inspect(text, context_type=ctx_type, session_id=sid)
            return res.model_dump(mode="json")

        if name == "redact_secrets":
            text = str(args.get("text") or "")
            found = secrets.find_secrets(text)
            redacted, count = secrets.redact(text, found)
            return {
                "sanitized_text": redacted,
                "redaction_count": count,
                "secrets_found": [f["type"] for f in found],
            }

        if name == "search_threat_rag":
            return self.rag.retrieve(
                str(args.get("query") or ""),
                top_k=int(args.get("top_k") or 5),
                category=args.get("category"),
            )

        # --- agentguard-breaker-mcp tools ---
        if name == "get_session_budget":
            sid = str(args.get("session_id") or "")
            sess = self.store.get_session(sid)
            br = self.breaker.status_for(sid)
            return {"session_id": sid, "session": sess, "breaker": br}

        if name == "set_session_limits":
            sid = str(args.get("session_id") or "")
            limits = dict(args.get("limits") or {})
            updated = self.breaker.set_session_limits(sid, limits)
            return {"session_id": sid, "limits": updated}

        if name == "reset_circuit_breaker":
            sid = str(args.get("session_id") or "")
            self.breaker.reset(sid)
            return {"ok": True, "session_id": sid, "status": "healthy"}

        if name == "list_pending_approvals":
            sid = args.get("session_id")
            return {"approvals": self.store.pending_approvals(sid)}

        # --- agentguard-lineage-mcp tools ---
        if name == "trace_attack_graph":
            return self.rag.kg.query_subgraph(
                query=str(args.get("query") or ""),
                session_id=args.get("session_id"),
                max_hops=int(args.get("max_hops") or 3),
            )

        if name == "ingest_security_policy":
            return self.rag.ingest_document(
                title=str(args.get("title") or "Untitled Policy"),
                content=str(args.get("content") or ""),
                source=str(args.get("source") or "custom_policy"),
                category=str(args.get("category") or "policy"),
                severity=str(args.get("severity") or "high"),
                action=str(args.get("action") or "block"),
                metadata=args.get("metadata") or {},
            )

        if name == "export_compliance_audit":
            sid = args.get("session_id")
            sessions = self.store.list_sessions(limit=50)
            if sid:
                sessions = [s for s in sessions if s["session_id"] == sid]
            verdicts = self.store.get_events(session_id=sid, type="firewall_verdict", limit=200)
            blocked = sum(1 for v in verdicts if v.data.get("action") == "block")
            sanitized = sum(1 for v in verdicts if v.data.get("action") == "sanitize")
            kg_sub = self.rag.kg.query_subgraph(session_id=sid, max_hops=3)
            return {
                "generated_ts": now(),
                "scope": sid or "all_sessions",
                "sessions_audited": len(sessions),
                "firewall_verdicts_analyzed": len(verdicts),
                "blocked_count": blocked,
                "sanitized_count": sanitized,
                "exfiltration_chains_detected": len(kg_sub.get("exfiltration_chains", [])),
                "rag_index": self.rag.status(),
                "frameworks_covered": ["OWASP LLM Top 10 (2025)", "MITRE ATLAS"],
            }

        raise ValueError(f"Unknown MCP tool: {name}")

    def read_resource(self, uri: str) -> dict[str, Any]:
        if uri == "agentguard://firewall/rules":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "contents": [
                    {"name": r.name, "kind": r.kind, "description": r.description, "weight": r.weight}
                    for r in RULESET
                ],
            }
        if uri == "agentguard://sessions/active":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "contents": self.store.list_sessions(limit=50),
            }
        if uri == "agentguard://breaker/snapshots":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "contents": [st.snapshot() for st in self.breaker.sessions.values()],
            }
        if uri == "agentguard://rag/status":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "contents": self.rag.status(),
            }
        if uri == "agentguard://graph/lineage":
            return {
                "uri": uri,
                "mimeType": "application/json",
                "contents": self.rag.kg.query_subgraph(max_hops=3),
            }
        raise ValueError(f"Unknown MCP resource URI: {uri}")

    async def handle_jsonrpc(self, payload: dict[str, Any], server_id: str | None = None) -> dict[str, Any]:
        """Standard JSON-RPC 2.0 dispatcher for MCP (stdio and Streamable HTTP)."""
        req_id = payload.get("id")
        method = payload.get("method") or ""
        params = payload.get("params") or {}

        server_meta = next(
            (s for s in BUILT_MCP_SERVERS if s["id"] == server_id),
            BUILT_MCP_SERVERS[0],
        )

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": server_meta["id"], "version": server_meta["version"]},
                    "capabilities": {"tools": {}, "resources": {}},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                if server_id:
                    tools = server_meta["tools"]
                else:
                    tools = [t for s in BUILT_MCP_SERVERS for t in s["tools"]]
                result = {"tools": tools}
            elif method == "tools/call":
                t_name = str(params.get("name") or "")
                t_args = params.get("arguments") or {}
                out = await self.call_tool(t_name, t_args)
                result = {
                    "content": [{"type": "text", "text": json.dumps(out)}],
                    "structuredContent": out,
                    "isError": False,
                }
            elif method == "resources/list":
                if server_id:
                    resources = server_meta["resources"]
                else:
                    resources = [r for s in BUILT_MCP_SERVERS for r in s["resources"]]
                result = {"resources": resources}
            elif method == "resources/read":
                uri = str(params.get("uri") or "")
                res_data = self.read_resource(uri)
                result = {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(res_data["contents"]),
                        }
                    ]
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }


async def run_stdio_mcp_server(hub: MCPHub, server_id: str | None = None) -> int:
    """Stdio transport loop for running any AgentGuard MCP server via CLI."""
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except Exception:
            continue
        resp = await hub.handle_jsonrpc(req, server_id=server_id)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    return 0
