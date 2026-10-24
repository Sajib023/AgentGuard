"""FastAPI application: REST + WebSocket endpoints for adapters and dashboard.

One "shared core" service: events, sessions, firewall, breaker, approvals,
and the live WebSocket feed the dashboard consumes.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .breaker.service import CircuitBreaker
from .bus import EventBus
from .config import Config, default_db_path
from .db import Database
from .firewall.engine import FirewallEngine
from .mcp.server import MCPHub
from .rag.service import ThreatRAGService
from .schema import AgentKind, Event, EventIn, EventType, FirewallAction, new_event_from
from .security import (
    LOGIN_PAGE_HTML,
    TOKEN_COOKIE,
    AuthManager,
    AuthMiddleware,
)
from .store import Store
from .tunnel import read_tunnel_url, setup_tunnel, TunnelManager
from .utils import now, sha256_text, truncate


@dataclass
class AppContext:
    config: Config
    db: Database
    store: Store
    bus: EventBus
    firewall: FirewallEngine
    breaker: CircuitBreaker
    rag: ThreatRAGService
    mcp: MCPHub
    auth: AuthManager
    tunnel: TunnelManager | None = None
    approval_futures: dict[str, asyncio.Future] = field(default_factory=dict)
    start_ts: float = field(default_factory=now)


class IngestBody(BaseModel):
    events: list[EventIn]


class SessionBody(BaseModel):
    pid: int | None = None
    ppid: int | None = None


class CheckBody(BaseModel):
    text: str
    session_id: str | None = None
    agent: str | None = None
    direction: str = "inbound"          # inbound | outbound
    context_type: str = "prompt"        # prompt | tool_input | tool_result
    await_approval: bool = False
    approval_timeout: float | None = None


class ResolveBody(BaseModel):
    approved: bool = False
    by: str = "dashboard"


class ModeBody(BaseModel):
    mode: str


class LimitsBody(BaseModel):
    session_id: str | None = None
    agent: str | None = None
    limits: dict | None = None


class RAGQueryBody(BaseModel):
    query: str
    top_k: int = 5
    category: str | None = None
    session_id: str | None = None
    include_graph: bool = True


class RAGIngestBody(BaseModel):
    title: str
    content: str
    source: str = "custom_policy"
    category: str = "policy"
    severity: str = "high"
    action: str = "block"
    doc_id: str | None = None
    metadata: dict | None = None


class MCPCallBody(BaseModel):
    name: str
    arguments: dict | None = None


class LoginBody(BaseModel):
    code: str


def create_app(config: Config | None = None, tunnel_on_url=None) -> FastAPI:
    cfg = config or Config.load()
    db = Database(cfg.server.db_path or default_db_path())
    store = Store(db)
    bus = EventBus()
    rag = ThreatRAGService(db)
    fw = FirewallEngine(cfg.firewall, rag=rag)
    breaker = CircuitBreaker(cfg.breaker, store, bus)
    mcp = MCPHub(store=store, firewall=fw, breaker=breaker, rag=rag)
    ctx = AppContext(
        config=cfg, db=db, store=store, bus=bus,
        firewall=fw, breaker=breaker, rag=rag, mcp=mcp,
        auth=AuthManager(
            enabled=cfg.auth.enabled,
            code_length=cfg.auth.code_length,
            max_attempts=cfg.auth.max_attempts,
            lockout_seconds=cfg.auth.lockout_seconds,
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.pruned_on_start = store.prune(now() - cfg.server.retention_hours * 3600)
        if cfg.tunnel.enabled and not ctx.tunnel:
            # cloudflared publishes a public URL for the one running server;
            # started here so the daemon/CLI only carries this app instance.
            _tunnel = setup_tunnel(cfg=cfg, on_url=tunnel_on_url)
            ctx.tunnel = _tunnel
        yield
        if ctx.tunnel is not None:
            ctx.tunnel.stop()
            ctx.tunnel = None
        if fw.llm is not None:
            await fw.llm.aclose()
        db.close()

    app = FastAPI(title="AgentGuard", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(AuthMiddleware, auth=ctx.auth)

    def agent_kind(name: str | None) -> AgentKind:
        try:
            return AgentKind(name or "generic")
        except ValueError:
            return AgentKind.generic

    async def record(event: Event) -> None:
        """Insert + broadcast an event; the breaker and GraphRAG consume it."""
        store.insert(event)
        rag.kg.observe_event(event)
        await bus.publish(event)
        for derived in breaker.observe_event(event):
            store.insert(derived)
            rag.kg.observe_event(derived)
            await bus.publish(derived)

    async def ingest(event_in: EventIn) -> Event:
        ev = new_event_from(event_in)
        await record(ev)
        return ev

    # ----------------------------------------------------------- lifecycle
    @app.get("/v1/healthz")
    async def healthz() -> dict:
        llm_status = None
        if fw.llm_enabled:
            llm_status = "reachable" if await fw.llm.is_available() else "unavailable"
        return {
            "status": "ok",
            "version": "0.1.0",
            "uptime_seconds": round(now() - ctx.start_ts, 1),
            "sessions_tracked": len(breaker.sessions),
            "llm_guard": llm_status,
            "observe_mode": cfg.firewall.observe_mode,
            "rag_chunks": rag.status()["contextual_chunks"],
            "mcp_servers": len(mcp.status()["built_servers"]),
            "tunnel_url": read_tunnel_url(),
            "auth_enabled": ctx.auth.enabled,
        }

    # ------------------------------------------------------------------ auth
    @app.get("/login", include_in_schema=False)
    async def login_page():
        return HTMLResponse(LOGIN_PAGE_HTML)

    @app.post("/v1/auth/login")
    async def auth_login(body: LoginBody):
        """Exchange the dashboard access code for a session cookie/token."""
        auth = ctx.auth
        if not auth.enabled:
            return {"ok": True, "auth_enabled": False}
        if auth.is_locked():
            retry_after = auth.retry_after()
            return JSONResponse(
                status_code=429,
                content={"detail": "too many failed attempts — try again later",
                         "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        if not auth.verify_code(body.code):
            retry_after = auth.retry_after()
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid access code" if not auth.is_locked()
                         else "too many failed attempts — try again later",
                         "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        resp = JSONResponse(content={
            "ok": True,
            "token": auth.token,  # also returned for non-cookie API clients
        })
        resp.set_cookie(
            key=TOKEN_COOKIE,
            value=auth.token,
            httponly=True,
            samesite="lax",
            secure=False,  # LAN/testing friendly; the quick tunnel is HTTPS and HttpOnly regardless
            max_age=7 * 24 * 3600,
        )
        return resp

    @app.post("/v1/auth/logout")
    async def auth_logout():
        resp = JSONResponse(content={"ok": True})
        resp.delete_cookie(key=TOKEN_COOKIE)
        return resp

    @app.get("/v1/auth/status")
    async def auth_status(request: Request):
        token = AuthMiddleware._extract_token(request.scope)  # noqa: SLF001 (same package)
        return {
            "auth_enabled": ctx.auth.enabled,
            "authenticated": ctx.auth.enabled and ctx.auth.verify_token(token),
        }

    # -------------------------------------------------------------- events
    @app.post("/v1/events")
    async def post_events(body: IngestBody):
        ids: list[str] = []
        for e in body.events:
            ids.append((await ingest(e)).id)
        return {"accepted": len(ids), "ids": ids}

    @app.get("/v1/events")
    async def get_events(session_id: str | None = None, agent: str | None = None,
                         type: str | None = None, since: float | None = None,
                         limit: int = 200, order: str = "desc"):
        rows = store.get_events(session_id=session_id, agent=agent, type=type,
                                since=since, limit=limit, order=order)
        return {"events": [e.model_dump(mode="json") for e in rows]}

    # ------------------------------------------------------------- sessions
    @app.get("/v1/sessions")
    async def sessions(limit: int = 50):
        return {"sessions": store.list_sessions(limit=limit)}

    @app.get("/v1/sessions/{session_id}")
    async def session_detail(session_id: str):
        s = store.get_session(session_id)
        if not s:
            return JSONResponse(status_code=404, content={"detail": "session not found"})
        return {"session": s, "breaker": breaker.status_for(session_id)}

    @app.get("/v1/sessions/{session_id}/export")
    async def session_export(session_id: str, format: str = "json", order: str = "desc"):
        from fastapi.responses import Response
        s = store.get_session(session_id)
        events_list = [
            e.model_dump(mode="json")
            for e in store.get_events(session_id=session_id, limit=50000, order=order)
        ]
        safe_sid = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_id)[:48]
        if format.lower() == "jsonl":
            lines = [json.dumps(ev) for ev in events_list]
            body = "\n".join(lines) + ("\n" if lines else "")
            return Response(
                content=body,
                media_type="application/x-ndjson",
                headers={"Content-Disposition": f'attachment; filename="agentguard-{safe_sid}.jsonl"'},
            )
        payload = {
            "session_id": session_id,
            "exported_at": now(),
            "order": order,
            "event_count": len(events_list),
            "session": s,
            "breaker": breaker.status_for(session_id),
            "events": events_list,
        }
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="agentguard-{safe_sid}.json"'},
        )

    @app.post("/v1/sessions/{session_id}/pid")
    async def set_pid(session_id: str, body: SessionBody):
        store.set_pid(session_id, body.pid, body.ppid)
        return {"ok": True}

    # ------------------------------------------------------------ firewall
    @app.post("/v1/firewall/check")
    async def firewall_check(body: CheckBody):
        sid = body.session_id or "adhoc"
        result = await fw.inspect(body.text, direction=body.direction,
                                  context_type=body.context_type, session_id=sid)
        agent = agent_kind(body.agent)
        store_content = cfg.firewall.store_prompt_content

        if body.direction == "inbound" and body.text.strip():
            probe: dict = {
                "direction": "inbound",
                "chars": len(body.text),
                "hash": sha256_text(body.text)[:16],
                "context_type": body.context_type,
            }
            if store_content:
                probe["content"] = truncate(body.text, 8000)
            else:
                probe["content"] = ""
            pb = Event(agent=agent, session_id=sid, type=EventType.prompt_before, data=probe)
            store.insert(pb)
            await bus.publish(pb)

        decision = result.model_dump(mode="json")
        verdict = {
            "action": decision["action"],
            "risk_score": decision["risk_score"],
            "reason": decision["decision_reason"],
            "violations": [
                {
                    "kind": v.kind, "rule": v.rule,
                    "snippet": truncate(v.snippet, 80),
                    "confidence": v.confidence, "weight": v.weight,
                    "description": v.description, "details": v.details,
                    "span": list(v.span) if v.span else None,
                }
                for v in result.violations
            ],
            "redaction_count": decision["redaction_count"],
            "meta": decision.get("meta", {}),
        }
        ev = Event(agent=agent, session_id=sid, type=EventType.firewall_verdict, data=verdict)
        store.insert(ev)
        await bus.publish(ev)

        final_action = decision["action"]
        approval = None
        if final_action == FirewallAction.approve.value and body.await_approval:
            approval = store.create_approval(
                session_id=sid, agent=agent.value, metric="firewall",
                value=decision["risk_score"], limit=cfg.firewall.block_threshold,
                reason=decision["decision_reason"], enforcement="pause",
            )
            await record(Event(
                agent=agent, session_id=sid, type=EventType.approval_request,
                data={"metric": "firewall", "reason": decision["decision_reason"],
                      "value": decision["risk_score"], "limit": cfg.firewall.block_threshold},
            ))
            fut = ctx.approval_futures.setdefault(approval["id"], asyncio.Future())
            try:
                timeout = body.approval_timeout or cfg.firewall.approval_timeout_seconds
                approved = await asyncio.wait_for(fut, timeout=max(1.0, timeout))
                if approved:
                    final_action = FirewallAction.sanitize.value
                    decision["decision_reason"] += " | approved after hold"
                else:
                    final_action = FirewallAction.block.value
                    decision["decision_reason"] += " | denied by reviewer"
                store.resolve_approval(approval["id"], "approved" if approved else "denied", "hook")
            except (TimeoutError, asyncio.TimeoutError):
                store.resolve_approval(approval["id"], "expired", "timeout")
                final_action = FirewallAction.block.value
                decision["decision_reason"] += " | approval timed out (denied)"
            finally:
                ctx.approval_futures.pop(approval["id"], None)

        await record(Event(
            agent=agent, session_id=sid, type=EventType.prompt_after,
            data={"direction": body.direction, "action": final_action,
                  "reason": decision["decision_reason"]},
        ))
        return {
            "action": final_action,
            "risk_score": decision["risk_score"],
            "violations": verdict["violations"],
            "sanitized_text": decision.get("sanitized_text", ""),
            "redaction_count": decision["redaction_count"],
            "decision_reason": decision["decision_reason"],
            "meta": decision.get("meta", {}),
            "session_id": sid,
            "approval": approval,
        }

    @app.get("/v1/firewall/rules")
    async def firewall_rules():
        from .firewall.rules import RULESET
        return {"rules": [
            {"name": r.name, "kind": r.kind, "description": r.description,
             "confidence": r.confidence, "weight": r.weight} for r in RULESET
        ]}

    # ------------------------------------------- approvals (dashboard route)
    @app.get("/v1/approvals")
    async def approvals(session_id: str | None = None):
        return {"approvals": store.pending_approvals(session_id)}

    @app.post("/v1/approvals/{aid}/resolve")
    async def resolve_approval(aid: str, body: ResolveBody):
        fut = ctx.approval_futures.get(aid)
        req = store.resolve_approval(aid, "approved" if body.approved else "denied", body.by)
        if fut and not fut.done():
            fut.set_result(body.approved)
            ctx.approval_futures.pop(aid, None)
        if req:
            await record(Event(
                agent=agent_kind(req["agent"]), session_id=req["session_id"],
                type=EventType.approval_decision,
                data={"status": req["status"], "by": req.get("decision_by"),
                      "metric": req.get("metric")},
            ))
        return {"ok": True, "approval": req}

    # -------------------------------------------------------------- breaker
    @app.get("/v1/breaker/status")
    async def breaker_status():
        return {"sessions": [st.snapshot() for st in breaker.sessions.values()]}

    @app.get("/v1/breaker/status/{session_id}")
    async def breaker_one(session_id: str):
        st = breaker.status_for(session_id)
        if st is None:
            return JSONResponse(status_code=404, content={"detail": "no breaker state"})
        return st

    @app.post("/v1/breaker/reset/{session_id}")
    async def breaker_reset(session_id: str):
        breaker.reset(session_id)
        return {"ok": True}

    @app.post("/v1/breaker/limits")
    async def breaker_limits(body: LimitsBody):
        """Runtime per-agent or per-session limit overrides.

        Per-session limits persist (SQLite kv) and survive breaker resets
        and service restarts; they are re-applied whenever session state is
        (re)created."""
        if not body.limits:
            return JSONResponse(status_code=400, content={"detail": "limits object required"})
        if body.session_id:
            limits = breaker.set_session_limits(body.session_id, body.limits)
            return {"session_id": body.session_id, "limits": limits}
        if not body.agent:
            return JSONResponse(status_code=400, content={"detail": "agent or session_id required"})
        cfg.breaker.agent_overrides.setdefault(body.agent, {}).update(body.limits)
        return {"agent": body.agent, "overrides": cfg.breaker.agent_overrides[body.agent]}

    @app.post("/v1/config/mode")
    async def set_mode(body: ModeBody):
        mode = body.mode
        if mode not in ("enforce", "observe"):
            return JSONResponse(status_code=400, content={"detail": "mode must be enforce|observe"})
        cfg.firewall.observe_mode = mode == "observe"
        await record(Event(agent=AgentKind.generic, session_id="system",
                           type=EventType.state_change,
                           data={"state": f"firewall_mode:{mode}"}))
        return {"mode": mode}

    # ---------------------------------------------- Threat-RAG & GraphRAG
    @app.get("/v1/rag/status")
    async def rag_status():
        return rag.status()

    @app.post("/v1/rag/query")
    async def rag_query(body: RAGQueryBody):
        return rag.retrieve(
            body.query,
            top_k=body.top_k,
            category=body.category,
            session_id=body.session_id,
            include_graph=body.include_graph,
        )

    @app.post("/v1/rag/ingest")
    async def rag_ingest(body: RAGIngestBody):
        return rag.ingest_document(
            title=body.title,
            content=body.content,
            source=body.source,
            category=body.category,
            severity=body.severity,
            action=body.action,
            doc_id=body.doc_id,
            metadata=body.metadata,
        )

    @app.get("/v1/graph/lineage")
    async def graph_lineage(
        query: str | None = None,
        session_id: str | None = None,
        max_hops: int = 3,
    ):
        return rag.kg.query_subgraph(
            query=query or "",
            session_id=session_id,
            max_hops=max_hops,
        )

    # ---------------------------------------- MCP (Built + External + SSE)
    @app.get("/v1/mcp/status")
    async def mcp_status():
        return mcp.status()

    @app.post("/v1/mcp/call")
    async def mcp_call(body: MCPCallBody):
        try:
            out = await mcp.call_tool(body.name, body.arguments or {})
            return {"ok": True, "tool": body.name, "result": out}
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.post("/v1/mcp/rpc")
    async def mcp_rpc(request: Request, server: str | None = None):
        payload = await request.json()
        resp = await mcp.handle_jsonrpc(payload, server_id=server)
        return resp

    @app.get("/v1/mcp/sse")
    async def mcp_sse(server: str | None = None):
        server_id = server or "agentguard-lineage-mcp"

        async def event_stream():
            rpc_url = f"/v1/mcp/rpc?server={server_id}"
            yield f"event: endpoint\ndata: {rpc_url}\n\n"
            status_payload = json.dumps({
                "server": server_id,
                "protocol": "2024-11-05",
                "transport": "sse",
                "status": "ready",
            })
            yield f"event: ready\ndata: {status_payload}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ------------------------------------------------------ websocket feed
    @app.websocket("/v1/ws")
    async def ws_feed(ws: WebSocket):
        await ws.accept()
        types_q = ws.query_params.get("types")
        sid_q = ws.query_params.get("session_id")
        replay = int(ws.query_params.get("replay", "0") or 0)
        ts = set(types_q.split(",")) if types_q else None
        sub_id, queue = await bus.subscribe(types=ts)
        stop = asyncio.Event()

        async def reader():
            """Adapters may emit events straight over the socket."""
            try:
                while True:
                    text = await ws.receive_text()
                    if text.strip().lower() == "ping":
                        try:
                            await ws.send_text(json.dumps({"kind": "pong"}))
                        except Exception:
                            break
                        continue
                    try:
                        payload = json.loads(text)
                        await ingest(EventIn.model_validate(payload.get("event", payload)))
                    except Exception:
                        await ws.send_text(json.dumps({"kind": "error", "detail": "bad message"}))
            except WebSocketDisconnect:
                pass
            finally:
                stop.set()

        async def sender():
            try:
                while not stop.is_set():
                    qget = asyncio.ensure_future(queue.get())
                    wstop = asyncio.ensure_future(stop.wait())
                    done, pending = await asyncio.wait(
                        {qget, wstop}, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    if wstop in done:
                        break
                    try:
                        msg = qget.result()
                    except asyncio.CancelledError:
                        break
                    await ws.send_text(msg)
            except Exception:
                stop.set()

        try:
            if replay:
                for ev in reversed(store.get_events(session_id=sid_q, limit=replay, order="desc")):
                    if ts and ev.type.value not in ts:
                        continue
                    await ws.send_text(json.dumps({"kind": "event",
                                                   "event": ev.model_dump(mode="json")}))
            await asyncio.gather(reader(), sender())
        except WebSocketDisconnect:
            pass
        finally:
            await bus.unsubscribe(sub_id)
            try:
                await ws.close()
            except Exception:
                pass

    # ------------------------------------ dashboard static (built React app)
    root = Path(__file__).resolve().parents[2]
    env_dist = os.environ.get("AGENTGUARD_DASHBOARD_DIR", "")
    candidates = [
        Path(cfg.dashboard.dir).expanduser() if cfg.dashboard.dir else None,
        Path(env_dist).expanduser() if env_dist else None,
        root / "dashboard" / "dist",
        (Path(os.environ.get("AGENTGUARD_HOME") or (Path.home() / ".agentguard")) / "app" / "dashboard" / "dist").expanduser(),
    ]
    dist_dir = next((c for c in candidates if c and c.is_dir()), root / "dashboard" / "dist")
    if dist_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(dist_dir / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("v1/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            candidate = (dist_dir / full_path).resolve()
            if candidate.is_file() and str(candidate).startswith(str(dist_dir.resolve())):
                return FileResponse(candidate)
            return FileResponse(dist_dir / "index.html")

    return app

