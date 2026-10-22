import { useEffect, useState } from "react";
import { api } from "../api";
import type { ApprovalRow, BreakerSnapshot, SessionRow } from "../types";

/** Trailing path fragments — enough to tell projects apart in the sidebar. */
function shortCwd(p: string): string {
  const parts = p.replace(/\/+$/, "").split("/").filter(Boolean);
  return parts.slice(-2).join("/");
}

export function Sessions({ sessions, selected, onSelect }: {
  sessions: SessionRow[]; selected: string | null; onSelect: (id: string | null) => void;
}) {
  return (
    <div className="panel">
      <div className="panel-head">sessions</div>
      <div className="session-rows">
        <div className={`srow ${!selected ? "sel" : ""}`} onMouseDown={() => onSelect(null)}>
          <span>all agents</span><span className="muted">combined</span>
        </div>
        {sessions.map(s => (
          <div key={s.session_id} className={`srow ${selected === s.session_id ? "sel" : ""}`}
               onMouseDown={() => onSelect(s.session_id)}>
            <span className="sid">{s.session_id}</span>
            <span className="tag">{s.agent}</span>
            {s.cwd ? <span className="cwd" title={s.cwd}>{shortCwd(s.cwd)}</span> : null}
            <span className="nums">{s.tokens.toLocaleString()} tok · ${s.cost_usd.toFixed(4)}</span>
          </div>
        ))}
        {sessions.length === 0 && <div className="empty">no sessions yet</div>}
      </div>
    </div>
  );
}

export function Breaker({ snaps, onReset }: { snaps: BreakerSnapshot[]; onReset: (id: string) => void }) {
  const active = snaps.filter(s => s.status !== "healthy");
  return (
    <div className="panel">
      <div className="panel-head">circuit breaker</div>
      {active.length === 0 && <div className="empty">all sessions healthy</div>}
      {active.map(s => (
        <div key={s.session_id} className={`brow ${s.status}`}>
          <div>
            <span className="sid">{s.session_id}</span>
            <span className="tag">{s.agent}</span>
            <span className={`status ${s.status}`}>{s.status}</span>
          </div>
          <div className="metrics">
            <span>iter {s.usage.iterations}/{s.limits.max_iterations ?? "∞"}</span>
            <span>tok {s.usage.input_tokens + s.usage.output_tokens}/{s.limits.max_tokens ?? "∞"}</span>
            <span>${s.usage.cost_usd.toFixed(3)}/{s.limits.max_cost_usd ?? "∞"}</span>
            {s.status === "breached" && (
              <button className="mini" onMouseDown={() => onReset(s.session_id)}>reset</button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Approvals({ rows, onResolve }: {
  rows: ApprovalRow[]; onResolve: (id: string, approved: boolean) => void;
}) {
  return (
    <div className="panel">
      <div className="panel-head">pending approvals</div>
      {rows.length === 0 && <div className="empty">no approvals pending</div>}
      {rows.map(a => (
        <div key={a.id} className="arow">
          <div className="ameta">
            <span className="sid">{a.session_id}</span>
            <span className="tag">{a.agent}</span>
            <span className="muted">{a.reason}</span>
          </div>
          <div className="abtns">
            <button className="ok" onMouseDown={() => onResolve(a.id, true)}>approve</button>
            <button className="no" onMouseDown={() => onResolve(a.id, false)}>deny</button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function TokenChart({ events }: { events: any[] }) {
  const calls = events
    .filter(e => e.type === "llm_call")
    .slice(0, 40).reverse() as { ts: number; data: any }[];
  const max = Math.max(1, ...calls.map(c => (c.data?.input_tokens || 0) + (c.data?.output_tokens || 0)));
  return (
    <div className="panel">
      <div className="panel-head">token flow (last {calls.length} model calls)</div>
      {calls.length === 0 && <div className="empty">no model calls yet</div>}
      <div className="chart">
        {calls.map((c, i) => (
          <div key={i} className="bar" title={`in ${c.data?.input_tokens || 0} / out ${c.data?.output_tokens || 0}`}>
            <span className="in" style={{ height: `${((c.data?.input_tokens || 0) / max) * 100}%` }} />
            <span className="out" style={{ height: `${((c.data?.output_tokens || 0) / max) * 100}%` }} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function FirewallDigest({ events }: { events: any[] }) {
  const verdicts = events.filter(e => e.type === "firewall_verdict").slice(0, 100);
  const count = { allow: 0, sanitize: 0, block: 0, approve: 0 } as Record<string, number>;
  verdicts.forEach(v => { count[v.data?.action] = (count[v.data?.action] || 0) + 1; });
  const top = {} as Record<string, number>;
  verdicts.forEach(v => (v.data?.violations || []).forEach((x: any) => {
    top[x.rule] = (top[x.rule] || 0) + 1;
  }));
  const ranked = Object.entries(top).sort((a, b) => b[1] - a[1]).slice(0, 6);
  return (
    <div className="panel">
      <div className="panel-head">firewall digest</div>
      <div className="fw-counts">
        <span className="v-allow">allow {count.allow || 0}</span>
        <span className="v-sanitize">sanitize {count.sanitize || 0}</span>
        <span className="v-approve">approve {count.approve || 0}</span>
        <span className="v-block">block {count.block || 0}</span>
      </div>
      {ranked.length > 0 && (
        <div className="fw-rules">
          {ranked.map(([rule, n]) => (
            <div key={rule} className="fwrule"><span className="badge">{rule}</span><span>×{n}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ModeSwitch() {
  const [observing, setObserving] = useState<boolean | null>(null);
  useEffect(() => {
    api.health().then(h => setObserving(h.observe_mode)).catch(() => setObserving(null));
    const t = setInterval(() => api.health().then(h => {
      setObserving(h.observe_mode);
    }).catch(() => {}), 10000);
    return () => clearInterval(t);
  }, []);
  const flip = () => {
    const next = !observing ? "observe" : "enforce";
    api.setMode(next as any).then(r => setObserving(r.mode === "observe")).catch(() => {});
  };
  return (
    <button className={`mini mode ${observing ? "warn" : ""}`} onMouseDown={flip}>
      {observing === null ? "…" : observing ? "observe mode (click to enforce)" : "enforce mode (click to observe)"}
    </button>
  );
}
