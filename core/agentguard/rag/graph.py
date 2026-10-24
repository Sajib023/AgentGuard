"""GraphRAG / Provenance & Attack-Lineage Knowledge Graph.

Combines a static MITRE ATLAS / OWASP LLM threat taxonomy graph with a live
per-session provenance graph (`Session -> ToolCall -> SensitiveResource ->
ExternalNetworkSink`) to detect multi-hop exfiltration chains across turns.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..db import Database
from ..schema import Event, EventType
from ..utils import new_id, now
from .corpus import SEED_KG_EDGES, SEED_KG_NODES

_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (".env", re.compile(r"(^|[\s/\"'])(\.env(?:\.[a-z0-9_]+)?)\b", re.IGNORECASE)),
    ("ssh_key", re.compile(r"\b(id_rsa|id_ed25519|authorized_keys|\.ssh/[a-z0-9_.-]+)\b", re.IGNORECASE)),
    ("cloud_creds", re.compile(r"(\.aws/credentials|\.config/gcloud|kubeconfig|service[-_]account\.json)", re.IGNORECASE)),
    ("system_secrets", re.compile(r"(/etc/shadow|/etc/passwd|/proc/self/environ)", re.IGNORECASE)),
    ("secret_material", re.compile(r"\b(AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|PRIVATE_KEY)\b")),
]

_NETWORK_SINK_RE = re.compile(
    r"\b(curl|wget|nc|netcat|ncat|scp|rsync|dig|nslookup)\b|"
    r"https?://(?!127\.0\.0\.1|localhost|0\.0\.0\.0)([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
    re.IGNORECASE,
)

_LOCAL_MGMT_RE = re.compile(r"127\.0\.0\.1|localhost|/v1/(breaker|approvals|config|events|sessions|rag|mcp)")


class KnowledgeGraphService:
    def __init__(self, db: Database):
        self.db = db
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        ts = now()
        with self.db.tx() as conn:
            for n in SEED_KG_NODES:
                conn.execute(
                    "INSERT OR IGNORE INTO kg_nodes (id, kind, label, session_id, risk_level, props, updated_ts) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (n["id"], n["kind"], n["label"], None, n.get("risk_level", "low"), json.dumps(n.get("props", {})), ts),
                )
            for e in SEED_KG_EDGES:
                eid = f"seed:{e['src']}->{e['dst']}:{e['relation']}"
                conn.execute(
                    "INSERT OR IGNORE INTO kg_edges (id, src, dst, relation, session_id, weight, props, ts) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (eid, e["src"], e["dst"], e["relation"], None, e.get("weight", 1.0), "{}", ts),
                )

    def upsert_node(
        self,
        node_id: str,
        kind: str,
        label: str,
        *,
        session_id: str | None = None,
        risk_level: str = "low",
        props: dict[str, Any] | None = None,
    ) -> None:
        ts = now()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO kg_nodes (id, kind, label, session_id, risk_level, props, updated_ts) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET label=excluded.label, risk_level=excluded.risk_level, "
                "props=excluded.props, updated_ts=excluded.updated_ts",
                (node_id, kind, label, session_id, risk_level, json.dumps(props or {}), ts),
            )

    def add_edge(
        self,
        src: str,
        dst: str,
        relation: str,
        *,
        session_id: str | None = None,
        weight: float = 1.0,
        props: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> None:
        eid = edge_id or f"edge:{src}->{dst}:{relation}"
        ts = now()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO kg_edges (id, src, dst, relation, session_id, weight, props, ts) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET weight=excluded.weight, props=excluded.props, ts=excluded.ts",
                (eid, src, dst, relation, session_id, weight, json.dumps(props or {}), ts),
            )

    def extract_sensitive_targets(self, text: str) -> list[tuple[str, str]]:
        """Return list of (kind, matched_artifact) for sensitive resources in text."""
        found: list[tuple[str, str]] = []
        raw = text or ""
        for kind, pat in _SENSITIVE_PATTERNS:
            m = pat.search(raw)
            if m:
                val = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(0)
                found.append((kind, val.strip()))
        return found

    def extract_network_sinks(self, text: str) -> list[str]:
        """Return external network commands/domains if text is not local management traffic."""
        raw = text or ""
        if _LOCAL_MGMT_RE.search(raw) and "http" not in raw.replace("http://127.0.0.1", "").replace("http://localhost", ""):
            return []
        sinks: list[str] = []
        for m in _NETWORK_SINK_RE.finditer(raw):
            cmd, domain = m.group(1), m.group(2)
            label = domain or cmd
            if label and label.lower() not in sinks:
                sinks.append(label.lower())
        return sinks

    def observe_event(self, event: Event) -> None:
        """Update session provenance graph from an emitted AgentGuard event."""
        sid = event.session_id
        if not sid or sid == "system":
            return
        sess_node = f"session:{sid}"
        self.upsert_node(
            sess_node,
            "session",
            f"Session {sid[:14]} ({event.agent.value})",
            session_id=sid,
            risk_level="low",
            props={"agent": event.agent.value},
        )
        raw_text = json.dumps(event.data)
        if event.type is EventType.tool_call:
            tool_name = str(event.data.get("name") or "tool")
            tool_node = f"tool:{sid}:{tool_name}"
            self.upsert_node(tool_node, "tool", f"Tool: {tool_name}", session_id=sid, risk_level="low")
            self.add_edge(sess_node, tool_node, "INVOKED_TOOL", session_id=sid)
            self.record_access_from_text(sid, raw_text, source_node=tool_node)
        elif event.type in (EventType.prompt_before, EventType.firewall_verdict):
            self.record_access_from_text(sid, raw_text, source_node=sess_node)

    def record_access_from_text(
        self, session_id: str, text: str, *, source_node: str | None = None
    ) -> dict[str, Any]:
        """Record resource touches into the KG and check for multi-hop exfiltration chains."""
        if not session_id or session_id == "system":
            return {"sensitive_touched": [], "network_sinks": [], "exfiltration_chains": []}

        sess_node = f"session:{session_id}"
        origin = source_node or sess_node
        self.upsert_node(sess_node, "session", f"Session {session_id[:14]}", session_id=session_id)

        sensitive = self.extract_sensitive_targets(text)
        for kind, artifact in sensitive:
            art_node = f"artifact:{session_id}:{kind}"
            self.upsert_node(
                art_node,
                "artifact",
                f"Sensitive: {artifact} ({kind})",
                session_id=session_id,
                risk_level="critical",
                props={"kind": kind, "artifact": artifact},
            )
            self.add_edge(origin, art_node, "READ_SENSITIVE", session_id=session_id, weight=1.0)
            self.add_edge(sess_node, art_node, "READ_SENSITIVE", session_id=session_id, weight=1.0)
            self.add_edge(art_node, "res:sensitive_credentials", "INSTANCE_OF", session_id=session_id, weight=1.0)

        sinks = self.extract_network_sinks(text)
        for sink in sinks:
            sink_node = f"sink:{session_id}:{sink}"
            self.upsert_node(
                sink_node,
                "domain",
                f"External Sink: {sink}",
                session_id=session_id,
                risk_level="high",
                props={"sink": sink},
            )
            self.add_edge(origin, sink_node, "CONNECTED_EXTERNAL", session_id=session_id, weight=1.0)
            self.add_edge(sink_node, "res:external_network", "INSTANCE_OF", session_id=session_id, weight=1.0)

        chains = self.detect_exfiltration_chains(session_id, current_sinks=sinks) if sinks else []
        return {
            "sensitive_touched": [a for _, a in sensitive],
            "network_sinks": sinks,
            "exfiltration_chains": chains,
        }

    def detect_exfiltration_chains(
        self, session_id: str, *, current_sinks: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Multi-hop GraphRAG query over session provenance + MITRE ATLAS taxonomy:

        Hop 1: (session:<sid>) -[READ_SENSITIVE]-> (artifact:<sid>:<kind>)
        Hop 2: (artifact:<sid>:<kind>) -[INSTANCE_OF]-> (res:sensitive_credentials)
        Hop 3: (session:<sid> | tool) -[CONNECTED_EXTERNAL]-> (sink:<sid>:<net>) -> (tech:AML.T0048)
        """
        if not session_id:
            return []
        prior_sensitive = self.db.query(
            """
            SELECT n.id, n.label, n.props, e.ts
            FROM kg_edges e
            JOIN kg_nodes n ON n.id = e.dst
            WHERE e.session_id = ? AND e.relation = 'READ_SENSITIVE'
            ORDER BY e.ts DESC
            """,
            (session_id,),
        )
        if not prior_sensitive:
            return []

        sinks = list(current_sinks or [])
        if not sinks:
            sink_rows = self.db.query(
                """
                SELECT n.label, n.props
                FROM kg_edges e
                JOIN kg_nodes n ON n.id = e.dst
                WHERE e.session_id = ? AND e.relation = 'CONNECTED_EXTERNAL'
                ORDER BY e.ts DESC
                """,
                (session_id,),
            )
            for r in sink_rows:
                props = json.loads(r["props"] or "{}")
                if props.get("sink"):
                    sinks.append(props["sink"])

        if not sinks:
            return []

        chains: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for s_row in prior_sensitive:
            s_props = json.loads(s_row["props"] or "{}")
            artifact = s_props.get("artifact") or s_row["label"]
            for sink in sinks:
                pair = (artifact, sink)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                # Record the discovered multi-hop exfiltration edge in the KG
                self.add_edge(
                    s_row["id"],
                    f"sink:{session_id}:{sink}",
                    "EXFILTRATION_PATH",
                    session_id=session_id,
                    weight=0.95,
                    props={"tactic": "AML.T0048", "artifact": artifact, "sink": sink},
                )
                chains.append({
                    "session_id": session_id,
                    "tactic": "AML.T0048",
                    "tactic_name": "MITRE ATLAS AML.T0048 — Multi-Hop Credential Exfiltration",
                    "sensitive_artifact": artifact,
                    "external_sink": sink,
                    "hops": [
                        f"session:{session_id}",
                        f"READ_SENSITIVE -> {artifact}",
                        "INSTANCE_OF -> res:sensitive_credentials",
                        f"EXFILTRATION_PATH -> {sink} (res:external_network)",
                        "MATCHES -> tech:AML.T0048",
                    ],
                    "confidence": 0.92,
                    "weight": 80.0,
                })
        return chains

    def query_subgraph(
        self,
        *,
        query: str = "",
        session_id: str | None = None,
        max_hops: int = 3,
        limit: int = 60,
    ) -> dict[str, Any]:
        """Retrieve relevant Knowledge Graph nodes, edges, and multi-hop paths."""
        q_lower = (query or "").strip().lower()
        if session_id:
            node_rows = self.db.query(
                "SELECT * FROM kg_nodes WHERE session_id IS NULL OR session_id = ? ORDER BY updated_ts DESC LIMIT ?",
                (session_id, limit),
            )
            edge_rows = self.db.query(
                "SELECT * FROM kg_edges WHERE session_id IS NULL OR session_id = ? ORDER BY ts DESC LIMIT ?",
                (session_id, limit * 2),
            )
        else:
            node_rows = self.db.query("SELECT * FROM kg_nodes ORDER BY updated_ts DESC LIMIT ?", (limit,))
            edge_rows = self.db.query("SELECT * FROM kg_edges ORDER BY ts DESC LIMIT ?", (limit * 2,))

        nodes = [
            {
                "id": r["id"],
                "kind": r["kind"],
                "label": r["label"],
                "session_id": r["session_id"],
                "risk_level": r["risk_level"],
                "props": json.loads(r["props"] or "{}"),
            }
            for r in node_rows
        ]
        edges = [
            {
                "id": r["id"],
                "src": r["src"],
                "dst": r["dst"],
                "relation": r["relation"],
                "session_id": r["session_id"],
                "weight": r["weight"],
                "props": json.loads(r["props"] or "{}"),
            }
            for r in edge_rows
        ]

        # Build adjacency for multi-hop path traversal
        adj: dict[str, list[tuple[str, str]]] = {}
        node_map = {n["id"]: n for n in nodes}
        for e in edges:
            adj.setdefault(e["src"], []).append((e["relation"], e["dst"]))

        # Find seed nodes matching query terms (or high-risk nodes if query is empty)
        q_terms = [t for t in re.findall(r"[a-z0-9_.-]{2,}", q_lower) if len(t) >= 2]
        seed_ids: list[str] = []
        for n in nodes:
            hay = f"{n['id']} {n['label']} {n['kind']} {json.dumps(n['props'])}".lower()
            if q_terms and any(t in hay for t in q_terms):
                seed_ids.append(n["id"])
            elif not q_terms and n["risk_level"] in ("critical", "high"):
                seed_ids.append(n["id"])

        paths: list[dict[str, Any]] = []
        hops_clamped = max(1, min(max_hops, 4))
        for start_id in seed_ids[:10]:
            # BFS up to max_hops
            frontier: list[tuple[str, list[str]]] = [(start_id, [ node_map.get(start_id, {}).get("label", start_id) ])]
            visited = {start_id}
            for _ in range(hops_clamped):
                next_frontier: list[tuple[str, list[str]]] = []
                for curr, trail in frontier:
                    for rel, nxt in adj.get(curr, []):
                        nxt_label = node_map.get(nxt, {}).get("label", nxt)
                        step_trail = [*trail, f"--[{rel}]--> {nxt_label}"]
                        if len(step_trail) >= 2:
                            paths.append({
                                "start": start_id,
                                "end": nxt,
                                "hops": len(step_trail) - 1,
                                "path": " ".join(step_trail),
                            })
                        if nxt not in visited:
                            visited.add(nxt)
                            next_frontier.append((nxt, step_trail))
                frontier = next_frontier

        active_chains = self.detect_exfiltration_chains(session_id) if session_id else []
        return {
            "nodes": nodes,
            "edges": edges,
            "multi_hop_paths": paths[:20],
            "exfiltration_chains": active_chains,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "paths_discovered": len(paths),
            },
        }
