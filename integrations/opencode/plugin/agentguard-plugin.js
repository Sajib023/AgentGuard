/**
 * AgentGuard adapter for OpenCode — prompt firewall, live telemetry feed,
 * and circuit-breaker enforcement.
 *
 * Loads under both OpenCode V2 (Plugin.define + setup(ctx)) and V1
 * (server() hook object) from the same entry.
 *
 * Configuration (environment):
 *   AGENTGUARD_URL       base URL of the AgentGuard service
 *                        (default http://127.0.0.1:8907)
 *   AGENTGUARD_MODE      enforce | observe  (default enforce)
 *   AGENTGUARD_BREAKER   shield tool calls/prompt admission with breaker
 *                        status polling (default true)
 *
 * Options in opencode.json plugins entry are supported for V2
 * ({package: "./.opencode/plugins/agentguard", options: {url, mode, breaker}}).
 */

const DEFAULTS = {
  url: process.env.AGENTGUARD_URL || "http://127.0.0.1:8907",
  mode: process.env.AGENTGUARD_MODE || "enforce",
  breaker: String(process.env.AGENTGUARD_BREAKER ?? "true") !== "false",
};

function sha(str) {
  // lightweight stable digest (no deps): FNV-1a 32-bit, hex
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0") + str.length.toString(36);
}

function makeClient(cfg) {
  const post = async (path, body) => {
    try {
      const r = await fetch(cfg.url + path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      return r.ok ? await r.json() : null;
    } catch {
      return null; // service down: never crash the host agent
    }
  };
  const get = async (path) => {
    try {
      const r = await fetch(cfg.url + path);
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  };
  const sendEvent = (sessionID, type, data) =>
    post("/v1/events", { events: [{ agent: "opencode", session_id: sessionID, type, data }] });
  const firewall = (body) => post("/v1/firewall/check", body);
  const breaker = (sid) => get(`/v1/breaker/status/${sid}`);
  const reportPid = (sid) =>
    post(`/v1/sessions/${sid}/pid`, { pid: process.pid, ppid: process.ppid });
  return { post, get, sendEvent, firewall, breaker, reportPid };
}

const seenSessions = new Set();
const lastTokens = new Map(); // sid -> {input, output, cost}

/** Sessions may never appear in the event stream (naming varies across
 * versions); register lazily from any hook that sees one. */
async function ensureSession(client, ctx, sid, hints = {}) {
  if (!sid || sid === "unknown" || seenSessions.has(sid)) return;
  seenSessions.add(sid);
  let model = hints.model;
  if (ctx?.session?.get) {
    try {
      const info = await ctx.session.get({ sessionID: sid });
      if (info) {
        if (!model && info.model) model = `${info.model.providerID ?? ""}/${info.model.modelID ?? info.model.id ?? ""}`;
      }
    } catch { void 0; }
  }
  void client.sendEvent(sid, "session_start", { model: model || undefined, cwd: process.cwd?.() });
  void client.reportPid(sid);
}

/** Token flow via cumulative Session.Info deltas (event names vary). */
async function pollTokens(client, ctx, sid) {
  if (!ctx?.session?.get || !sid || sid === "unknown") return;
  try {
    const info = await ctx.session.get({ sessionID: sid });
    const t = info?.tokens || {};
    const cost = Number(info?.cost ?? 0) || 0;
    const prev = lastTokens.get(sid) || { input: 0, output: 0, cache: 0, cost: 0 };
    const di = Math.max(0, Math.round((t.input ?? 0) - prev.input));
    const dout = Math.max(0, Math.round((t.output ?? 0) - prev.output));
    const dcache = Math.max(0, Math.round((t.cache?.read ?? 0) - prev.cache));
    const dcost = Math.max(0, cost - prev.cost);
    lastTokens.set(sid, {
      input: t.input ?? 0, output: t.output ?? 0, cache: t.cache?.read ?? 0, cost,
    });
    if (di + dout + dcache > 0) {
      void client.sendEvent(sid, "llm_call", {
        input_tokens: di,
        output_tokens: dout,
        cache_read_tokens: dcache,
        cost_usd: dcost || undefined,
        model: info?.model ? `${info.model.providerID ?? ""}/${info.model.modelID ?? info.model.id ?? ""}` : undefined,
      });
    }
  } catch { void 0; }
}

/** Session IDs may appear in different event shapes across hooks/versions. */
function resolveSid(event) {
  return (
    event?.sessionID ||
    event?.session_id ||
    event?.metadata?.sessionID ||
    event?.properties?.sessionID ||
    "unknown"
  );
}

function extractTokens(payload) {
  const c = payload?.info ?? payload ?? {};
  const t = c.tokens || c.usage || payload?.tokens || {};
  const input = Number(t.input ?? t.promptTokens ?? t.prompt_tokens ?? 0) || 0;
  const output = Number(t.output ?? t.completionTokens ?? t.completion_tokens ?? 0) || 0;
  if (!input && !output) return null;
  const cost = Number(c.cost ?? payload?.cost ?? 0) || null;
  return {
    input_tokens: input,
    output_tokens: output,
    cache_read_tokens: Number(t.cache?.read ?? t.cacheReadTokens ?? 0) || 0,
    cost_usd: cost ?? undefined,
    provider: c.providerID ?? undefined,
    model: c.modelID ?? undefined,
  };
}

/**
 * Escape-hatch matcher: text that manages the AgentGuard service itself —
 * control API paths (/v1/breaker, /v1/approvals, /v1/config) or the
 * agentguard CLI (stop/doctor/serve). Such traffic must never be shielded
 * away: with the circuit open, the only commands that can reset the shield
 * are these, so blocking them deadlocks the whole setup. */
function isManagementText(t) {
  return /\/v1\/(breaker|approvals|config)(\/|\b)/.test(t || "") ||
    /(^|[^\w])agentguard\s+(stop|doctor|serve|status)\b/.test(t || "");
}

/* ------------------------------------------------------------------ V2 ---- */
async function setup(ctx) {
  const cfg = { ...DEFAULTS };
  if (ctx.options && typeof ctx.options === "object") {
    if (ctx.options.url) cfg.url = String(ctx.options.url);
    if (ctx.options.mode) cfg.mode = String(ctx.options.mode);
    if (ctx.options.breaker !== undefined)
      cfg.breaker = String(ctx.options.breaker) !== "false";
  }
  const client = makeClient(cfg);
  const enforce = () => cfg.mode === "enforce";
  const breakerOpen = new Map(); // sid -> {ts, open}

  const breakerCheck = async (sid) => {
    if (!cfg.breaker || !sid) return null;
    const cached = breakerOpen.get(sid);
    if (cached && Date.now() - cached.ts < 1000) return cached.open ? cached : null;
    const st = await client.breaker(sid);
    const open = !!st && (st.status === "stopped" || st.status === "breached");
    breakerOpen.set(sid, { ts: Date.now(), open });
    return open ? { reason: `circuit ${st.status}` } : null;
  };

  const circuitError = (what, st) =>
    new Error(`agentguard: ${what} blocked — circuit breaker ${st.reason} (limits exceeded; approve/reset in AgentGuard)`);

  // --- prompt admission firewall -----------------------------------------
  await ctx.session.hook("prompt", async (event) => {
    try {
      const sid = resolveSid(event);
      void ensureSession(client, ctx, sid);
      void pollTokens(client, ctx, sid);

      const text = event?.prompt?.text || "";
      // ESCAPE HATCH: a prompt that manages AgentGuard itself (breaker
      // reset/limits, approvals) is admitted even with the breaker open —
      // otherwise an open circuit locks the operator out of the only
      // channel that can reset it. The firewall still sees the text.
      if (!isManagementText(text)) {
        const br = await breakerCheck(sid);
        if (br && enforce()) throw circuitError("prompt", br);
      }
      if (!text.trim()) return;
      const v = await client.firewall({
        text,
        session_id: sid,
        agent: "opencode",
        context_type: "prompt",
        await_approval: true,
        approval_timeout: Number(process.env.AGENTGUARD_APPROVAL_TIMEOUT || 120),
      });
      if (!v) return; // service unreachable → fail-open
      if (v.action === "allow") return;
      if (v.action === "sanitize" && enforce()) {
        event.prompt.text = v.sanitized_text || text;
        return;
      }
      // block/approve-denied/observe-mode-record
      if (v.action === "approve" && !enforce()) return; // observe: pass through
      if (!enforce()) return;                            // observe: record only
      throw new Error(
        `agentguard: prompt blocked by firewall — ${v.decision_reason}` +
          (v.violations?.length ? ` [${v.violations.map(x => x.rule).join(", ")}]` : "")
      );
    } catch (e) {
      if (String(e?.message || "").startsWith("agentguard:")) throw e;
      // unexpected: fail-open, log via event
      void e;
    }
  });

  // --- tool-call firewall + telemetry ------------------------------------
  await ctx.tool.hook("execute.before", async (event) => {
    try {
      const sid = resolveSid(event);
      void ensureSession(client, ctx, sid);
      void pollTokens(client, ctx, sid);

      const input = event?.input ?? {};
      let serialized = "";
      try { serialized = JSON.stringify(input); } catch { void 0; }

      // ESCAPE HATCH: calls that manage AgentGuard itself (breaker
      // reset/limits, approval resolution, agentguard CLI) skip the breaker
      // shield — an open circuit would otherwise block the very commands
      // that reset it. They are still recorded and still firewalled.
      if (isManagementText(serialized)) {
        void client.sendEvent(sid, "tool_call", {
          name: event.tool,
          args_digest: sha(serialized || event.tool),
          args_preview: serialized.slice(0, 240),
          status: "management_pass",
        });
        void client.firewall({
          text: serialized.slice(0, 20000),
          session_id: sid,
          agent: "opencode",
          context_type: "tool_input",
        });
        return;
      }

      const br = await breakerCheck(sid);
      if (br && enforce()) throw circuitError("tool call", br);

      void client.sendEvent(sid, "tool_call", {
        name: event.tool,
        args_digest: sha(serialized || event.tool),
        args_preview: serialized.slice(0, 240),
        status: "started",
      });

      const v = await client.firewall({
        text: serialized.slice(0, 20000),
        session_id: sid,
        agent: "opencode",
        context_type: "tool_input",
      });
      if (!v || v.action === "allow" || !enforce()) return;
      if (v.action === "sanitize") {
        // redact secrets inside string fields
        try {
          const sanitized = JSON.parse(v.sanitized_text || serialized);
          event.input = sanitized;
        } catch { void v; }
        return;
      }
      throw circuitOpenBlock("tool call", v);
    } catch (e) {
      if (String(e?.message || "").startsWith("agentguard:")) throw e;
      void e;
    }
  });

  await ctx.tool.hook("execute.after", async (event) => {
    try {
      const sid = resolveSid(event);
      void client.sendEvent(sid, "tool_call", {
        name: event?.tool,
        status: event?.status === "error" ? "error" : "success",
        duration_ms: undefined,
        result_preview: (event?.status === "error"
          ? String(event?.error?.message || "")
          : JSON.stringify(event?.result ?? "")
        ).slice(0, 240),
      });
    } catch {
      void 0;
    }
  });

  // --- event stream → monitoring ------------------------------------------
  const controller = new AbortController();
  void (async () => {
    for await (const ev of ctx.event.subscribe({ signal: controller.signal })) {
      try {
        const type = ev?.type || "";
        const payload = ev?.properties ?? ev?.payload ?? {};
        // session lifecycle
        const info = payload?.info || payload;
        const sid = info?.id || payload?.sessionID || payload?.id;
        if (!sid) continue;
        if ((type === "session.created" || type === "session.updated") && !seenSessions.has(sid)) {
          void ensureSession(client, ctx, sid, { model: info?.modelID || info?.model });
        }
        if (type === "session.deleted" || type === "session.idle") {
          void client.sendEvent(sid, type === "session.idle" ? "state_change" : "session_end", {
            state: type === "session.idle" ? "idle" : undefined,
          });
        }
        // token accounting: delta-poll on any sid-bearing event (final run
        // counts land here via session.idle / updated events), plus the
        // direct token payload extraction when shapes disclose it
        const toks = extractTokens(payload);
        if (toks) void client.sendEvent(sid, "llm_call", toks);
        void pollTokens(client, ctx, sid);
        // permission requests → dashboard
        if (type.startsWith("permission.")) {
          void client.sendEvent(sid, "approval_request", {
            reason: JSON.stringify(payload).slice(0, 200),
            metric: "permission",
          });
        }
        if (type === "session.error" || type === "error") {
          void client.sendEvent(sid, "error", {
            message: String(payload?.error || payload?.message || type).slice(0, 240),
          });
        }
      } catch {
        void 0;
      }
    }
  })().catch(() => {});

  return () => controller.abort();
}

function circuitOpenBlock(what, v) {
  return new Error(
    `agentguard: ${what} blocked — ${v.decision_reason}` +
      (v.violations?.length ? ` [${v.violations.map(x => x.rule).join(", ")}]` : "")
  );
}

/* ------------------------------------------------------------------ V1 ---- */
function makeV1(cfg) {
  const client = makeClient(cfg);
  const enforce = () => cfg.mode === "enforce";
  return {
    async "chat.message"(input, output) {
      // V1 equivalent of the prompt hook
      try {
        const text = output?.message?.text ?? "";
        if (!text.trim() || !enforce()) return;
        const sid = input?.sessionID || "unknown";
        const brSid = await (async () => {
          const st = cfg.breaker ? await client.breaker(sid) : null;
          return st && (st.status === "stopped" || st.status === "breached") ? st : null;
        })();
        if (brSid) throw circuitOpenBlock("prompt", { decision_reason: `circuit ${brSid.status}` });
        const v = await client.firewall({
          text, session_id: sid, agent: "opencode", await_approval: true,
          approval_timeout: 120,
        });
        if (v && enforce()) {
          if (v.action === "sanitize") output.message.text = v.sanitized_text || text;
          else if (v.action !== "allow" && v.action !== "approve")
            throw circuitOpenBlock("prompt", v);
          else if (v.action === "approve") { /* approval pending w/o UI in V1: block */ }
        }
      } catch (e) {
        if (String(e?.message || "").startsWith("agentguard:")) throw e;
      }
    },
    async "tool.execute.before"(input, output) {
      let sid = (input && input.sessionID) || "unknown";
      try {
        let serialized = "";
        try { serialized = JSON.stringify(output?.args || {}); } catch {}
        if (isManagementText(serialized)) {
          void client.sendEvent(sid, "tool_call", {
            name: input?.tool, args_digest: sha(serialized || input?.tool),
            args_preview: serialized.slice(0, 240), status: "management_pass",
          });
          return;
        }
        if (cfg.breaker) {
          const st = await client.breaker(sid);
          if (st && (st.status === "stopped" || st.status === "breached") && enforce())
            throw circuitOpenBlock("tool call", { decision_reason: `circuit ${st.status}` });
        }
        void client.sendEvent(sid, "tool_call", {
          name: input?.tool, args_digest: sha(serialized || input?.tool),
          args_preview: serialized.slice(0, 240), status: "started",
        });
        const v = await client.firewall({
          text: serialized.slice(0, 20000), session_id: sid, agent: "opencode",
        });
        if (v && enforce() && (v.action === "block"))
          throw circuitOpenBlock("tool call", v);
      } catch (e) {
        if (String(e?.message || "").startsWith("agentguard:")) throw e;
      }
    },
    async "tool.execute.after"(input, output) {
      try {
        void client.sendEvent((input && input.sessionID) || "unknown", "tool_call", {
          name: input?.tool,
          status: (output && output.status === "error") ? "error" : "success",
          result_preview: String(output?.title || "").slice(0, 200),
        });
      } catch {}
    },
    async event({ event }) {
      try {
        const type = event?.type || "";
        const props = event?.properties || {};
        const info = props?.info || props;
        const sid = info?.id || props?.sessionID;
        if (!sid) return;
        if (type === "session.updated" && !seenSessions.has(sid)) {
          seenSessions.add(sid);
          void client.sendEvent(sid, "session_start", {
            model: info?.modelID, cwd: info?.directory,
          });
          void client.reportPid(sid);
        }
        const toks = extractTokens(props);
        if (toks) void client.sendEvent(sid, "llm_call", toks);
        if (type === "session.error") {
          void client.sendEvent(sid, "error", { message: String(props?.error || type) });
        }
      } catch {}
    },
  };
}

/* --------------------------------------------------------------- export --- */
let Plugin = null;
try {
  // @opencode/plugin exists on V2 runtime; absent on V1
  const mod = await import("@opencode/plugin");
  Plugin = mod.Plugin;
} catch {
  Plugin = null;
}

const cfgV1 = { ...DEFAULTS };

const entry = Plugin
  ? Plugin.define({ id: "agentguard", setup })
  : { id: "agentguard" };

if (!Plugin) {
  entry.server = async () => makeV1(cfgV1);
}

export { isManagementText };
export default entry;
