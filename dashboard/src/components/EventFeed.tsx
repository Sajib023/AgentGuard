import { useState, useMemo, useEffect, useRef, type ReactNode } from "react";
import { api } from "../api";
import type { AgentEvent } from "../types";
import Icon from "./Icon";

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
      return {
        ...base,
        badge: "SESSION:START",
        body: (
          <span>
            <strong className="text-white">{e.agent}</strong> · {d.model || "default"} started
            {d.cwd && <span className="dev-path"> @ {d.cwd}</span>}
          </span>
        ),
      };
    case "prompt_before":
      return {
        ...base,
        badge: "PROMPT:IN",
        body: <span className="text-muted">{String(d.content || "").slice(0, 110) || d.preview || (d.chars != null ? `${d.chars} chars` : "Prompt content not recorded")}</span>,
      };
    case "prompt_after":
      return {
        ...base,
        badge: "PROMPT:OUT",
        body: <span className="text-muted">{String(d.content || "").slice(0, 110) || d.preview || (d.chars != null ? `${d.chars} chars` : "Response content not recorded")}</span>,
      };
    case "firewall_verdict":
      return {
        badge: `FW:${(d.action || "verdict").toUpperCase()}`,
        cls: `ev-fw ${verdictClass(d.action)}`,
        body: (
          <span>
            <span className="risk-pill">risk {d.risk_score}</span>
            <span className="fw-reason">{d.reason}</span>
            {(d.violations || []).length > 0 && (
              <span className="fw-tags">
                {(d.violations || []).slice(0, 3).map((v: any, idx: number) => (
                  <span key={idx} className="dev-rule-tag">{v.rule}</span>
                ))}
              </span>
            )}
          </span>
        ),
      };
    case "llm_call":
      return {
        ...base,
        badge: "LLM:CALL",
        body: (
          <span className="llm-details">
            <span className="dev-model">{d.model || "?"}</span>
            <span className="dev-metric">↓{d.input_tokens ?? 0}</span>
            <span className="dev-metric">↑{d.output_tokens ?? 0}</span>
            {d.cost_usd != null && (
              <span className="dev-cost">${Number(d.cost_usd).toFixed(4)}</span>
            )}
            {d.latency_ms && <span className="dev-latency">{d.latency_ms}ms</span>}
            {d.iteration != null && <span className="dev-iter">iter #{d.iteration}</span>}
          </span>
        ),
      };
    case "tool_call":
      return {
        ...base,
        badge: "TOOL:EXEC",
        body: (
          <span>
            <strong className="dev-tool-name">{d.name}</strong>
            <span className={`dev-status-pill status-${d.status}`}>{d.status}</span>
            {d.duration_ms && <span className="dev-latency">{d.duration_ms}ms</span>}
            {d.args_preview && (
              <code className="dev-inline-code">{String(d.args_preview).slice(0, 75)}</code>
            )}
          </span>
        ),
      };
    case "state_change":
      return {
        ...base,
        badge: "STATE",
        body: (
          <span>
            <span className="text-dim">{d.previous_state || "∅"}</span>
            <span className="dev-arrow"> → </span>
            <span className="text-cyan">{d.state}</span>
          </span>
        ),
      };
    case "graph_event":
      return {
        ...base,
        badge: "GRAPH",
        body: (
          <span>
            <strong>{d.node}</strong> [{d.phase}]
            {d.transition_to && <span className="dev-arrow"> → {d.transition_to}</span>}
          </span>
        ),
      };
    case "error":
      return {
        ...base,
        badge: "ERROR",
        body: (
          <span className="text-red">
            <strong>{d.kind || "ERR"}:</strong> {String(d.message).slice(0, 140)}
          </span>
        ),
      };
    case "breaker_alert":
      return {
        ...base,
        badge: "BREAKER:WARN",
        body: (
          <span className="text-amber">
            <strong>{d.metric}</strong> @ {Math.round(Number(d.value))} / {d.limit} — {d.message || "Threshold warning"}
          </span>
        ),
      };
    case "breaker_stop":
      return {
        ...base,
        badge: "BREAKER:STOP",
        body: (
          <span className="text-red">
            <strong>TRIPPED:</strong> {d.metric} {d.value}/{d.limit} · {d.enforcement} → {d.result}
          </span>
        ),
      };
    case "approval_request":
      return {
        ...base,
        badge: "APPROVAL:REQ",
        body: (
          <span className="text-amber">
            <strong>Action Required:</strong> {d.metric || d.reason} — {d.reason || ""}
          </span>
        ),
      };
    case "approval_decision":
      return {
        ...base,
        badge: "APPROVAL:DEC",
        body: (
          <span>
            Decision: <strong>{d.status}</strong> by <span className="text-dim">{d.by}</span>
          </span>
        ),
      };
    case "session_end":
      return {
        ...base,
        badge: "SESSION:END",
        body: <span className="text-dim">{e.agent} session terminated</span>,
      };
    default:
      return {
        ...base,
        badge: String(e.type).toUpperCase(),
        body: <span>{JSON.stringify(d).slice(0, 110)}</span>,
      };
  }
}

export default function EventFeed({
  events,
  connected,
  sessionFilter,
  onClear,
  focusedEvent,
  onFocusEvent,
}: {
  events: AgentEvent[];
  connected: boolean;
  sessionFilter: string | null;
  onClear?: () => void;
  focusedEvent?: string | null;
  onFocusEvent?: (id: string | null) => void;
}) {
  const [filterText, setFilterText] = useState("");
  const [activeCategory, setActiveCategory] = useState<"all" | "llm" | "tool" | "security" | "error">("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [frozenEvents, setFrozenEvents] = useState<AgentEvent[]>([]);
  const [actionError, setActionError] = useState("");
  const rowsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusedEvent) {
      setExpandedId(focusedEvent);
      setFilterText("");
      setActiveCategory("all");
      setIsPaused(false);
      requestAnimationFrame(() => document.getElementById(`event-${focusedEvent}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    } else setExpandedId(null);
  }, [focusedEvent]);

  useEffect(() => { setExpandedId(null); setIsPaused(false); setFrozenEvents([]); }, [sessionFilter]);

  const download = (format: "context-md" | "context-json" | "raw-json") => {
    setActionError("");
    void api.downloadSessionLog(sessionFilter, format).catch(() => setActionError("Export failed. Please try again."));
  };

  const handleTogglePause = () => {
    if (!isPaused) {
      setFrozenEvents(events);
      setIsPaused(true);
    } else {
      setIsPaused(false);
    }
  };

  const currentEvents = isPaused ? frozenEvents : events;

  const filtered = useMemo(() => {
    let list = sessionFilter
      ? currentEvents.filter(e => e.session_id === sessionFilter)
      : currentEvents;

    if (activeCategory !== "all") {
      list = list.filter(e => {
        if (activeCategory === "llm") {
          return e.type === "llm_call" || e.type === "prompt_before" || e.type === "prompt_after";
        }
        if (activeCategory === "tool") {
          return e.type === "tool_call";
        }
        if (activeCategory === "security") {
          return (
            e.type === "firewall_verdict" ||
            e.type === "breaker_alert" ||
            e.type === "breaker_stop" ||
            e.type === "approval_request" ||
            e.type === "approval_decision"
          );
        }
        if (activeCategory === "error") {
          return e.type === "error" || e.type === "breaker_stop";
        }
        return true;
      });
    }

    if (filterText.trim()) {
      const q = filterText.toLowerCase();
      list = list.filter(e => {
        const dObj = new Date(e.ts * 1000);
        const dStr = `${dObj.getFullYear()}-${String(dObj.getMonth() + 1).padStart(2, "0")}-${String(dObj.getDate()).padStart(2, "0")}`;
        return (
          e.agent.toLowerCase().includes(q) ||
          e.type.toLowerCase().includes(q) ||
          e.session_id.toLowerCase().includes(q) ||
          dStr.includes(q) ||
          JSON.stringify(e.data).toLowerCase().includes(q)
        );
      });
    }

    return [...list].sort((a, b) => b.ts - a.ts);
  }, [currentEvents, sessionFilter, activeCategory, filterText]);

  const toggleExpand = (id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
    if (expandedId === id) onFocusEvent?.(null);
  };

  const copyEventJson = (e: AgentEvent, ev: React.MouseEvent) => {
    ev.stopPropagation();
    navigator.clipboard.writeText(JSON.stringify(e, null, 2)).then(() => {
      setCopiedId(e.id);
      setTimeout(() => setCopiedId(null), 1800);
    }).catch(() => setActionError("Couldn't copy the payload. Please try again."));
  };

  return (
    <div className="feed" onKeyDown={e => { if (e.key === "Escape" && expandedId) { e.stopPropagation(); setExpandedId(null); onFocusEvent?.(null); } }}>
      {/* Stream Control Bar */}
      <div className="feed-head">
        <div className="feed-title-group">
          <h2 className="feed-title">Event stream</h2>
          <span className="feed-count-badge">{filtered.length} events</span>
          {sessionFilter && (
            <span className="feed-filter-tag" title={sessionFilter}>Session {sessionFilter.slice(0, 10)}</span>
          )}
        </div>

        <div className="feed-actions">
          <details className="export-menu" onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.open = false; e.stopPropagation(); } }}><summary className="dev-btn"><Icon name="download" size={14} />Export</summary><div onClick={e => { const details = e.currentTarget.closest("details"); if (details) details.open = false; }}><button onClick={() => download("context-md")}>Context Markdown</button><button onClick={() => download("context-json")}>Context JSON</button><button onClick={() => download("raw-json")}>Raw events JSON</button>{onClear && <button onClick={onClear} title="Clear the in-memory view; stored events are kept">Clear view</button>}</div></details>
          <button
            type="button"
            className={`dev-btn mini ${isPaused ? "active-pause" : ""}`}
            onClick={handleTogglePause}
            title={isPaused ? "Resume live auto-updating" : "Pause live auto-updating"}
          >
            <Icon name={isPaused ? "play" : "pause"} size={13} />{isPaused ? "Resume" : "Pause"}
          </button>
          <div className="ws-indicator-pill">
            <span className={`ws-dot ${connected ? "on" : "off"}`} />
            <span className="ws-text">{isPaused ? "Paused view" : connected ? "Live" : "Backfill"}</span>
          </div>
        </div>
      </div>

      {/* Filter / Search Bar */}
      <div className="feed-toolbar">
        <div className="feed-search-box">
          <Icon name="search" size={16} />
          <input
            type="text"
            className="feed-search-input"
            placeholder="Search events, tools, rules…"
            aria-label="Search events"
            value={filterText}
            onChange={e => setFilterText(e.target.value)}
          />
          {filterText && (
            <button
              type="button"
              className="clear-search-btn"
              aria-label="Clear event search"
              onClick={() => setFilterText("")}
            >
              <Icon name="close" size={13} />
            </button>
          )}
        </div>

        <div className="feed-category-tabs">
          {(["all", "llm", "tool", "security", "error"] as const).map(cat => (
            <button
              key={cat}
              type="button"
              className={`feed-cat-btn ${activeCategory === cat ? "active" : ""}`}
              onClick={() => setActiveCategory(cat)}
            >
              {cat === "llm" ? "LLM" : cat[0].toUpperCase() + cat.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Rows Container */}
      {actionError && <div className="inline-error" role="status">{actionError}</div>}
      <div className="event-column-head"><span>Time</span><span>Agent</span><span>Event</span><span>Evidence</span></div>
      <div className="feed-rows" ref={rowsRef}>
        {filtered.length === 0 ? (
          <div className="empty-terminal-state">
            <Icon name="activity" size={28} />
            <h3>{filterText || activeCategory !== "all" ? "No matching events" : "Waiting for agent activity"}</h3>
            <div className="terminal-output-line">
              {filterText || activeCategory !== "all"
                ? "Try another search or event category."
                : connected ? "Agent lifecycle events will appear here as they arrive." : "The live stream is disconnected. History will appear when the engine is available."}
            </div>
            <div className="terminal-hint">
              {!filterText && activeCategory === "all" && <>Connect an agent integration to start monitoring.</>}
            </div>
          </div>
        ) : (
          filtered.map(e => {
            const { badge, body, cls } = line(e);
            const isExpanded = expandedId === e.id;
            const isCopied = copiedId === e.id;
            const dateObj = new Date(e.ts * 1000);
            const dateStr = `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, "0")}-${String(dateObj.getDate()).padStart(2, "0")}`;
            const timeStr = dateObj.toLocaleTimeString([], {
              hour12: false,
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });
            const millis = String(dateObj.getMilliseconds()).padStart(3, "0");

            return (
              <div
                key={e.id}
                id={`event-${e.id}`}
                className={`event-row-container ${isExpanded ? "expanded" : ""}`}
              >
                <button
                  type="button"
                  className={`row ${cls}`}
                  onClick={() => toggleExpand(e.id)}
                  aria-expanded={isExpanded}
                  title="Click to inspect raw JSON payload"
                >
                  <span className="ts" title={`${dateStr} ${timeStr}.${millis} (ts: ${e.ts})`}>
                    <span className="date">{dateStr}</span> {timeStr}.<span className="ms">{millis}</span>
                  </span>
                  <span className="agent" title={`Agent: ${e.agent}`}>
                    {e.agent}
                  </span>
                  <span className="badge">{badge}</span>
                  <span className="body">{body}</span>
                  <span className="row-expand-arrow"><Icon name={isExpanded ? "close" : "chevron"} size={12} /></span>
                </button>

                {/* Inspectable Raw JSON Drawer */}
                {isExpanded && (
                  <div className="event-inspector-drawer">
                    <div className="inspector-bar">
                      <span className="inspector-title">
                        Event details · <span className="t-cyan">{e.id.slice(0, 12)}</span>
                      </span>
                      <div className="inspector-actions">
                        <button
                          type="button"
                          className="dev-btn mini"
                          onClick={ev => copyEventJson(e, ev)}
                        >
                          {isCopied ? "Copied" : "Copy JSON"}
                        </button>
                      </div>
                    </div>
                    <div className="event-detail-summary"><strong>{badge} · {e.agent}</strong><span>{dateStr} {timeStr}.{millis}</span><span>Session <code>{e.session_id}</code></span>{e.parent_event_id && <span>Parent event <code>{e.parent_event_id}</code></span>}</div>
                    <pre className="inspector-json">
                      {JSON.stringify(e, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
