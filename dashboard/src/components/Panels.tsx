import { useEffect, useState, useMemo } from "react";
import { api } from "../api";
import type { ApprovalRow, BreakerSnapshot, SessionRow } from "../types";

/** Trailing path fragments — enough to tell projects apart in the sidebar. */
function shortCwd(p: string): string {
  const parts = p.replace(/\/+$/, "").split("/").filter(Boolean);
  return parts.slice(-2).join("/");
}

export function Sessions({
  sessions,
  selected,
  onSelect,
}: {
  sessions: SessionRow[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">SESSIONS</span>
        <span className="panel-badge">{sessions.length} ACTIVE</span>
      </div>
      <div className="session-rows">
        <div
          className={`srow srow-all ${!selected ? "sel" : ""}`}
          onClick={() => onSelect(null)}
        >
          <div className="srow-header">
            <span className="srow-dot" />
            <span className="sid">ALL AGENTS</span>
            <span className="tag-all">GLOBAL STREAM</span>
          </div>
          <div className="srow-meta text-muted">Aggregated stream across all runtime sessions</div>
        </div>

        {sessions.map(s => {
          const isSelected = selected === s.session_id;
          const isEnded = Boolean(s.end_ts);
          return (
            <div
              key={s.session_id}
              className={`srow ${isSelected ? "sel" : ""} ${isEnded ? "ended" : ""}`}
              onClick={() => onSelect(s.session_id)}
            >
              <div className="srow-header">
                <span className={`session-indicator ${isEnded ? "indicator-off" : "indicator-on"}`} />
                <span className="sid" title={s.session_id}>
                  {s.session_id.length > 14 ? `${s.session_id.slice(0, 14)}…` : s.session_id}
                </span>
                <span className="tag dev-tag">{s.agent}</span>
              </div>

              {s.cwd && (
                <div className="srow-path" title={s.cwd}>
                  <span className="path-icon">~</span>/{shortCwd(s.cwd)}
                </div>
              )}

              <div className="srow-stats">
                <span className="dev-stat-pill">
                  <span className="stat-label">TOK</span> {s.tokens.toLocaleString()}
                </span>
                <span className="dev-stat-pill">
                  <span className="stat-label">COST</span> ${s.cost_usd.toFixed(4)}
                </span>
                {s.iteration > 0 && (
                  <span className="dev-stat-pill">
                    <span className="stat-label">ITR</span> {s.iteration}
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {sessions.length === 0 && (
          <div className="empty dev-empty">
            <span className="empty-icon">⌨</span>
            <span>No agent sessions active</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function Breaker({
  snaps,
  onReset,
}: {
  snaps: BreakerSnapshot[];
  onReset: (id: string) => void;
}) {
  const active = snaps.filter(s => s.status !== "healthy");

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">CIRCUIT BREAKER</span>
        {active.length > 0 ? (
          <span className="panel-badge alert">{active.length} ALERT</span>
        ) : (
          <span className="panel-badge ok">NOMINAL</span>
        )}
      </div>

      {active.length === 0 ? (
        <div className="circuit-healthy-card">
          <div className="healthy-indicator">
            <span className="healthy-dot" />
            <span className="healthy-text">ALL CIRCUITS NOMINAL</span>
          </div>
          <div className="healthy-subtext">No token, cost, or loop limits tripped.</div>
        </div>
      ) : (
        <div className="breaker-list">
          {active.map(s => {
            const iterLimit = s.limits.max_iterations ?? null;
            const tokenLimit = s.limits.max_tokens ?? null;
            const costLimit = s.limits.max_cost_usd ?? null;
            const totalTokens = s.usage.input_tokens + s.usage.output_tokens;

            const iterPct = iterLimit ? Math.min(100, Math.round((s.usage.iterations / iterLimit) * 100)) : 0;
            const tokenPct = tokenLimit ? Math.min(100, Math.round((totalTokens / tokenLimit) * 100)) : 0;
            const costPct = costLimit ? Math.min(100, Math.round((s.usage.cost_usd / costLimit) * 100)) : 0;

            return (
              <div key={s.session_id} className={`brow brow-dev ${s.status}`}>
                <div className="brow-header">
                  <div className="brow-id-group">
                    <span className="sid">{s.session_id.slice(0, 10)}…</span>
                    <span className="tag dev-tag">{s.agent}</span>
                  </div>
                  <span className={`status-badge-dev ${s.status}`}>
                    {s.status.toUpperCase()}
                  </span>
                </div>

                {/* Meter Bars */}
                <div className="brow-meters">
                  <div className="meter-row">
                    <div className="meter-label">
                      <span>Iterations</span>
                      <span className="meter-val">{s.usage.iterations} / {iterLimit ?? "∞"}</span>
                    </div>
                    {iterLimit && (
                      <div className="meter-track">
                        <div
                          className={`meter-bar ${iterPct > 90 ? "bar-red" : iterPct > 70 ? "bar-amber" : "bar-green"}`}
                          style={{ width: `${iterPct}%` }}
                        />
                      </div>
                    )}
                  </div>

                  <div className="meter-row">
                    <div className="meter-label">
                      <span>Tokens</span>
                      <span className="meter-val">{totalTokens.toLocaleString()} / {tokenLimit ? tokenLimit.toLocaleString() : "∞"}</span>
                    </div>
                    {tokenLimit && (
                      <div className="meter-track">
                        <div
                          className={`meter-bar ${tokenPct > 90 ? "bar-red" : tokenPct > 70 ? "bar-amber" : "bar-green"}`}
                          style={{ width: `${tokenPct}%` }}
                        />
                      </div>
                    )}
                  </div>

                  <div className="meter-row">
                    <div className="meter-label">
                      <span>Cost</span>
                      <span className="meter-val">${s.usage.cost_usd.toFixed(3)} / {costLimit ? `$${costLimit}` : "∞"}</span>
                    </div>
                    {costLimit && (
                      <div className="meter-track">
                        <div
                          className={`meter-bar ${costPct > 90 ? "bar-red" : costPct > 70 ? "bar-amber" : "bar-green"}`}
                          style={{ width: `${costPct}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>

                {s.status === "breached" && (
                  <div className="brow-actions">
                    <button
                      type="button"
                      className="dev-btn reset-btn"
                      onClick={() => onReset(s.session_id)}
                    >
                      ↺ RESET BREAKER
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Approvals({
  rows,
  onResolve,
}: {
  rows: ApprovalRow[];
  onResolve: (id: string, approved: boolean) => void;
}) {
  return (
    <div className="panel panel-approvals">
      <div className="panel-head">
        <span className="panel-title">APPROVAL GATEWAY</span>
        {rows.length > 0 ? (
          <span className="panel-badge alert-red">{rows.length} PENDING</span>
        ) : (
          <span className="panel-badge">0 REQ</span>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="empty dev-empty">
          <span className="empty-icon">✓</span>
          <span>No security approvals pending</span>
        </div>
      ) : (
        <div className="approval-list">
          {rows.map(a => (
            <div key={a.id} className="arow arow-dev">
              <div className="arow-top">
                <span className="approval-alert-tag">ACTION REQUIRED</span>
                <span className="tag dev-tag">{a.agent}</span>
              </div>
              <div className="arow-session text-muted">
                Session: <span className="text-white">{a.session_id.slice(0, 12)}…</span>
              </div>
              <div className="arow-reason">
                {a.reason}
              </div>
              {a.metric && a.limit && (
                <div className="arow-metric-pill">
                  {a.metric}: {a.value} &gt; limit {a.limit}
                </div>
              )}
              <div className="abtns abtns-dev">
                <button
                  type="button"
                  className="dev-btn btn-approve"
                  onClick={() => onResolve(a.id, true)}
                >
                  ✓ APPROVE
                </button>
                <button
                  type="button"
                  className="dev-btn btn-deny"
                  onClick={() => onResolve(a.id, false)}
                >
                  ✕ DENY
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TokenChart({ events }: { events: any[] }) {
  const calls = useMemo(() => {
    return events
      .filter(e => e.type === "llm_call")
      .slice(0, 36)
      .reverse() as { ts: number; data: any }[];
  }, [events]);

  const max = useMemo(() => {
    return Math.max(1, ...calls.map(c => (c.data?.input_tokens || 0) + (c.data?.output_tokens || 0)));
  }, [calls]);

  const summary = useMemo(() => {
    let inTok = 0;
    let outTok = 0;
    calls.forEach(c => {
      inTok += c.data?.input_tokens || 0;
      outTok += c.data?.output_tokens || 0;
    });
    return { inTok, outTok, total: inTok + outTok };
  }, [calls]);

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">TOKEN FLOW</span>
        <span className="panel-badge">{calls.length} CALLS</span>
      </div>

      <div className="token-legend">
        <span className="legend-item">
          <span className="legend-color in-color" /> Prompt
        </span>
        <span className="legend-item">
          <span className="legend-color out-color" /> Completion
        </span>
      </div>

      {calls.length === 0 ? (
        <div className="empty dev-empty">
          <span className="empty-icon">📊</span>
          <span>No LLM call telemetry recorded</span>
        </div>
      ) : (
        <>
          <div className="chart chart-dev">
            {calls.map((c, i) => {
              const inT = c.data?.input_tokens || 0;
              const outT = c.data?.output_tokens || 0;
              const inPct = (inT / max) * 100;
              const outPct = (outT / max) * 100;
              const cost = c.data?.cost_usd ? `$${Number(c.data.cost_usd).toFixed(4)}` : "";
              return (
                <div
                  key={i}
                  className="bar bar-dev"
                  title={`${c.data?.model || "model"} | in: ${inT.toLocaleString()} / out: ${outT.toLocaleString()} ${cost}`}
                >
                  <div className="bar-track">
                    <span className="bar-out" style={{ height: `${outPct}%` }} />
                    <span className="bar-in" style={{ height: `${inPct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>

          <div className="chart-telemetry-summary">
            <div className="tele-item">
              <span className="tele-label">PROMPT</span>
              <span className="tele-val text-cyan">{summary.inTok.toLocaleString()}</span>
            </div>
            <div className="tele-item">
              <span className="tele-label">COMPL</span>
              <span className="tele-val text-violet">{summary.outTok.toLocaleString()}</span>
            </div>
            <div className="tele-item">
              <span className="tele-label">TOTAL</span>
              <span className="tele-val text-white">{summary.total.toLocaleString()}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function FirewallDigest({ events }: { events: any[] }) {
  const verdicts = useMemo(() => {
    return events.filter(e => e.type === "firewall_verdict").slice(0, 150);
  }, [events]);

  const count = useMemo(() => {
    const c = { allow: 0, sanitize: 0, block: 0, approve: 0 } as Record<string, number>;
    verdicts.forEach(v => {
      c[v.data?.action] = (c[v.data?.action] || 0) + 1;
    });
    return c;
  }, [verdicts]);

  const total = verdicts.length || 1;

  const ranked = useMemo(() => {
    const top = {} as Record<string, number>;
    verdicts.forEach(v =>
      (v.data?.violations || []).forEach((x: any) => {
        top[x.rule] = (top[x.rule] || 0) + 1;
      })
    );
    return Object.entries(top)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [verdicts]);

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">FIREWALL TELEMETRY</span>
        <span className="panel-badge">{verdicts.length} VERDICTS</span>
      </div>

      {/* Distribution Spectrum Bar */}
      <div className="fw-distribution-track">
        <div
          className="fw-bar-seg v-allow-bg"
          style={{ width: `${(count.allow / total) * 100}%` }}
          title={`Allow: ${count.allow}`}
        />
        <div
          className="fw-bar-seg v-sanitize-bg"
          style={{ width: `${(count.sanitize / total) * 100}%` }}
          title={`Sanitize: ${count.sanitize}`}
        />
        <div
          className="fw-bar-seg v-approve-bg"
          style={{ width: `${(count.approve / total) * 100}%` }}
          title={`Approve: ${count.approve}`}
        />
        <div
          className="fw-bar-seg v-block-bg"
          style={{ width: `${(count.block / total) * 100}%` }}
          title={`Block: ${count.block}`}
        />
      </div>

      {/* Counter Grid */}
      <div className="fw-counts-grid">
        <div className="fw-count-cell v-allow-cell">
          <span className="fw-count-label">ALLOW</span>
          <span className="fw-count-val">{count.allow}</span>
        </div>
        <div className="fw-count-cell v-sanitize-cell">
          <span className="fw-count-label">SANITIZE</span>
          <span className="fw-count-val">{count.sanitize}</span>
        </div>
        <div className="fw-count-cell v-approve-cell">
          <span className="fw-count-label">APPROVE</span>
          <span className="fw-count-val">{count.approve}</span>
        </div>
        <div className="fw-count-cell v-block-cell">
          <span className="fw-count-label">BLOCK</span>
          <span className="fw-count-val">{count.block}</span>
        </div>
      </div>

      {ranked.length > 0 && (
        <div className="fw-rules-section">
          <div className="fw-rules-title">TOP TRIGGERED RULES</div>
          <div className="fw-rules">
            {ranked.map(([rule, n]) => (
              <div key={rule} className="fwrule">
                <span className="rule-badge">{rule}</span>
                <span className="rule-count">×{n}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function ModeSwitch() {
  const [observing, setObserving] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.health().then(h => setObserving(h.observe_mode)).catch(() => setObserving(null));
    const t = setInterval(() => {
      api.health().then(h => setObserving(h.observe_mode)).catch(() => {});
    }, 10000);
    return () => clearInterval(t);
  }, []);

  const flip = () => {
    if (loading) return;
    setLoading(true);
    const next = !observing ? "observe" : "enforce";
    api.setMode(next as any)
      .then(r => setObserving(r.mode === "observe"))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  return (
    <button
      type="button"
      className={`mode-toggle-btn ${observing ? "is-observe" : "is-enforce"}`}
      onClick={flip}
      disabled={loading}
      title={observing ? "Switch to Enforce mode" : "Switch to Observe mode"}
    >
      <span className={`mode-led ${observing ? "led-amber" : "led-cyan"}`} />
      <span className="mode-text">
        {observing === null
          ? "CONNECTING…"
          : observing
          ? "OBSERVE MODE"
          : "ENFORCE MODE"}
      </span>
      <span className="mode-action-hint">
        {observing ? "FLIP" : "FLIP"}
      </span>
    </button>
  );
}
