/**
 * AgentGuard adapter for OpenCode — prompt firewall, live telemetry feed,
 * and circuit-breaker enforcement.
 *
 * Loader contract (verified against OpenCode 2.1.3 source,
 * packages/core/src/plugin/{module,promise}.ts):
 *   default export = { id, setup }   // bare functions/other shapes rejected
 *   setup(ctx) registers hooks via ctx.*.hook(...) / ctx.event.subscribe()
 *   and returns a CLEANUP function (the loader invokes it when the plugin's
 *   scope closes; returning any other truthy value is invoked as cleanup and
 *   throws). Hooks live on the plugin's scope, so a watcher reload disposes
 *   the previous registration before the fresh setup re-registers.
 *
 * Per-copy ids: global and project plugin dirs are both loaded per location
 * in one process; distinct ids ("agentguard-global" vs "agentguard", from
 * the module path) avoid the registrar's duplicate-id failure. The
 * exactly-once guard is keyed per location directory, not per process:
 * OpenCode builds a separate plugin/tool graph per location, and every
 * location needs its own registration for session/tool hooks to dispatch.
 *
 * Configuration (environment):
 *   AGENTGUARD_URL       base URL of the AgentGuard service
 *                        (default http://127.0.0.1:8907)
 *   AGENTGUARD_MODE      enforce | observe  (default enforce)
 *   AGENTGUARD_BREAKER   shield tool calls/prompt admission with breaker
 *                        status polling (default true)
 *
 * Options in opencode.json plugins entry are supported:
 * ({package: "./.opencode/plugins/agentguard", options: {url, mode, breaker}}).
*/
import { appendFileSync } from "node:fs";

/** Hook/loop breadcrumbs (tmp; tiny + best-effort — never throws). */
const _crumb = (msg) => {
  if ((globalThis.__agentguardCrumbCount = (globalThis.__agentguardCrumbCount || 0) + 1) > 600) return;
  try {
    appendFileSync("/tmp/opencode/agentguard-plugin.log", `${Date.now()} ${msg}\n`);
  } catch {}
};

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
        // the session's own directory beats the plugin process cwd (shared
        // services host many projects: without this, every session on the
        // dashboard "lives" in the service's startup dir)
        if (!hints.directory && info.directory) hints.directory = info.directory;
      }
    } catch { void 0; }
  }
  const cwd = hints.directory || ctx?.directory || process.cwd?.();
  void client.sendEvent(sid, "session_start", { model: model || undefined, cwd });
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
  // Exactly-once activation per LOCATION: OpenCode compiles a full plugin
  // graph per location directory (home root AND the project dir each get
  // their own supervisor + hook registry), and loads this plugin from both
  // the global and the project plugin dir. A process-wide guard would be
  // claimed by whichever activates first and leave every other location
  // with zero registered hooks — so key the guard on ctx.location.directory;
  // both copies inside ONE location share the key (single registration).
  const locDir = (ctx && ctx.location && ctx.location.directory) || "";
  const guardKey = `__agentguardActive_${locDir}`;
  _crumb(`setup enter loc=${locDir || "(none)"}`);
  if (globalThis[guardKey]) {
    _crumb(`setup guard-hit (${guardKey})`);
    return;
  }
  globalThis[guardKey] = true;

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
  _crumb("setup registering session.hook=prompt");
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
  _crumb("setup registering tool.hook=execute.before");
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

  _crumb("setup registering tool.hook=execute.after");
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
  _crumb("setup starting event loop");
  void (async () => {
    _crumb("event loop: entering subscribe");
    for await (const ev of ctx.event.subscribe({ signal: controller.signal })) {
      try {
        const type = ev?.type || "";
        const payload = ev?.properties ?? ev?.payload ?? {};
        // session lifecycle
        const info = payload?.info || payload;
        const sid = info?.id || payload?.sessionID || payload?.id;
        if (!sid) continue;
        if ((type === "session.created" || type === "session.updated") && !seenSessions.has(sid)) {
          void ensureSession(client, ctx, sid, {
            model: info?.modelID || info?.model,
            directory: info?.directory,
          });
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
  })().catch((e) => _crumb("event loop FAILED: " + String(e?.message || e).slice(0, 160)));

  // Cleanup = unload contract: stop the event loop and release the
  // exactly-once guard so a watcher reload can re-activate this module
  // instance (module-level state does not survive, but globalThis does).
  return () => {
    _crumb("cleanup invoked");
    controller.abort();
    delete globalThis[guardKey];
  };
}

function circuitOpenBlock(what, v) {
  return new Error(
    `agentguard: ${what} blocked — ${v.decision_reason}` +
      (v.violations?.length ? ` [${v.violations.map(x => x.rule).join(", ")}]` : "")
  );
}


/* --------------------------------------------------------------- export --- */
/* The loader (core/src/plugin/module.ts) validates ONLY `default` as
 * { id, effect | setup } — setup must be a function and its return value is
 * invoked as the unload cleanup when truthy (so it must be a cleanup or
 * undefined). Named exports are ignored by the core loader. */
export { isManagementText };

const moduleId = (() => {
  try { return String(import.meta.url || ""); } catch { return ""; }
})();
// Global + project plugin dirs both activate in one process; the registrar
// dies on "Duplicate plugin ID", so give the global copy a distinct id.
const id = moduleId.includes("/.config/opencode/plugins")
  ? "agentguard-global"
  : "agentguard";

export default { id, setup };
