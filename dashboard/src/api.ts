import type { ApprovalRow, BreakerSnapshot, Health, MCPStatus, RAGHit, RAGStatus, SessionRow } from "./types";

const BASE = "/v1";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch(`${BASE}/healthz`).then(j<Health>),
  sessions: () => fetch(`${BASE}/sessions`).then(r => j<{ sessions: SessionRow[] }>(r)),
  events: (q: Record<string, string | number | undefined> = {}) => {
    const usp = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && usp.set(k, String(v)));
    return fetch(`${BASE}/events?${usp}`).then(r => j<{ events: any[] }>(r));
  },
  breakerAll: () => fetch(`${BASE}/breaker/status`).then(r => j<{ sessions: BreakerSnapshot[] }>(r)),
  approvals: () => fetch(`${BASE}/approvals`).then(r => j<{ approvals: ApprovalRow[] }>(r)),
  resolveApproval: (id: string, approved: boolean) =>
    fetch(`${BASE}/approvals/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, by: "dashboard" }),
    }).then(j<any>),
  setMode: (mode: "enforce" | "observe") =>
    fetch(`${BASE}/config/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).then(j<any>),
  resetBreaker: (sid: string) =>
    fetch(`${BASE}/breaker/reset/${sid}`, { method: "POST" }).then(j<any>),
  ragStatus: () => fetch(`${BASE}/rag/status`).then(j<RAGStatus>),
  ragQuery: (query: string, sessionId?: string | null, topK = 5, category?: string | null) =>
    fetch(`${BASE}/rag/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        top_k: topK,
        category: category || undefined,
        session_id: sessionId || undefined,
        include_graph: true,
      }),
    }).then(j<{ hits: RAGHit[]; graph: any; elapsed_ms: number; techniques_applied?: string[] }>),
  ragIngest: (body: {
    title: string;
    content: string;
    source?: string;
    category?: string;
    severity?: string;
    action?: string;
  }) =>
    fetch(`${BASE}/rag/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<any>),
  graphLineage: (query?: string, sessionId?: string | null, maxHops = 3) => {
    const usp = new URLSearchParams({ max_hops: String(maxHops) });
    if (query) usp.set("query", query);
    if (sessionId) usp.set("session_id", sessionId);
    return fetch(`${BASE}/graph/lineage?${usp}`).then(j<any>);
  },
  mcpStatus: () => fetch(`${BASE}/mcp/status`).then(j<MCPStatus>),
  mcpCall: (name: string, args: Record<string, any> = {}) =>
    fetch(`${BASE}/mcp/call`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, arguments: args }),
    }).then(j<{ ok: boolean; tool: string; result: any }>),
  firewallRules: () =>
    fetch(`${BASE}/firewall/rules`).then(
      j<{ rules: Array<{ name: string; kind: string; description: string; confidence: number; weight: number }> }>
    ),
  setBreakerLimits: (sessionId: string, limits: Record<string, number>) =>
    fetch(`${BASE}/breaker/limits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, limits }),
    }).then(j<any>),
  downloadSessionLog: async (
    sessionId: string | null,
    format: "context-md" | "context-json" | "raw-json" = "context-md"
  ) => {
    const safeName = sessionId
      ? sessionId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48)
      : "all-sessions";

    const [evRes, sessRes] = await Promise.all([
      api.events({
        session_id: sessionId ?? undefined,
        limit: 10000,
        order: "desc",
      }),
      sessionId
        ? fetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}`)
            .then(r =>
              r.ok && (r.headers.get("content-type") || "").includes("application/json")
                ? r.json()
                : null
            )
            .catch(() => null)
        : Promise.resolve(null),
    ]);

    const rawDesc = [...(evRes.events || [])].sort((a, b) => b.ts - a.ts);

    if (format === "raw-json") {
      const rawContent = JSON.stringify(
        {
          session_id: sessionId || "all",
          exported_at: new Date().toISOString(),
          order: "newest_to_oldest",
          event_count: rawDesc.length,
          ...(sessRes?.session ? { session: sessRes.session } : {}),
          ...(sessRes?.breaker ? { breaker: sessRes.breaker } : {}),
          events: rawDesc,
        },
        null,
        2
      );
      triggerDownload(rawContent, `agentguard-${safeName}-raw.json`, "application/json");
      return;
    }

    const processed = processEventsIntoContext(
      sessionId || "all",
      rawDesc,
      sessRes?.session || null,
      sessRes?.breaker || null
    );

    if (format === "context-json") {
      triggerDownload(
        JSON.stringify(processed, null, 2),
        `agentguard-${safeName}-context.json`,
        "application/json"
      );
      return;
    }

    const md = renderContextMarkdown(processed);
    triggerDownload(md, `agentguard-${safeName}-context.md`, "text/markdown;charset=utf-8");
  },
};

function triggerDownload(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function tryParseJson(str: any): any {
  if (typeof str !== "string" || !str.trim()) return null;
  try {
    return JSON.parse(str);
  } catch {
    return null;
  }
}

function formatToolInput(rawInput: string): string {
  const parsed = tryParseJson(rawInput);
  if (!parsed || typeof parsed !== "object") return rawInput.trim();
  if (typeof parsed.command === "string") {
    return `$ ${parsed.command}`;
  }
  if (parsed.filePath || parsed.path) {
    const target = parsed.filePath || parsed.path;
    if (parsed.newString !== undefined) {
      return `file: ${target}\n--- old\n${String(parsed.oldString || "").slice(0, 400)}\n+++ new\n${String(parsed.newString || "").slice(0, 600)}`;
    }
    if (parsed.content !== undefined) {
      return `file: ${target}\n${String(parsed.content).slice(0, 800)}`;
    }
    return `file: ${target} ${JSON.stringify(parsed)}`;
  }
  return JSON.stringify(parsed, null, 2);
}

function formatToolOutput(rawResult: string): string {
  if (!rawResult) return "";
  const parsed = tryParseJson(rawResult);
  if (parsed && typeof parsed === "object") {
    const out = parsed.output ?? parsed;
    if (typeof out === "string") return out.trim();
    if (out && typeof out === "object") {
      if (typeof out.output === "string") {
        const exitTag = out.exit !== undefined ? `[exit ${out.exit}] ` : "";
        return `${exitTag}${out.output.trim()}`;
      }
      if (Array.isArray(out.files)) {
        return `Modified files: ${out.files.map((f: any) => f.filePath || f.relativePath || JSON.stringify(f)).join(", ")}`;
      }
    }
    return JSON.stringify(parsed, null, 2);
  }
  return rawResult.trim();
}

function processEventsIntoContext(
  sessionId: string,
  eventsDesc: any[],
  sessionMeta: any,
  breakerMeta: any
) {
  // Process chronologically to pair pre-tool inputs with post-tool outputs, then expose newest-to-oldest & chronological
  const asc = [...eventsDesc].sort((a, b) => a.ts - b.ts);

  const userPrompts: Array<{ ts: string; agent: string; text: string }> = [];
  const incidents: Array<{ ts: string; type: string; summary: string; details?: any }> = [];
  const steps: Array<{
    step: number;
    ts: string;
    epoch: number;
    kind: "user_prompt" | "tool_execution" | "security_incident" | "session_lifecycle";
    title: string;
    input?: string;
    output?: string;
    status?: string;
  }> = [];

  let pendingToolInput = "";
  let pendingToolName = "";
  let llmCalls = 0;
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalCacheReadTokens = 0;
  let totalCostUsd = 0;
  let detectedCwd = sessionMeta?.cwd || null;
  let detectedModel = sessionMeta?.model || null;
  let detectedAgent = sessionMeta?.agent || (asc[0]?.agent ?? "unknown");

  for (const ev of asc) {
    const d = ev.data || {};
    const iso = new Date(ev.ts * 1000).toISOString();

    if (ev.type === "session_start") {
      if (d.cwd && !detectedCwd) detectedCwd = d.cwd;
      if (d.model && !detectedModel) detectedModel = d.model;
      steps.push({
        step: steps.length + 1,
        ts: iso,
        epoch: ev.ts,
        kind: "session_lifecycle",
        title: `Session started (${ev.agent}${d.model ? ` · ${d.model}` : ""}${d.cwd ? ` @ ${d.cwd}` : ""})`,
      });
      continue;
    }

    if (ev.type === "session_end") {
      steps.push({
        step: steps.length + 1,
        ts: iso,
        epoch: ev.ts,
        kind: "session_lifecycle",
        title: `Session ended (${ev.agent})`,
      });
      continue;
    }

    if (ev.type === "llm_call") {
      llmCalls += 1;
      totalInputTokens += Number(d.input_tokens || 0);
      totalOutputTokens += Number(d.output_tokens || 0);
      totalCacheReadTokens += Number(d.cache_read_tokens || 0);
      totalCostUsd += Number(d.cost_usd || 0);
      if (d.model && !detectedModel) detectedModel = d.model;
      continue;
    }

    if (ev.type === "prompt_before") {
      const content = String(d.content || d.preview || "").trim();
      if (d.context_type === "prompt") {
        if (content) {
          userPrompts.push({ ts: iso, agent: ev.agent, text: content });
          steps.push({
            step: steps.length + 1,
            ts: iso,
            epoch: ev.ts,
            kind: "user_prompt",
            title: "User Prompt",
            input: content,
          });
        }
      } else if (d.context_type === "tool_input" && content) {
        pendingToolInput = formatToolInput(content);
      }
      continue;
    }

    if (ev.type === "prompt_after") {
      // Redundant wrapper when paired with prompt_before & firewall_verdict
      continue;
    }

    if (ev.type === "firewall_verdict") {
      // Only keep non-benign verdicts (sanitize, approve, block, or risk_score > 0)
      if (d.action && d.action !== "allow") {
        const rules = (d.violations || []).map((v: any) => v.rule).join(", ");
        const summary = `Firewall ${String(d.action).toUpperCase()} (risk=${d.risk_score}): ${d.reason}${rules ? ` [${rules}]` : ""}`;
        incidents.push({ ts: iso, type: `firewall_${d.action}`, summary, details: d.violations });
        steps.push({
          step: steps.length + 1,
          ts: iso,
          epoch: ev.ts,
          kind: "security_incident",
          title: summary,
          status: d.action,
        });
      }
      continue;
    }

    if (ev.type === "tool_call") {
      const name = d.name || pendingToolName || "tool";
      const argsPreview = String(d.args_preview || "").trim();
      const resultPreview = String(d.result_preview || "").trim();

      // Pre-execution tool_call (has args_preview, no result_preview yet)
      if (argsPreview && !resultPreview) {
        pendingToolName = name;
        if (!pendingToolInput) {
          pendingToolInput = formatToolInput(argsPreview);
        }
        continue;
      }

      // Post-execution tool_call (or single combined tool_call)
      const finalInput = pendingToolInput || (argsPreview ? formatToolInput(argsPreview) : "");
      const finalOutput = formatToolOutput(resultPreview);

      steps.push({
        step: steps.length + 1,
        ts: iso,
        epoch: ev.ts,
        kind: "tool_execution",
        title: `Tool: ${name}`,
        status: d.status || "done",
        ...(finalInput ? { input: finalInput } : {}),
        ...(finalOutput ? { output: finalOutput } : {}),
      });
      pendingToolInput = "";
      pendingToolName = "";
      continue;
    }

    if (
      ev.type === "breaker_alert" ||
      ev.type === "breaker_stop" ||
      ev.type === "approval_request" ||
      ev.type === "approval_decision" ||
      ev.type === "error"
    ) {
      const summary =
        ev.type === "breaker_stop"
          ? `Circuit Breaker STOPPED (${d.metric}: ${d.value} / ${d.limit} -> ${d.enforcement})`
          : ev.type === "breaker_alert"
          ? `Circuit Breaker Warning (${d.metric}: ${d.value} / ${d.limit})`
          : ev.type === "error"
          ? `Error (${d.kind || "runtime"}): ${d.message || JSON.stringify(d)}`
          : `${ev.type}: ${d.reason || d.status || JSON.stringify(d)}`;

      incidents.push({ ts: iso, type: ev.type, summary, details: d });
      steps.push({
        step: steps.length + 1,
        ts: iso,
        epoch: ev.ts,
        kind: "security_incident",
        title: summary,
        status: ev.type,
      });
    }
  }

  // Flush any trailing pending tool input that didn't get a post-tool event (e.g. blocked/killed mid-call)
  if (pendingToolInput) {
    steps.push({
      step: steps.length + 1,
      ts: new Date().toISOString(),
      epoch: Date.now() / 1000,
      kind: "tool_execution",
      title: `Tool: ${pendingToolName || "pending_tool"} (in-flight / interrupted)`,
      status: "interrupted",
      input: pendingToolInput,
    });
  }

  const stepsNewestFirst = [...steps].sort((a, b) => b.epoch - a.epoch || b.step - a.step);

  return {
    session_id: sessionId,
    exported_at: new Date().toISOString(),
    summary: {
      agent: detectedAgent,
      model: detectedModel,
      cwd: detectedCwd,
      raw_events_collapsed: eventsDesc.length,
      meaningful_steps: steps.length,
      user_prompts_count: userPrompts.length,
      incidents_count: incidents.length,
      llm_calls: sessionMeta?.llm_calls ?? llmCalls,
      input_tokens: sessionMeta?.input_tokens ?? totalInputTokens,
      output_tokens: sessionMeta?.output_tokens ?? totalOutputTokens,
      cache_read_tokens: totalCacheReadTokens,
      cost_usd: sessionMeta?.cost_usd ?? totalCostUsd,
      breaker_status: breakerMeta?.status ?? "nominal",
      breaker_limits: breakerMeta?.limits ?? null,
    },
    user_prompts: userPrompts,
    incidents: [...incidents].reverse(),
    steps_newest_first: stepsNewestFirst,
  };
}

function renderContextMarkdown(ctx: ReturnType<typeof processEventsIntoContext>): string {
  const s = ctx.summary;
  const lines: string[] = [];

  lines.push(`# AgentGuard Session Context Pack`);
  lines.push(`- **Session ID:** \`${ctx.session_id}\``);
  lines.push(`- **Agent / Model:** \`${s.agent}\` · \`${s.model || "default"}\``);
  if (s.cwd) lines.push(`- **Workspace (\`cwd\`):** \`${s.cwd}\``);
  lines.push(`- **Circuit Breaker State:** \`${String(s.breaker_status).toUpperCase()}\``);
  lines.push(
    `- **Usage:** ${s.llm_calls} LLM calls · ${(s.input_tokens + s.output_tokens).toLocaleString()} tokens (in: ${s.input_tokens.toLocaleString()}, out: ${s.output_tokens.toLocaleString()}, cache_read: ${s.cache_read_tokens.toLocaleString()}) · $${Number(s.cost_usd || 0).toFixed(4)}`
  );
  lines.push(
    `- **Signal Compression:** Collapsed ${s.raw_events_collapsed} raw telemetry events into **${s.meaningful_steps} actionable context steps** (newest to oldest)`
  );
  lines.push("");

  if (ctx.incidents.length > 0) {
    lines.push(`## ⚠ Security & Circuit Breaker Incidents (${ctx.incidents.length})`);
    for (const inc of ctx.incidents) {
      lines.push(`- **[${inc.ts}]** \`${inc.type}\` — ${inc.summary}`);
    }
    lines.push("");
  }

  if (ctx.user_prompts.length > 0) {
    lines.push(`## 💬 User Prompts (${ctx.user_prompts.length})`);
    ctx.user_prompts.forEach((p, idx) => {
      lines.push(`### Prompt #${idx + 1} (${p.ts})`);
      lines.push(p.text);
      lines.push("");
    });
  }

  lines.push(`## 🛠 Execution Context Timeline (Newest to Oldest)`);
  lines.push("");

  for (const st of ctx.steps_newest_first) {
    const statusBadge = st.status ? ` [${st.status.toUpperCase()}]` : "";
    lines.push(`### Step #${st.step} · ${st.title}${statusBadge} — \`${st.ts}\``);
    if (st.input) {
      lines.push("```");
      lines.push(st.input);
      lines.push("```");
    }
    if (st.output) {
      lines.push("**Output:**");
      lines.push("```");
      lines.push(st.output);
      lines.push("```");
    }
    lines.push("");
  }

  return lines.join("\n");
}

export function wsUrl(sessionId?: string | null, replay = 200): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const p = new URLSearchParams({ replay: String(replay) });
  if (sessionId) p.set("session_id", sessionId);
  return `${proto}://${location.host}/v1/ws?${p}`;
}
