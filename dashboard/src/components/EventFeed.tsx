import type { ReactNode } from "react";
import type { AgentEvent } from "../types";

const KIND_STYLE: Record<string, string> = {
  session_start: "ev-session",
  session_end: "ev-session",
  prompt_before: "ev-dim",
  prompt_after: "ev-dim",
  firewall_verdict: "ev-fw",
  tool_call: "ev-tool",
  llm_call: "ev-llm",
  state_change: "ev-state",
  graph_event: "ev-graph",
  error: "ev-error",
  breaker_alert: "ev-alert",
  breaker_stop: "ev-stop",
  approval_request: "ev-approval",
  approval_decision: "ev-approval",
};

function verdictClass(action?: string) {
  if (action === "block") return "v-block";
  if (action === "sanitize") return "v-sanitize";
  if (action === "approve") return "v-approve";
  return "v-allow";
}

function line(e: AgentEvent): { badge: string; body: ReactNode; cls: string } {
  const d = e.data || {};
  const base = { badge: e.type, body: "", cls: KIND_STYLE[e.type] || "" };
  switch (e.type) {
    case "session_start":
      return { ...base, body: `${e.agent} · ${d.model || "?"} started${d.cwd ? ` @ ${d.cwd}` : ""}` };
    case "prompt_before":
      return { ...base, body: `${(d.content || "").slice(0, 90) || d.preview || d.chars + " chars"}` };
    case "firewall_verdict":
      return {
        badge: `${e.type}:${d.action}`,
        cls: `ev-fw ${verdictClass(d.action)}`,
        body: `score ${d.risk_score} — ${d.reason}${
          (d.violations || []).length ? ` [${(d.violations || []).map((v: any) => v.rule).slice(0, 3).join(", ")}]` : ""
        }`,
      };
    case "llm_call":
      return {
        ...base,
        body: `${d.model || "?"} ▸ ${d.input_tokens ?? 0}↓ ${d.output_tokens ?? 0}↑ ${
          d.cost_usd != null ? `$${Number(d.cost_usd).toFixed(4)}` : ""
        }${d.latency_ms ? ` ${d.latency_ms}ms` : ""}${d.iteration ? ` iter ${d.iteration}` : ""}`,
      };
    case "tool_call":
      return {
        ...base,
        body: `${d.name} ${d.status}${d.duration_ms ? ` · ${d.duration_ms}ms` : ""}${
          d.args_preview ? ` — ${String(d.args_preview).slice(0, 60)}` : ""
        }`,
      };
    case "state_change":
      return { ...base, body: `${d.previous_state || "∅"} → ${d.state}` };
    case "graph_event":
      return { ...base, body: `${d.node} ${d.phase}${d.transition_to ? ` → ${d.transition_to}` : ""}` };
    case "error":
      return { ...base, body: `${d.kind || "error"}: ${String(d.message).slice(0, 120)}` };
    case "breaker_alert":
      return { ...base, body: `${d.metric} @ ${Math.round(Number(d.value))} / ${d.limit} — ${d.message || ""}` };
    case "breaker_stop":
      return {
        ...base,
        body: `${d.metric} ${d.value}/${d.limit} · ${d.enforcement} → ${d.result}`,
      };
    case "approval_request":
      return { ...base, body: `${d.metric || d.reason} — ${d.reason || ""}` };
    case "approval_decision":
      return { ...base, body: `${d.status} by ${d.by}` };
    case "session_end":
      return { ...base, body: `${e.agent} session ended` };
    default:
      return { ...base, body: JSON.stringify(d).slice(0, 100) };
  }
}

export default function EventFeed({ events, connected, sessionFilter }: {
  events: AgentEvent[]; connected: boolean; sessionFilter: string | null;
}) {
  const filtered = sessionFilter
    ? events.filter(e => e.session_id === sessionFilter)
    : events;
  return (
    <div className="feed">
      <div className="feed-head">
        <span>live event stream</span>
        <span className={`ws-dot ${connected ? "on" : "off"}`}>{connected ? "connected" : "reconnecting…"}</span>
      </div>
      <div className="feed-rows">
        {filtered.length === 0 && <div className="empty">waiting for events… run an agent adapter or POST /v1/events</div>}
        {filtered.map(e => {
          const { badge, body, cls } = line(e);
          return (
            <div key={e.id} className={`row ${cls}`}>
              <span className="ts">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
              <span className="agent">{e.agent}</span>
              <span className="badge">{badge}</span>
              <span className="body">{body}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
