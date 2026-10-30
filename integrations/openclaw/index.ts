/**
 * AgentGuard plugin for OpenClaw.
 *
 * https://github.com/sajib-oss/AgentGuard — local-first security firewall,
 * Threat-RAG/GraphRAG engine, and circuit breaker for agentic tools.
 *
 * This plugin wires OpenClaw's typed lifecycle hooks onto the AgentGuard core
 * service (default http://127.0.0.1:8907):
 *
 *   before_tool_call  -> breaker shield + firewall verdict, mapped to
 *                        OpenClaw's request contract:
 *                          allow    -> (no decision)
 *                          sanitize -> { params: <redacted args> }  (real
 *                                      parameter rewrite, thanks to OpenClaw
 *                                      native rewrites)
 *                          approve  -> { requireApproval: {...} }  (OpenClaw's
 *                                      own approval UI: allow-once/
 *                                      allow-always/deny/timeout)
 *                          block    -> { block: true, blockReason }
 *   after_tool_call   -> tool_call result telemetry ( breaker loop stats)
 *   before_agent_run  -> run admission gate: breaker shield + prompt-level
 *                        firewall check; session tracking
 *   model_call_ended  -> llm_call telemetry (token/cost ledger + iteration
 *                        budget): one llm_call per actual model call with
 *                        usage extracted from the event (shapes vary across
 *                        providers — camelCase, snake_case, provider counts)
 *   session_end       -> session_end event (breaker session finalization)
 *
 * Configure in ~/.openclaw/openclaw.json (see install.sh):
 *
 *   {
 *     "plugins": {
 *       "entries": {
 *         "agentguard": {
 *           "enabled": true,
 *           "hooks": { "allowConversationAccess": true },
 *           "config": { "mode": "enforce" }
 *         }
 *       }
 *     }
 *   }
 *
 * Design note — fail-open: when the local service is unreachable every hook
 * allows by default (same trade-off the OpenCode/Claude/Codex adapters use:
 * availability over protection). All handlers swallow their own errors.
 */

import { createHash } from "node:crypto";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const TRUNCATE = 20_000;
const HTTP_TIMEOUT_MS = 5_000;
const DEFAULT_URL = "http://127.0.0.1:8907";

type AnyDict = Record<string, any>;

function safeStringify(value: unknown): string {
  try {
    return typeof value === "string" ? value : JSON.stringify(value) ?? "";
  } catch {
    return String(value);
  }
}

function digest(text: string): string {
  const h = createHash("sha256").update(text).digest("hex");
  return `${h.slice(0, 12)}${text.length.toString(16)}`;
}

function tryParseJson(text: string | undefined): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export default definePluginEntry({
  id: "agentguard",
  name: "AgentGuard",
  description:
    "Local-first security firewall, circuit-breaker shield, and threat telemetry for every OpenClaw tool call.",
  register(api: any) {
    const cfg = (api.pluginConfig ?? {}) as AnyDict;
    const url = String(cfg.url ?? DEFAULT_URL).replace(/\/+$/, "");
    const enforce = String(cfg.mode ?? "enforce") !== "observe";
    const breakerOn = cfg.breaker !== false;
    const approvalTimeoutMs =
      typeof cfg.approvalTimeoutMs === "number" ? cfg.approvalTimeoutMs : 60_000;

    const seenSessions = new Set<string>();

    async function post(path: string, body: unknown): Promise<AnyDict | undefined> {
      try {
        const res = await fetch(url + path, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
        });
        return (await res.json()) as AnyDict;
      } catch {
        return undefined; // fail-open transport
      }
    }

    async function get(path: string): Promise<AnyDict | undefined> {
      try {
        const res = await fetch(url + path, { signal: AbortSignal.timeout(HTTP_TIMEOUT_MS) });
        return (await res.json()) as AnyDict;
      } catch {
        return undefined;
      }
    }

    function sessionIdOf(ctx: any): string {
      return String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
    }

    async function ensureSession(sid: string, agentName: string): Promise<void> {
      if (seenSessions.has(sid)) return;
      seenSessions.add(sid);
      await post("/v1/events", {
        events: [{ agent: agentName, session_id: sid, type: "session_start", data: {} }],
      });
    }

    function isManagementTraffic(serialized: string): boolean {
      // Management escape hatch: AgentGuard self-management must stay possible
      // even while an open circuit would otherwise lock the tool gate.
      return (
        serialized.includes("/v1/breaker") ||
        serialized.includes("/v1/approvals") ||
        serialized.includes("/v1/config")
      );
    }

    async function breakerStatus(sid: string): Promise<string | undefined> {
      if (!breakerOn) return undefined;
      const st = await get(`/v1/breaker/status/${encodeURIComponent(sid)}`);
      if (st && (st.status === "breached" || st.status === "stopped")) {
        return String(st.status);
      }
      return undefined;
    }

    async function emit(sid: string, type: string, data: AnyDict): Promise<void> {
      await post("/v1/events", { events: [{ agent: "openclaw", session_id: sid, type, data }] });
    }

    api.on("before_tool_call", async (event: any, ctx: any) => {
      const sid = sessionIdOf(ctx);
      try {
        await ensureSession(sid, "openclaw");
        const tool = String(event?.toolName ?? "unknown");
        const params = (event?.params ?? {}) as AnyDict;
        const serialized = safeStringify(params);
        const mgmt = isManagementTraffic(serialized);

        const openStatus = await breakerStatus(sid);
        if (openStatus && !mgmt) {
          return {
            block: true,
            blockReason:
              `agentguard: tool call blocked — circuit breaker ${openStatus} ` +
              "(approve/reset in AgentGuard, then continue)",
          };
        }

        await emit(sid, "tool_call", {
          name: tool,
          args_digest: digest(serialized),
          args_preview: serialized.slice(0, 240),
          status: "started",
        });

        const verdict = await post("/v1/firewall/check", {
          text: serialized.slice(0, TRUNCATE),
          session_id: sid,
          agent: "openclaw",
          context_type: "tool_input",
        });
        const action = String(verdict?.action ?? "allow");

        if (action === "sanitize") {
          const redacted = tryParseJson(String(verdict?.sanitized_text ?? ""));
          if (redacted && typeof redacted === "object" && !Array.isArray(redacted)) {
            if (JSON.stringify(redacted) !== JSON.stringify(params)) {
              return { params: redacted as AnyDict };
            }
            return undefined;
          }
          if (enforce) {
            return {
              block: true,
              blockReason:
                `agentguard: tool args contain secret material ` +
                `(${verdict?.redaction_count ?? 0} redaction(s)); resubmit without secrets`,
            };
          }
          return undefined;
        }

        if (!enforce) return undefined;

        if (action === "approve") {
          // Surface OpenClaw's own approval machinery; the operator can also
          // watch the AgentGuard dashboard live feed for the verdict events.
          return {
            requireApproval: {
              title: "AgentGuard approval",
              description:
                String(verdict?.decision_reason ?? "AgentGuard requested approval") +
                " — approve in AgentGuard-compatible chat or deny.",
              severity: "warning",
              timeoutMs: approvalTimeoutMs,
            },
          };
        }
        if (action === "block") {
          return {
            block: true,
            blockReason: `agentguard: tool call blocked by firewall — ${verdict?.decision_reason ?? "policy violation"}`,
          };
        }
        return undefined; // allow
      } catch {
        return undefined; // fail-open: never wedge the gateway
      }
    });

    api.on("after_tool_call", async (event: any, ctx: any) => {
      try {
        const sid = sessionIdOf(ctx);
        const err = typeof event?.error === "string" ? event.error : "";
        let preview = "";
        if (event?.result !== undefined) {
          preview = safeStringify(event.result);
        }
        await emit(sid, "tool_call", {
          name: String(event?.toolName ?? "unknown"),
          status: err ? "error" : "success",
          result_preview: (err && `error: ${err}`) || preview.slice(0, 240),
          duration_ms: event?.durationMs ?? undefined,
        });
      } catch {
        /* observation only; ignore */
      }
    });

    api.on("before_agent_run", async (event: any, ctx: any) => {
      try {
        const sid = sessionIdOf(ctx);
        await ensureSession(sid, "openclaw");

        const openStatus = await breakerStatus(sid);
        if (openStatus && enforce) {
          return {
            outcome: "block",
            reason:
              `agentguard: run blocked — circuit breaker ${openStatus} ` +
              "(approve/reset in AgentGuard, then re-send)",
          };
        }

        // Note: llm_call telemetry is emitted from model_call_ended (one event
        // per actual model call, carrying usage) — not here, which would
        // double-count runs vs calls.

        // Prompt-level gate: only when the event carries the prepared prompt
        // text and the runtime exposes it.
        const prompt =
          typeof event?.prompt === "string"
            ? event.prompt
            : typeof event?.text === "string"
              ? event.text
              : undefined;
        if (enforce && prompt && prompt.trim()) {
          const verdict = await post("/v1/firewall/check", {
            text: prompt.slice(0, TRUNCATE),
            session_id: sid,
            agent: "openclaw",
            context_type: "prompt",
          });
          if (verdict?.action === "block") {
            return {
              outcome: "block",
              message: `agentguard: prompt blocked by firewall — ${verdict.decision_reason ?? "policy violation"}`,
            };
          }
        }
        return undefined;
      } catch {
        return undefined;
      }
    });

    api.on("session_end", async (event: any, ctx: any) => {
      try {
        const sid = sessionIdOf(ctx);
        await emit(sid, "session_end", {});
      } catch {
        /* ignore */
      }
    });

    // Token & cost ledger: one llm_call event per actual model call. Event
    // shapes vary across providers and OpenClaw versions, so extraction is
    // permissive (camelCase, snake_case, provider-style counts, nested
    // usage/tokens objects) and silently skips when nothing usable exists.
    const num = (v: unknown): number | undefined => {
      const n = typeof v === "string" ? Number(v) : (v as number);
      return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : undefined;
    };

    // Cache counts sometimes nest one level under the usage dict (e.g.
    // OpenAI-style prompt_tokens_details.cached_tokens) — probe child dicts.
    const CACHE_READ_KEYS = [
      "cache_read", "cache_read_tokens", "cacheReadTokens", "cached_tokens",
      "cachedContentTokenCount", "cache_read_input_tokens",
    ];
    const CACHE_WRITE_KEYS = [
      "cache_write", "cache_write_tokens", "cacheWriteTokens",
      "cache_creation_tokens", "cache_creation_input_tokens",
    ];

    function probeNestedCache(node: AnyDict, keys: string[]): number {
      for (const key of Object.keys(node).slice(0, 32)) {
        const child = node[key];
        if (child && typeof child === "object" && !Array.isArray(child)) {
          for (const k of keys) {
            const v = num(child[k]);
            if (v !== undefined) return Math.round(v);
          }
        }
      }
      return 0;
    }

    function extractUsage(node: any, depth = 0): AnyDict | undefined {
      if (!node || typeof node !== "object" || depth > 6) return undefined;
      const input =
        num(node.input) ?? num(node.input_tokens) ?? num(node.inputTokens) ??
        num(node.prompt_tokens) ?? num(node.promptTokens) ?? num(node.promptTokenCount) ??
        num(node.messages_input_tokens) ?? num(node.text_input_tokens);
      const output =
        num(node.output) ?? num(node.output_tokens) ?? num(node.outputTokens) ??
        num(node.completion_tokens) ?? num(node.completionTokens) ?? num(node.candidatesTokenCount);
      if ((input ?? 0) + (output ?? 0) > 0) {
        return {
          input_tokens: Math.round(input ?? 0),
          output_tokens: Math.round(output ?? 0),
          cache_read_tokens:
            Math.round(
              num(node.cache_read) ?? num(node.cache_read_tokens) ?? num(node.cacheReadTokens) ??
              num(node.cached_tokens) ?? num(node.cachedContentTokenCount) ?? 0,
            ) || probeNestedCache(node, CACHE_READ_KEYS),
          cache_write_tokens:
            Math.round(
              num(node.cache_write) ?? num(node.cache_write_tokens) ?? num(node.cacheWriteTokens) ??
              num(node.cache_creation_tokens) ?? num(node.cache_creation_input_tokens) ?? 0,
            ) || probeNestedCache(node, CACHE_WRITE_KEYS),
          cost_usd: num(node.cost) ?? num(node.costUsd) ?? num(node.cost_usd),
          // provider-side extras ride along when present (breaker summaries)
          duration_ms: num(node.durationMs) ?? num(node.duration_ms) ??
            num(node.latencyMs) ?? num(node.elapsedMs),
        };
      }
      for (const key of Object.keys(node)) {
        const child = node[key];
        if (child && typeof child === "object") {
          const found = extractUsage(child, depth + 1);
          if (found) return found;
        }
      }
      return undefined;
    }

    api.on("model_call_ended", async (event: any, ctx: any) => {
      try {
        const sid = sessionIdOf(ctx);
        const usage = extractUsage(event);
        if (!usage) return undefined; // no usage disclosed: do not emit a wrong event
        const model =
          (typeof event?.model === "string" && event.model) ||
          (typeof event?.modelRef === "string" && event.modelRef) ||
          (typeof event?.modelId === "string" && event.modelId) ||
          (typeof ctx?.model === "string" && ctx.model) ||
          undefined;
        await emit(sid, "llm_call", {
          ...usage,
          model,
          run_id: typeof event?.runId === "string" ? event.runId : undefined,
        });
        return undefined;
      } catch {
        return undefined;
      }
    });
  },
});
