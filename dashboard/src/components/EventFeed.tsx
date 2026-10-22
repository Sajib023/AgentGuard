import { useState, useMemo, type ReactNode } from "react";
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
        body: <span className="text-muted">{(d.content || "").slice(0, 110) || d.preview || `${d.chars} chars`}</span>,
      };
    case "prompt_after":
      return {
        ...base,
        badge: "PROMPT:OUT",
        body: <span className="text-muted">{(d.content || "").slice(0, 110) || d.preview || `${d.chars} chars`}</span>,
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
            {d.iteration !== undefined && <span className="dev-iter">iter #{d.iteration}</span>}
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
}: {
  events: AgentEvent[];
  connected: boolean;
  sessionFilter: string | null;
  onClear?: () => void;
}) {
  const [filterText, setFilterText] = useState("");
  const [activeCategory, setActiveCategory] = useState<"all" | "llm" | "tool" | "security" | "error">("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [frozenEvents, setFrozenEvents] = useState<AgentEvent[]>([]);

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
      list = list.filter(
        e =>
          e.agent.toLowerCase().includes(q) ||
          e.type.toLowerCase().includes(q) ||
          e.session_id.toLowerCase().includes(q) ||
          JSON.stringify(e.data).toLowerCase().includes(q)
      );
    }

    return list;
  }, [currentEvents, sessionFilter, activeCategory, filterText]);

  const toggleExpand = (id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
  };

  const copyEventJson = (e: AgentEvent, ev: React.MouseEvent) => {
    ev.stopPropagation();
    navigator.clipboard.writeText(JSON.stringify(e, null, 2)).then(() => {
      setCopiedId(e.id);
      setTimeout(() => setCopiedId(null), 1800);
    });
  };

  return (
    <div className="feed">
      {/* Stream Control Bar */}
      <div className="feed-head">
        <div className="feed-title-group">
          <span className="feed-title">EVENT STREAM</span>
          <span className="feed-count-badge">{filtered.length} ROWS</span>
          {sessionFilter && (
            <span className="feed-filter-tag">
              SESSION: {sessionFilter.slice(0, 10)}…
            </span>
          )}
        </div>

        <div className="feed-actions">
          <button
            type="button"
            className={`dev-btn mini ${isPaused ? "active-pause" : ""}`}
            onClick={handleTogglePause}
            title={isPaused ? "Resume live auto-updating" : "Pause live auto-updating"}
          >
            {isPaused ? "▶ RESUME" : "⏸ PAUSE"}
          </button>
          {onClear && (
            <button
              type="button"
              className="dev-btn mini"
              onClick={onClear}
              title="Clear event history in view"
            >
              CLEAR
            </button>
          )}
          <div className="ws-indicator-pill">
            <span className={`ws-dot ${connected ? "on" : "off"}`} />
            <span className="ws-text">{connected ? "LIVE" : "DISCONNECTED"}</span>
          </div>
        </div>
      </div>

      {/* Filter / Search Bar */}
      <div className="feed-toolbar">
        <div className="feed-search-box">
          <span className="search-icon">⌕</span>
          <input
            type="text"
            className="feed-search-input"
            placeholder="grep events (filter text, model, rules, args)..."
            value={filterText}
            onChange={e => setFilterText(e.target.value)}
          />
          {filterText && (
            <button
              type="button"
              className="clear-search-btn"
              onClick={() => setFilterText("")}
            >
              ✕
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
              {cat.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Rows Container */}
      <div className="feed-rows">
        {filtered.length === 0 ? (
          <div className="empty-terminal-state">
            <div className="terminal-ascii-header">
              <span className="t-green">●</span> <span className="t-cyan">agentguard.stream</span>
            </div>
            <div className="terminal-prompt-line">
              <span className="t-prompt">$</span> agentguard tail --follow
            </div>
            <div className="terminal-output-line">
              {filterText || activeCategory !== "all"
                ? "> No events match current filter criteria."
                : "> Socket listening on /v1/ws. Awaiting agent lifecycle events..."}
            </div>
            <div className="terminal-hint">
              Run any adapter or post to <code className="t-code">/v1/events</code> to stream telemetry.
            </div>
          </div>
        ) : (
          filtered.map(e => {
            const { badge, body, cls } = line(e);
            const isExpanded = expandedId === e.id;
            const isCopied = copiedId === e.id;
            const dateObj = new Date(e.ts * 1000);
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
                className={`event-row-container ${isExpanded ? "expanded" : ""}`}
              >
                <div
                  className={`row ${cls}`}
                  onClick={() => toggleExpand(e.id)}
                  title="Click to inspect raw JSON payload"
                >
                  <span className="ts" title={`ts: ${e.ts}`}>
                    {timeStr}.<span className="ms">{millis}</span>
                  </span>
                  <span className="agent" title={`Agent: ${e.agent}`}>
                    {e.agent}
                  </span>
                  <span className="badge">{badge}</span>
                  <span className="body">{body}</span>
                  <span className="row-expand-arrow">{isExpanded ? "▼" : "▶"}</span>
                </div>

                {/* Inspectable Raw JSON Drawer */}
                {isExpanded && (
                  <div className="event-inspector-drawer">
                    <div className="inspector-bar">
                      <span className="inspector-title">
                        PAYLOAD INSPECTOR · <span className="t-cyan">{e.id}</span>
                      </span>
                      <div className="inspector-actions">
                        <button
                          type="button"
                          className="dev-btn mini"
                          onClick={ev => copyEventJson(e, ev)}
                        >
                          {isCopied ? "✓ COPIED" : "COPY JSON"}
                        </button>
                      </div>
                    </div>
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
