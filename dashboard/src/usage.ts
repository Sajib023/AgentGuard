import type { AgentEvent } from "./types";

export interface UsageCall {
  id: string;
  ts: number;
  sessionId: string;
  agent: string;
  model: string;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  costMicros: number | null;
}

export interface UsageTotals {
  calls: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  costMicros: number;
  pricedCalls: number;
}

export interface UsageBin extends UsageTotals { from: number; to: number }
export interface UsageGroup extends UsageTotals { id: string; agent?: string }

export const emptyTotals = (): UsageTotals => ({ calls: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, costMicros: 0, pricedCalls: 0 });

function numeric(value: unknown): number | null {
  if (value === null || value === undefined || (typeof value !== "number" && typeof value !== "string") || (typeof value === "string" && !value.trim())) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function usageCalls(events: AgentEvent[], from: number, to: number): UsageCall[] {
  const seen = new Set<string>();
  return events.filter(event => {
    if (event.type !== "llm_call" || !Number.isFinite(event.ts) || event.ts < from || event.ts > to || seen.has(event.id)) return false;
    seen.add(event.id);
    return true;
  }).map(event => {
    const d = event.data || {};
    const cost = numeric(d.cost_usd);
    return {
      id: event.id, ts: event.ts, sessionId: event.session_id, agent: event.agent,
      model: typeof d.model === "string" && d.model.trim() ? d.model : "Unreported model",
      input: Math.trunc(numeric(d.input_tokens) ?? 0), output: Math.trunc(numeric(d.output_tokens) ?? 0),
      cacheRead: Math.trunc(numeric(d.cache_read_tokens) ?? 0), cacheWrite: Math.trunc(numeric(d.cache_write_tokens) ?? 0),
      costMicros: cost === null ? null : Math.round(cost * 1_000_000),
    };
  }).sort((a, b) => a.ts - b.ts);
}

function add(total: UsageTotals, call: UsageCall) {
  total.calls++;
  total.input += call.input;
  total.output += call.output;
  total.cacheRead += call.cacheRead;
  total.cacheWrite += call.cacheWrite;
  if (call.costMicros !== null) { total.costMicros += call.costMicros; total.pricedCalls++; }
}

export function summarizeUsage(calls: UsageCall[], from: number, to: number, count = 24) {
  const total = emptyTotals();
  const interval = Math.max(1, to - from) / count;
  const bins: UsageBin[] = Array.from({ length: count }, (_, i) => ({ ...emptyTotals(), from: from + i * interval, to: from + (i + 1) * interval }));
  const models = new Map<string, UsageGroup>();
  const sessions = new Map<string, UsageGroup>();
  for (const call of calls) {
    add(total, call);
    add(bins[Math.max(0, Math.min(count - 1, Math.floor((call.ts - from) / interval)))], call);
    if (!models.has(call.model)) models.set(call.model, { ...emptyTotals(), id: call.model });
    if (!sessions.has(call.sessionId)) sessions.set(call.sessionId, { ...emptyTotals(), id: call.sessionId, agent: call.agent });
    add(models.get(call.model)!, call);
    add(sessions.get(call.sessionId)!, call);
  }
  const rank = (a: UsageGroup, b: UsageGroup) => b.costMicros - a.costMicros || b.input + b.output - a.input - a.output;
  return { total, bins, models: [...models.values()].sort(rank), sessions: [...sessions.values()].sort(rank) };
}

export function formatUsageCost(micros: number) {
  return `$${(micros / 1_000_000).toLocaleString("en-US", { minimumFractionDigits: 6, maximumFractionDigits: 6 })}`;
}
