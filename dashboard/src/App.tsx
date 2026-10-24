import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { useLiveFeed } from "./useLiveFeed";
import EventFeed from "./components/EventFeed";
import { MCPAdminWorkspace, ModeSwitch, ThreatRAGWorkspace } from "./components/Panels";
import { AttentionQueue, FirewallOverview, IncidentTrail, SessionList, TokenUsage } from "./components/Console";
import Icon, { type IconName } from "./components/Icon";
import GuardStatus from "./components/GuardStatus";
import UsageWorkspace from "./components/UsageWorkspace";
import type { ApprovalRow, BreakerSnapshot, Health, SessionRow } from "./types";

export type WorkspaceTab = "monitor" | "usage" | "rag" | "mcp";
type Pane = "events" | "sessions" | "attention";
const workspaces: { id: WorkspaceTab; label: string; short: string; icon: IconName; description: string }[] = [
  { id: "monitor", label: "Live Monitor", short: "Monitor", icon: "monitor", description: "Every agent. Every decision. One place to investigate." },
  { id: "usage", label: "Token flow & costs", short: "Usage", icon: "usage", description: "Track token flow and recorded spend across models and agent sessions." },
  { id: "rag", label: "Threat RAG", short: "Threat RAG", icon: "shield", description: "Find the policy evidence behind an agent's activity." },
  { id: "mcp", label: "MCP & Policy", short: "MCP & policy", icon: "network", description: "Inspect your tools, permission boundaries, and session budgets." },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("monitor");
  const [pane, setPane] = useState<Pane>("events");
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [snaps, setSnaps] = useState<BreakerSnapshot[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const [updated, setUpdated] = useState<Date | null>(null);
  const [focusedEvent, setFocusedEvent] = useState<string | null>(null);
  const feed = useLiveFeed(selected);
  const workspaceRef = useRef<HTMLElement>(null);
  useEffect(() => { workspaceRef.current?.scrollTo({ top: 0 }); }, [activeTab]);

  const refresh = useCallback(() => {
    const fetchResource = <T,>(key: string, request: Promise<T>, apply: (data: T) => void) => request.then(data => {
      apply(data); setErrors(prev => ({ ...prev, [key]: "" }));
      if (key === "health") setUpdated(new Date());
    }).catch(() => setErrors(prev => ({ ...prev, [key]: `Couldn't load ${key === "health" ? "engine status" : key}.` }))).finally(() => setLoaded(prev => ({ ...prev, [key]: true })));
    return Promise.all([
      fetchResource("health", api.health(), setHealth),
      fetchResource("sessions", api.sessions(), r => setSessions(r.sessions)),
      fetchResource("breakers", api.breakerAll(), r => setSnaps(r.sessions)),
      fetchResource("approvals", api.approvals(), r => setApprovals(r.approvals)),
    ]);
  }, []);
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 4000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => { void refresh(); }, [Math.floor(feed.pulse / 5), refresh]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const disclosure = document.querySelector<HTMLDetailsElement>("details[open]");
      if (disclosure) { disclosure.open = false; disclosure.querySelector<HTMLElement>("summary")?.focus(); return; }
      if (focusedEvent) setFocusedEvent(null);
      else if (pane !== "events") setPane("events");
      else if (selected) setSelected(null);
      else if (activeTab !== "monitor") setActiveTab("monitor");
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [selected, activeTab, pane, focusedEvent]);

  const selectSession = (id: string | null) => { setSelected(id); setFocusedEvent(null); setPane("events"); };
  const selectedEvents = useMemo(() => selected ? feed.events.filter(e => e.session_id === selected) : feed.events, [feed.events, selected]);
  const resolve = async (id: string, approved: boolean) => { await api.resolveApproval(id, approved); await refresh(); };
  const resetBreaker = async (id: string) => { await api.resetBreaker(id); await refresh(); };
  const breachedCount = snaps.filter(s => s.status !== "healthy").length;
  const attentionCount = approvals.length + breachedCount;
  const workspace = workspaces.find(w => w.id === activeTab)!;
  const apiAvailable = loaded.health && !errors.health;
  let finding = "Monitoring connected. No intervention pending across all sessions.";
  if (!loaded.health) finding = "Connecting to your local safety engine…";
  else if (errors.health) finding = "Engine unavailable. Last received data is kept in view.";
  else if (!feed.connected) finding = "Live stream disconnected. Checking for new events with REST backfill.";
  else if (!loaded.approvals || !loaded.breakers) finding = "Checking approvals and circuit breakers…";
  else if (errors.approvals || errors.breakers) finding = "Attention status unavailable. Refresh to check approvals and circuit breakers.";
  else if (attentionCount) finding = `${approvals.length} pending approval${approvals.length === 1 ? "" : "s"} · ${breachedCount} circuit breaker signal${breachedCount === 1 ? "" : "s"} across all sessions.`;
  return <div className="app console-app">
    <nav className="navigation-rail" aria-label="Workspace navigation">
      <a className="rail-brand" href="#" aria-label="AgentGuard monitor" onClick={e => { e.preventDefault(); setActiveTab("monitor"); }}>AG<span /></a>
      <div className="rail-destinations">{workspaces.map(w => <button key={w.id} onClick={() => setActiveTab(w.id)} aria-label={w.label} aria-current={activeTab === w.id ? "page" : undefined} title={w.label} className={activeTab === w.id ? "active" : ""}><Icon name={w.icon} /><span>{w.short}</span>{w.id === "monitor" && attentionCount > 0 && <i className="nav-attention" />}</button>)}</div>
      <div className="rail-bottom" title="Local-first runtime"><Icon name="shield" size={17} /><span>Local</span></div>
    </nav>
    <div className="console-body">
      <header className="console-header">
        <div className="console-wordmark">Agent<span>Guard</span><span className="header-divider" /><span className="header-workspace">{workspace.short}</span></div>
        <div className="header-controls">
          <GuardStatus health={health} loading={!loaded.health} unavailable={Boolean(errors.health)} className="guard-desktop" />
          <button className="scope-control" onClick={() => { setActiveTab("monitor"); setPane(pane === "sessions" ? "events" : "sessions"); }} title="Choose a session"><span className="status-dot" />{selected ? selected.slice(0, 12) : "All agents"}<Icon name="chevron" size={13} /></button>
          <details className="service-popover" onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.open = false; e.stopPropagation(); } }}>
            <summary><span className={`status-dot ${feed.connected ? "live" : "warning"}`} /><span>{feed.connected ? "Live" : "Reconnecting"}</span></summary>
            <div><strong>Service status</strong><p>Engine API <span>{!loaded.health ? "Connecting" : apiAvailable ? "Available" : "Unavailable"}</span></p><p>Event socket <span>{feed.connected ? "Connected" : "Disconnected"}</span></p><p>Llama Guard <span>{apiAvailable ? health?.llm_guard ?? "Disabled" : "Unknown"}</span></p><p>Last API update <span>{updated?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) ?? "—"}</span></p></div>
          </details>
          <ModeSwitch />
        </div>
      </header>
      <div className="guard-mobile-bar"><GuardStatus health={health} loading={!loaded.health} unavailable={Boolean(errors.health)} /></div>
      <main ref={workspaceRef} className={`console-workspace workspace-${activeTab}`}>
        <div className="workspace-heading"><div><div className="title-line"><h1>{workspace.label}</h1>{activeTab === "monitor" && <span className="live-caption"><span className={`status-dot ${feed.connected ? "live" : ""}`} />Runtime observability</span>}</div><p>{activeTab === "monitor" ? finding : workspace.description}</p></div><div className="heading-actions">{selected && <button className="text-button" onClick={() => selectSession(null)}>All agents<Icon name="close" size={13} /></button>}{activeTab !== "usage" && <button className="icon-button" onClick={() => void refresh()} aria-label="Refresh dashboard" title="Refresh dashboard"><Icon name="refresh" size={17} /></button>}</div></div>
        {activeTab === "monitor" && <>
          <IncidentTrail events={selectedEvents} onSelect={id => { setFocusedEvent(id); setPane("events"); }} />
          {feed.error && <div className="inline-error" role="status">{feed.error}{feed.lastUpdated && ` Last updated ${new Date(feed.lastUpdated).toLocaleTimeString()}.`}</div>}
          <div className="monitor-pane-tabs line-tabs">{(["events", "sessions", "attention"] as Pane[]).map(p => <button key={p} className={pane === p ? "active" : ""} aria-pressed={pane === p} onClick={() => setPane(p)}>{p[0].toUpperCase() + p.slice(1)}{p === "attention" && attentionCount > 0 && <span>{attentionCount}</span>}</button>)}</div>
          <div className={`monitor-grid pane-${pane}`}>
            <aside className="sessions-column"><SessionList sessions={sessions} selected={selected} onSelect={selectSession} loading={!loaded.sessions} error={errors.sessions} onRetry={() => void refresh()} /></aside>
            <div className="events-column"><EventFeed events={selectedEvents} connected={feed.connected} sessionFilter={selected} onClear={feed.clear} focusedEvent={focusedEvent} onFocusEvent={setFocusedEvent} /></div>
            <aside className="context-column">
              <AttentionQueue approvals={approvals} snaps={snaps} onResolve={resolve} onReset={resetBreaker} error={errors.approvals || errors.breakers} loading={!loaded.approvals || !loaded.breakers} onRetry={() => void refresh()} />
              {feed.loaded ? <><FirewallOverview events={selectedEvents} /><div className="usage-monitor-link"><TokenUsage events={selectedEvents} /><button className="text-button" onClick={() => setActiveTab("usage")}>View token flow & costs<Icon name="arrow" size={14} /></button></div></> : <>
                <section className="context-section"><div className="section-heading"><h2>Firewall</h2></div><p className="section-note">{feed.error ? "Event history unavailable" : "Loading verdicts…"}</p></section>
                <section className="context-section"><div className="section-heading"><h2>Token usage</h2></div><p className="section-note">{feed.error ? "Event history unavailable" : "Loading usage…"}</p></section>
              </>}
              <section className="service-links">
                <button onClick={() => setActiveTab("rag")}><Icon name="shield" size={16} /><span>Threat RAG<small>{apiAvailable && health?.rag_chunks != null ? `${health.rag_chunks} indexed chunks` : "Index status unavailable"}</small></span><Icon name="arrow" size={15} /></button>
                <button onClick={() => setActiveTab("mcp")}><Icon name="network" size={16} /><span>MCP & policy<small>{apiAvailable && health?.mcp_servers != null ? `${health.mcp_servers} built-in servers` : "Server status unavailable"}</small></span><Icon name="arrow" size={15} /></button>
              </section>
            </aside>
          </div>
        </>}
        {activeTab === "usage" && <UsageWorkspace sessionId={selected} sessions={sessions} onSelectSession={id => { setSelected(id); setFocusedEvent(null); }} />}
        {activeTab === "rag" && <ThreatRAGWorkspace sessionId={selected} />}
        {activeTab === "mcp" && <MCPAdminWorkspace sessionId={selected} sessions={sessions} snaps={snaps} onResetBreaker={resetBreaker} onRefresh={() => void refresh()} />}
      </main>
      <footer className="console-footer"><span><span className={`status-dot ${apiAvailable ? "live" : ""}`} />{!loaded.health ? "Connecting" : apiAvailable ? "Engine connected" : "Engine unavailable"}<span className="footer-scope"> / {selected ? `Session ${selected.slice(0, 10)}` : "All agents"}</span></span><span>{health && <span>v{health.version} <span className="footer-scope">· {Math.floor(health.uptime_seconds / 60)}m uptime · </span></span>}{feed.events.length} events in buffer</span></footer>
    </div>
  </div>;
}
