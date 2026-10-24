import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { AgentEvent, SessionRow } from "../types";
import { formatUsageCost, summarizeUsage, usageCalls, type UsageBin, type UsageGroup } from "../usage";
import Icon from "./Icon";

const MAX_CALLS = 10000;
type Period = "hour" | "day" | "history";
interface UsageSnapshot { events: AgentEvent[]; from: number; to: number; capped: boolean }

function compact(n: number) {
  return n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(1)}m` : n >= 1000 ? `${+(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

function UsageChart({ bins, cost = false, loading, unavailable }: { bins: UsageBin[]; cost?: boolean; loading: boolean; unavailable: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const resize = () => setWidth(Math.max(240, node.getBoundingClientRect().width));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const height = 210, right = 10, top = 16, bottom = 34;
  const max = Math.max(0, ...bins.map(bin => cost ? bin.costMicros / 1_000_000 : bin.input + bin.output));
  const magnitude = 10 ** Math.floor(Math.log10(max || 1));
  const ceiling = max ? Math.ceil((max * 1.08) / magnitude) * magnitude : cost ? 0.01 : 10;
  const left = cost ? ceiling < .0001 ? 90 : 66 : 48;
  const chartWidth = Math.max(1, width - left - right), chartHeight = height - top - bottom;
  const step = chartWidth / Math.max(1, bins.length);
  const selected = active === null ? null : bins[active];
  const tick = (value: number) => cost ? `$${value.toFixed(ceiling < .0001 ? 6 : ceiling < .01 ? 4 : ceiling < 1 ? 3 : 2)}` : compact(value);
  const span = bins.length ? bins[bins.length - 1].to - bins[0].from : 0;
  const time = (ts: number) => new Date(ts * 1000).toLocaleString([], { ...(span > 86400 ? { month: "short", day: "numeric" } as const : {}), hour: "2-digit", minute: "2-digit", hour12: false });
  const axisTime = (ts: number) => span > 86400 ? new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric", ...(span > 366 * 86400 ? { year: "2-digit" } as const : {}) }) : time(ts);
  return <div className="usage-plot" ref={ref}>
    <svg viewBox={`0 0 ${width} ${height}`} style={{ height }} role="img" aria-label={cost ? "Recorded USD cost per time interval; unpriced calls are not treated as free." : "Input and output tokens per time interval."}>
      {[0, .5, 1].map(ratio => <g key={ratio}><line x1={left} x2={width - right} y1={top + chartHeight * (1 - ratio)} y2={top + chartHeight * (1 - ratio)} className="usage-gridline" /><text x={left - 10} y={top + chartHeight * (1 - ratio) + 4} textAnchor="end">{tick(ceiling * ratio)}</text></g>)}
      {bins.map((bin, i) => {
        const x = left + i * step + 2, barWidth = Math.max(1, step - 4);
        const inputHeight = (cost ? bin.costMicros / 1_000_000 : bin.input) / ceiling * chartHeight;
        const outputHeight = cost ? 0 : bin.output / ceiling * chartHeight;
        const description = `${time(bin.from)}–${time(bin.to)}: ${cost ? `${formatUsageCost(bin.costMicros)} recorded; ${bin.pricedCalls}/${bin.calls} calls priced` : `${bin.input.toLocaleString()} input, ${bin.output.toLocaleString()} output tokens`}`;
        return <g key={bin.from} tabIndex={bin.calls ? 0 : undefined} aria-label={description} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(i)} onBlur={() => setActive(null)}>
          <title>{description}</title><rect x={x} y={top} width={barWidth} height={chartHeight} fill="transparent" />
          <rect x={x} y={top + chartHeight - inputHeight} width={barWidth} height={inputHeight} className="usage-input-mark" />
          {!cost && <rect x={x} y={top + chartHeight - inputHeight - outputHeight} width={barWidth} height={outputHeight} className="usage-output-mark" />}
          {cost && bin.calls > bin.pricedCalls && <path d={`M${x} ${top + chartHeight - 5}h${barWidth}`} className="usage-unpriced-mark" />}
        </g>;
      })}
      {bins.length > 0 && [0, 1, 2, 3, 4].map(i => {
        const ts = bins[0].from + (bins[bins.length - 1].to - bins[0].from) * i / 4;
        return <text key={i} x={left + chartWidth * i / 4} y={height - 9} textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}>{axisTime(ts)}</text>;
      })}
      {loading && <text x={left + chartWidth / 2} y={top + chartHeight / 2} textAnchor="middle">Loading telemetry…</text>}
      {!loading && bins.every(b => !b.calls) && <text x={left + chartWidth / 2} y={top + chartHeight / 2} textAnchor="middle">{unavailable ? "Usage unavailable" : "No LLM calls in this range"}</text>}
    </svg>
    <div className="usage-plot-readout" aria-live="polite">{selected ? `${time(selected.from)}–${time(selected.to)} · ${cost ? `${formatUsageCost(selected.costMicros)} recorded · ${selected.calls - selected.pricedCalls} unpriced calls` : `${selected.input.toLocaleString()} input / ${selected.output.toLocaleString()} output tokens`}` : cost ? "Hover or focus a bar for recorded cost and coverage." : "Hover or focus a bar to inspect token flow."}</div>
  </div>;
}

function Breakdown({ title, groups, sessions, kind, loading, unavailable, onSelect }: {
  title: string; groups: UsageGroup[]; sessions: SessionRow[]; kind: "model" | "session"; loading: boolean; unavailable: boolean; onSelect?: (id: string) => void;
}) {
  return <section className="usage-breakdown">
    <div className="section-heading"><h2>{title}</h2><span className="meta">{groups.length} {kind === "model" ? "models" : "sessions"}</span></div>
    <div className="usage-table-wrap"><table className="usage-table">
      <thead><tr><th>{kind === "model" ? "Model" : "Session / project"}</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Recorded USD</th></tr></thead>
      <tbody>{groups.map(group => {
        const session = sessions.find(s => s.session_id === group.id);
        const name = session?.cwd?.split("/").filter(Boolean).pop() || group.id;
        return <tr key={group.id}><td>{kind === "session" ? <button onClick={() => onSelect?.(group.id)} title={group.id}>{name}<Icon name="arrow" size={12} /></button> : <span title={group.id}>{group.id}</span>}<small>{kind === "session" ? `${group.agent} · ${group.id}` : `${group.input.toLocaleString()} input · ${group.output.toLocaleString()} output`}</small></td><td className="num">{group.calls.toLocaleString()}</td><td className="num">{(group.input + group.output).toLocaleString()}</td><td className="num">{group.pricedCalls ? formatUsageCost(group.costMicros) : "—"}{group.pricedCalls < group.calls && <small>{group.calls - group.pricedCalls} unpriced</small>}</td></tr>;
      })}</tbody>
    </table></div>
    {!groups.length && <div className="usage-empty-row">{loading ? "Loading breakdown…" : unavailable ? "Usage telemetry is unavailable." : "No LLM calls match this range and scope."}</div>}
  </section>;
}

export default function UsageWorkspace({ sessionId, sessions, onSelectSession }: {
  sessionId: string | null; sessions: SessionRow[]; onSelectSession: (id: string | null) => void;
}) {
  const [period, setPeriod] = useState<Period>("hour");
  const [model, setModel] = useState("all");
  const [snapshot, setSnapshot] = useState<UsageSnapshot | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++sequence.current;
    const to = Date.now() / 1000;
    const since = period === "history" ? undefined : to - (period === "hour" ? 3600 : 86400);
    setBusy(true);
    try {
      const response = await api.events({ type: "llm_call", session_id: sessionId ?? undefined, since, limit: MAX_CALLS, order: "desc" });
      if (request !== sequence.current) return;
      const events = response.events as AgentEvent[];
      const from = since ?? Math.min(to - 60, ...events.filter(e => Number.isFinite(e.ts)).map(e => e.ts));
      setSnapshot({ events, from, to, capped: events.length >= MAX_CALLS });
      setUpdated(new Date()); setError("");
    } catch {
      if (request === sequence.current) setError("Couldn't update usage telemetry. Any previous results remain in view.");
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  }, [period, sessionId]);

  useEffect(() => {
    setSnapshot(null); setUpdated(null); setError(""); setModel("all");
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => { sequence.current++; clearInterval(timer); };
  }, [refresh]);
  const calls = useMemo(() => snapshot ? usageCalls(snapshot.events, snapshot.from, snapshot.to) : [], [snapshot]);
  const models = [...new Set(calls.map(call => call.model))].sort();
  const filtered = model === "all" ? calls : calls.filter(call => call.model === model);
  const end = snapshot?.to ?? Date.now() / 1000;
  const start = snapshot?.from ?? end - (period === "hour" ? 3600 : 86400);
  const { total, bins, models: modelGroups, sessions: sessionGroups } = summarizeUsage(filtered, start, end, period === "hour" ? 12 : 24);
  const ready = snapshot !== null;
  const missingCost = total.calls - total.pricedCalls;
  return <div className="usage-workspace">
    <div className="usage-toolbar">
      <div className="usage-filters"><label>Period<select value={period} onChange={e => setPeriod(e.target.value as Period)}><option value="hour">Last hour</option><option value="day">Last 24 hours</option><option value="history">Available history</option></select></label>
        <label>Session<select value={sessionId ?? "all"} onChange={e => onSelectSession(e.target.value === "all" ? null : e.target.value)}><option value="all">All sessions</option>{sessionId && !sessions.some(s => s.session_id === sessionId) && <option value={sessionId}>{sessionId}</option>}{sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.cwd?.split("/").filter(Boolean).pop() || s.agent} · {s.session_id.slice(0, 12)}</option>)}</select></label>
        <label>Model<select value={model} onChange={e => setModel(e.target.value)}><option value="all">All models</option>{model !== "all" && !models.includes(model) && <option value={model}>{model} (no calls)</option>}{models.map(m => <option key={m}>{m}</option>)}</select></label></div>
      <div className="usage-freshness"><span>{busy ? "Refreshing…" : updated ? `Updated ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}` : "Awaiting telemetry"}</span><button className="icon-button" aria-label="Refresh usage" disabled={busy} onClick={() => void refresh()}><Icon name="refresh" size={15} /></button></div>
    </div>
    {error && <div className="inline-error" role="status">{error}<button onClick={() => void refresh()}>Retry</button></div>}
    {snapshot?.capped && <div className="usage-notice">Showing the newest {MAX_CALLS.toLocaleString()} LLM calls in this range. Totals and charts cover these loaded calls; choose a shorter period for a complete view.</div>}
    <section className="usage-summary" aria-label="Token and cost totals">
      <div><span>Total tokens</span><strong>{ready ? (total.input + total.output).toLocaleString() : "—"}</strong><small>{ready ? `${total.calls.toLocaleString()} LLM ${total.calls === 1 ? "call" : "calls"}` : "Awaiting telemetry"}</small></div>
      <div><span>Input tokens</span><strong>{ready ? total.input.toLocaleString() : "—"}</strong><small>{ready ? `${total.cacheRead.toLocaleString()} cache-read tokens reported` : "Awaiting telemetry"}</small></div>
      <div><span>Output tokens</span><strong>{ready ? total.output.toLocaleString() : "—"}</strong><small>{ready ? `${total.cacheWrite.toLocaleString()} cache-write tokens reported` : "Awaiting telemetry"}</small></div>
      <div><span>Recorded cost <span className="usage-unit">USD</span></span><strong>{ready && (total.pricedCalls || !total.calls) ? formatUsageCost(total.costMicros) : "—"}</strong><small>{ready ? `${total.pricedCalls.toLocaleString()} of ${total.calls.toLocaleString()} calls priced` : "Awaiting telemetry"}</small></div>
    </section>
    <p className="usage-coverage">{ready ? `${missingCost ? `${missingCost.toLocaleString()} ${missingCost === 1 ? "call has" : "calls have"} no reported cost; ${missingCost === 1 ? "it is" : "they are"} not counted as free. ` : "Costs use reported telemetry; no model pricing is inferred. "}Token totals are input + output; cache counters are shown separately.` : "Charts and totals will appear when usage telemetry is available."}</p>
    <div className="usage-charts"><section className="usage-chart-panel"><div className="section-heading"><h2>Token flow</h2><div className="usage-chart-legend"><span><i className="input" />Input</span><span><i className="output" />Output</span></div></div><UsageChart bins={ready ? bins : []} loading={!ready && busy} unavailable={!ready && !busy} /><p className="section-note">Tokens per interval · {new Date(start * 1000).toLocaleDateString()} to {new Date(end * 1000).toLocaleDateString()}</p></section>
      <section className="usage-chart-panel"><div className="section-heading"><h2>Recorded cost over time</h2><span className="meta">USD per interval</span></div><UsageChart bins={ready ? bins : []} cost loading={!ready && busy} unavailable={!ready && !busy} /><p className="section-note">{missingCost ? "An amber baseline mark identifies an interval with unpriced calls." : "Zero recorded cost remains zero; missing prices remain unpriced."}</p></section></div>
    <div className="usage-breakdowns"><Breakdown title="By model" groups={modelGroups} sessions={sessions} kind="model" loading={!ready && busy} unavailable={!ready && !busy} /><Breakdown title="By session" groups={sessionGroups} sessions={sessions} kind="session" loading={!ready && busy} unavailable={!ready && !busy} onSelect={onSelectSession} /></div>
  </div>;
}
