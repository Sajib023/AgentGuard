import { useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import type { AgentEvent, ApprovalRow, BreakerSnapshot, SessionRow } from "../types";
import Icon from "./Icon";

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="console-empty">{children}</div>;
}
function age(ts: number) {
  const seconds = Math.max(0, Date.now() / 1000 - ts);
  return seconds < 60 ? "just now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
}
export function SessionList({ sessions, selected, onSelect, error, loading, onRetry }: {
  sessions: SessionRow[]; selected: string | null; onSelect: (id: string | null) => void; error?: string; loading: boolean; onRetry: () => void;
}) {
  const [all, setAll] = useState(false);
  const [agent, setAgent] = useState("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const agents = [...new Set(sessions.map(s => s.agent))];
  const filtered = useMemo(() => sessions.filter(s => (agent === "all" || s.agent === agent) && `${s.session_id} ${s.agent} ${s.cwd || ""} ${s.model || ""}`.toLowerCase().includes(query.toLowerCase())).filter(s => all || query || s.session_id === selected || !s.end_ts).sort((a, b) => b.last_ts - a.last_ts), [sessions, selected, all, agent, query]);
  const visible = expanded || query ? filtered : filtered.slice(0, 6);
  const recent = sessions.filter(s => !s.end_ts && Date.now() / 1000 - s.last_ts < 1800).length;
  return <section className="session-browser" aria-label="Agent sessions">
    <div className="section-heading"><h2>Sessions</h2><span className="meta">{loading ? "Loading" : `${sessions.length} total`}</span></div>
    <button className={`global-session ${!selected ? "selected" : ""}`} onClick={() => onSelect(null)} aria-pressed={!selected}><Icon name="activity" /><span>All agents<small>{loading ? "Connecting to your agents" : `${recent} recently active`}</small></span><Icon name="chevron" size={14} /></button>
    <div className="line-tabs session-tabs"><button className={!all ? "active" : ""} onClick={() => { setAll(false); setExpanded(false); }}>Recent</button><button className={all ? "active" : ""} onClick={() => { setAll(true); setExpanded(false); }}>All sessions</button></div>
    <label className="search-control"><Icon name="search" size={15} /><input aria-label="Find a session" placeholder="Find a session…" value={query} onChange={e => setQuery(e.target.value)} /></label>
    {agents.length > 1 && <select aria-label="Filter sessions by agent" value={agent} onChange={e => setAgent(e.target.value)}><option value="all">Every agent</option>{agents.map(a => <option key={a}>{a}</option>)}</select>}
    {error && <div className="inline-error">{error} <button onClick={onRetry}>Retry</button></div>}
    {downloadError && <div className="inline-error" role="status">{downloadError}</div>}
    <div className="console-session-list">{visible.map(s => {
      const state = s.end_ts ? "Ended" : Date.now() / 1000 - s.last_ts < 1800 ? "Recent activity" : "Idle";
      const project = s.cwd?.split("/").filter(Boolean).slice(-1)[0] || s.agent;
      return <article key={s.session_id} className={`console-session ${selected === s.session_id ? "selected" : ""}`}>
        <button className="session-select" aria-pressed={selected === s.session_id} onClick={() => onSelect(s.session_id)}>
          <span className="session-first"><span className={`status-dot ${state === "Recent activity" ? "live" : ""}`} title={state} /><strong title={s.cwd || s.session_id}>{project}</strong><span>{age(s.last_ts)}</span></span>
          <span className="session-identity"><span>{s.agent}</span><code title={s.session_id}>{s.session_id.slice(0, 10)}</code></span>
          <span className="session-model">{s.model?.split("/").pop() || "Model not reported"}</span>
          <span className="session-metrics"><span>{s.prompt_count.toLocaleString()} <small>prompts</small></span><span>{s.tool_calls.toLocaleString()} <small>tools</small></span></span>
          <span className="session-metrics"><span>{s.tokens.toLocaleString()} <small>tokens</small></span><span>${s.cost_usd.toFixed(3)} <small>USD</small></span></span>
        </button>
        <button className="session-export" aria-label={`Download context for ${s.session_id}`} title="Download session context" onClick={() => void api.downloadSessionLog(s.session_id, "context-md").catch(() => setDownloadError("Context download failed. Please try again."))}><Icon name="download" size={14} /></button>
      </article>;
    })}</div>
    {!loading && !error && !filtered.length && <EmptyState>{sessions.length ? "No sessions match this view. Try All sessions." : "No sessions yet. Connect an agent to start monitoring."}</EmptyState>}
    {loading && !sessions.length && <div className="session-skeleton" aria-label="Loading sessions"><span /><span /><span /></div>}
    {filtered.length > 6 && <button className="text-button view-sessions" onClick={() => setExpanded(!expanded)}>{expanded ? "Show fewer" : `View all ${filtered.length} sessions`} <Icon name="arrow" size={14} /></button>}
  </section>;
}

export function AttentionQueue({ approvals, snaps, onResolve, onReset, error, loading, onRetry }: {
  approvals: ApprovalRow[]; snaps: BreakerSnapshot[]; onResolve: (id: string, approved: boolean) => Promise<void>; onReset: (id: string) => Promise<void>; error?: string; loading: boolean; onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const active = snaps.filter(s => s.status !== "healthy");
  const count = approvals.length + active.length;
  const act = async (id: string, action: () => Promise<void>) => {
    setPending(id); setActionError("");
    try { await action(); } catch { setActionError("Action failed. Please try again."); } finally { setPending(null); }
  };
  return <section className={`context-section attention-section ${expanded ? "expanded" : ""}`} id="attention">
    <div className="section-heading"><h2>Attention</h2><span className={`meta ${count ? "text-amber" : ""}`}>{loading ? "Loading" : `${count} signals`}</span></div><p className="section-note">Across all sessions</p>
    {error && <div className="inline-error">{error} <button onClick={onRetry}>Retry</button></div>}
    {actionError && <div className="inline-error" role="alert">{actionError}</div>}
    {!count && !error && <div className="attention-clear"><Icon name="check" size={16} /><span>{loading ? "Checking approvals and budgets…" : "No intervention pending"}</span></div>}
    {approvals.length > 0 && <div className="attention-group"><h3>Approvals <span>{approvals.length}</span></h3>{(expanded ? approvals : approvals.slice(0, 2)).map(a => <article className="attention-item" key={a.id}><div className="attention-identity"><span>{a.agent}</span><code title={a.session_id}>{a.session_id.slice(0, 10)}</code></div><p>{a.reason}</p>{a.metric && <small>{a.metric}: {a.value ?? "—"} / {a.limit ?? "—"}</small>}<div className="attention-actions"><button disabled={pending !== null} onClick={() => void act(a.id, () => onResolve(a.id, true))}>{pending === a.id ? "Saving…" : "Approve"}</button><button disabled={pending !== null} onClick={() => void act(a.id, () => onResolve(a.id, false))}>Deny</button></div></article>)}</div>}
    {active.length > 0 && <div className="attention-group"><h3>Circuit breakers <span>{active.length}</span></h3>{(expanded ? active : active.slice(0, Math.max(0, 2 - Math.min(approvals.length, 2)))).map(s => <article className="attention-item" key={s.session_id}><div className="attention-identity"><span>{s.agent}</span><span className={s.status === "warning" ? "text-amber" : "text-red"}>{s.status}</span></div><code title={s.session_id}>{s.session_id.slice(0, 14)}</code><div className="budget-summary"><span>Tokens</span><span>{(s.usage.input_tokens + s.usage.output_tokens).toLocaleString()} / {s.limits.max_tokens?.toLocaleString() ?? "∞"}</span><span>Iterations</span><span>{s.usage.iterations} / {s.limits.max_iterations ?? "∞"}</span><span>Cost</span><span>${s.usage.cost_usd.toFixed(3)} / {s.limits.max_cost_usd == null ? "∞" : `$${s.limits.max_cost_usd.toFixed(2)}`}</span></div><button className="text-button" disabled={pending !== null} onClick={() => void act(s.session_id, () => onReset(s.session_id))}>{pending === s.session_id ? "Resetting…" : "Reset breaker"}<Icon name="refresh" size={13} /></button></article>)}</div>}
    {count > 0 && <button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? "Collapse details" : `Review ${count} signal${count === 1 ? "" : "s"}`}<Icon name="arrow" size={14} /></button>}
  </section>;
}

export function FirewallOverview({ events }: { events: AgentEvent[] }) {
  const verdicts = events.filter(e => e.type === "firewall_verdict").slice(0, 150);
  const actions = ["allow", "sanitize", "approve", "block"];
  const rules = new Map<string, number>();
  verdicts.forEach(e => (e.data.violations || []).forEach((v: { rule: string }) => rules.set(v.rule, (rules.get(v.rule) || 0) + 1)));
  return <section className="context-section firewall-section"><div className="section-heading"><h2>Firewall</h2><span className="meta">{verdicts.length} verdicts</span></div><div className="verdict-bar" aria-label="Firewall verdict distribution">{actions.map(action => <span key={action} className={`verdict-${action}`} style={{ width: `${verdicts.length ? verdicts.filter(v => v.data.action === action).length / verdicts.length * 100 : 0}%` }} />)}</div><div className="verdict-values">{actions.map(a => <div key={a}><span>{a === "approve" ? "Review" : a[0].toUpperCase() + a.slice(1)}</span><strong className={a === "block" && verdicts.some(v => v.data.action === a) ? "text-red" : ""}>{verdicts.filter(v => v.data.action === a).length}</strong></div>)}</div>{rules.size > 0 && <details className="rules-breakdown"><summary>Top triggered rules</summary>{[...rules.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([rule, count]) => <div className="triggered-rule" key={rule}><code title={rule}>{rule}</code><span>×{count}</span></div>)}</details>}<p className="section-note">Latest 150 verdicts in loaded events</p></section>;
}

export function TokenUsage({ events }: { events: AgentEvent[] }) {
  const calls = events.filter(e => e.type === "llm_call").slice(0, 36).reverse();
  const input = calls.reduce((n, e) => n + Number(e.data.input_tokens || 0), 0);
  const output = calls.reduce((n, e) => n + Number(e.data.output_tokens || 0), 0);
  const peak = Math.max(1, ...calls.map(e => Number(e.data.input_tokens || 0) + Number(e.data.output_tokens || 0)));
  const ceiling = Math.max(10, Math.ceil(peak / (10 ** Math.floor(Math.log10(peak)))) * 10 ** Math.floor(Math.log10(peak)));
  const compact = (n: number) => n >= 1000 ? `${+(n / 1000).toFixed(1)}k` : `${n}`;
  return <section className="context-section token-section"><div className="section-heading"><h2>Token usage</h2><span className="meta">{calls.length} calls</span></div><div className="token-total">{(input + output).toLocaleString()}<span>tokens</span></div><svg className="usage-chart" viewBox="0 0 280 108" role="img" aria-label={`Tokens across ${calls.length} LLM calls. ${input.toLocaleString()} input and ${output.toLocaleString()} output tokens.`}>{[0, .5, 1].map(r => <g key={r}><line x1="37" x2="276" y1={81 - r * 65} y2={81 - r * 65} stroke="var(--border-default)" /><text x="30" y={85 - r * 65} textAnchor="end">{compact(ceiling * r)}</text></g>)}{calls.map((e, i) => { const width = 232 / Math.max(calls.length, 1); const h = Number(e.data.input_tokens || 0) / ceiling * 65; const oh = Number(e.data.output_tokens || 0) / ceiling * 65; return <g key={e.id}><title>{new Date(e.ts * 1000).toLocaleTimeString()}: {Number(e.data.input_tokens || 0).toLocaleString()} input / {Number(e.data.output_tokens || 0).toLocaleString()} output tokens</title><rect x={40 + i * width} y={81 - h} width={Math.max(1, width - 3)} height={h} fill="var(--dev-cyan)" /><rect x={40 + i * width} y={81 - h - oh} width={Math.max(1, width - 3)} height={oh} fill="var(--text-secondary)" /></g>; })}{calls.length > 0 && <><text x="38" y="103">{new Date(calls[0].ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</text><text x="276" y="103" textAnchor="end">{new Date(calls[calls.length - 1].ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</text></>}{!calls.length && <text x="155" y="48" textAnchor="middle">No LLM calls recorded</text>}</svg><div className="usage-legend"><span><i />Input {input.toLocaleString()}</span><span><i />Output {output.toLocaleString()}</span></div><p className="section-note">Latest 36 LLM calls in loaded events</p></section>;
}

export function IncidentTrail({ events, onSelect }: { events: AgentEvent[]; onSelect: (id: string) => void }) {
  const security = events.filter(e => e.type === "breaker_stop" || e.type === "breaker_alert" || e.type === "approval_request" || (e.type === "firewall_verdict" && e.data.action !== "allow")).slice(0, 10).reverse();
  return <div className="incident-trail"><div className="trail-heading"><Icon name="activity" size={16} /><span>Incident trail</span><small>Loaded events</small></div><div className="trail-events">{security.length ? security.map(e => <button key={e.id} onClick={() => onSelect(e.id)} title={`Inspect ${e.type} · ${e.agent}`}><span className={`trail-mark ${e.type === "breaker_stop" || e.data.action === "block" ? "danger" : ""}`} /><span>{e.type === "firewall_verdict" ? e.data.action : e.type.replace("_", " ")}</span><time>{new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</time></button>) : <span className="trail-empty">No security interventions in loaded events</span>}</div></div>;
}
