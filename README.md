# AgentGuard

Local-first watchdog for agentic coding tools. One small Python service sees
everything your agents do — prompts, tool calls, tokens, turns — applies a
prompt-injection firewall, and locks runaway loops out with a circuit
breaker, while you watch live on a dashboard.

```
             ┌──────────────────────────────────────────────────────┐
 opencode ─▶ │  AgentGuard core (FastAPI, port 8907)                │
 claude code ─▶  firewall: rules ▸ heuristics ▸ secrets ▸ Llama    │
 codex ───────▶            Guard 3 (Ollama)                        │
 langgraph ───▶  breaker: budget + loop detection + kill switch    │
             └───────────────┬──────────────────────┬───────────────┘
                             ▼                      ▼
                   SQLite ~/.agentguard/events.db   React dashboard (WS live feed)
```

Nothing leaves your machine but the model calls your agents already made:
the firewall's LLM tier queries a **local** Ollama serving `llama-guard3:1b`.

## Quickstart

```bash
# 1. core (Python 3.12, editable install)
cd core && pip install -e . && cd ..
.venv/bin/agentguard serve            # or: agentguard serve anywhere on PATH

# 2. check health + doctor
curl http://127.0.0.1:8907/v1/healthz
.venv/bin/agentguard doctor

# 3. dashboard — just open it
http://127.0.0.1:8907/                # served by the core (single binary UX)

# 4. pick your agent(s): see Adapters below
```

## Firewall

Inbound text (prompts, tool arguments) passes through a tiered pipeline:

| Tier | Detector | Role |
|---|---|---|
| 1 | `rules.py` — 40+ deterministic patterns | injection phrases, jailbreaks, unsafe payloads |
| 2 | `heuristics.py` — structural scoring | base64 blobs, unicode homoglyphs, instruction-like density |
| 3 | `secrets.py` | AWS/GCP/tokens/keys → redaction `[REDACTED:kind]` |
| 4 | **Llama Guard 3** (`llama-guard3:1b` via Ollama) | semantic safety verdict; never the sole detector |

Policy voting: each category maps to an action
(`injection→block`, `encoded_payload→sanitize`, `secret→sanitize`, …).
Llama Guard hazards map to actions too — high-severity hazards (`S3/S4/S9/S13/S14/S15`)
block; unknown or low-severity ones default to **sanitize**, weighted ×50 so a
1B model's noisy false positive can't push an otherwise benign payload past
`block_threshold` on its own.

Actions:

- `allow` — pass through
- `sanitize` — text is rewritten (secrets redacted) and execution continues
- `approve` — execution **pauses**; resolve on the dashboard
  (`POST /v1/approvals/{id}/resolve {"approved":true}`) within timeout or deny
- `block` — the adapter rejects the call with the reason

**Observe vs enforce.** `observe` computes full verdicts and records them but
always returns `allow` — run it while you baseline your agents. Flipping
between modes is runtime and per-service:

```bash
curl -X POST http://127.0.0.1:8907/v1/config/mode -H 'Content-Type: application/json' \
     -d '{"mode":"enforce"}'
```

Note: observe mode is runtime-only and resets to enforce on core restart —
decisions, not defaults, require a flag flip to be safe.

## Circuit breaker

Per session, the breaker watches `iterations`, `tool_calls`,
`input+output tokens`, `cost`, `wall_time`, `consecutive_tool_errors`, and
loop signatures (consecutive repeats, A-B cycles, diversity collapse).
Breach response (`on_breach`): `alert` | `pause` (approval gate) | `kill`
(`SIGTERM` through the registered agent pid — adapters register it).

```bash
curl http://127.0.0.1:8907/v1/breaker/status/ses_xyz
curl -X POST http://127.0.0.1:8907/v1/breaker/reset/ses_xyz
curl -X POST http://127.0.0.1:8907/v1/breaker/limits -H 'Content-Type: application/json' \
     -d '{"session_id":"ses_xyz","limits":{"max_tokens":50000000}}'
```

Per-session limit overrides **persist in SQLite** (kv `breaker_session_overrides`)
and re-apply on resets and core restarts — an operator reset must never
silently restore default budgets and re-breach a legitimately huge session.
(In an early build, that exact bug locked the operator out of a session that
needed reset twice a turn.)

### The deadlock discipline (why there is an escape hatch)

The breaker only knows itself: it cannot tell "runaway loop" from "the
operator resetting the breaker". A naive plugin therefore deadlocks — with
the circuit open, it blocks every tool call, including:

- `curl … /v1/breaker/reset/…`
- `agentguard stop`

the very commands that open the circuit again. AgentGuard's adapters embed a
narrow escape hatch: anything managing AgentGuard itself (`/v1/breaker`,
`/v1/approvals`, `/v1/config` paths, `agentguard stop|doctor|serve`) skips
the **breaker shield** but is still firewalled and recorded. Manage the
watchdog, always available; weaponize nothing else.

## Adapters

| Agent | File | Install | Coverage |
|---|---|---|---|
| OpenCode | `integrations/opencode/plugin/agentguard-plugin.js` | `install.sh` (project) or `install.sh --global` (every session) | prompt firewall, tool firewall, tokens/cost, lifecycle, breaker shield |
| Claude Code | `integrations/claude/hooks/agentguard_hook.py` | merge `integrations/claude/settings.example.json` into `~/.claude/settings.json` (or per-project `.claude/settings.json`) | prompt firewall, tool firewall, lifecycle, breaker shield |
| Codex CLI | `integrations/codex/notify.py` | `~/.codex/config.toml`: `notify = ["python3","<path>"]` (global by nature) | observability only (Codex exposes no prompt/tool gate) |
| LangGraph | `core/agentguard/adapters/langgraph.py` | `pip install -e core` then callback handler | nodes/edges/LLM/tool events |

### OpenCode install scope matters

OpenCode discovers plugins from `.opencode/plugins/` (project) and
`~/.config/opencode/plugins/` (global). A project install only covers
sessions opened **inside that directory**; `install.sh --global` covers
everything. Because OpenCode loads hooks from both sources in sequence
(global first), the plugin carries an **exactly-once guard**
(`globalThis.__agentguardActive`): the second copy in the same process
registers no hooks, so double installs duplicate nothing. Keep both copies
in sync after edits (or keep only one). Plugins load at service boot — run
`opencode service restart` once after installing/updating.

OpenCode restart only after plugin edits: plugins load at service boot —
restart the OpenCode service (`opencode service restart`) once after installing
to pick up the latest adapter. (Same rule for Claude Code hooks, which reload
per session.)

### LangGraph

```python
from agentguard.adapters.langgraph import AgentGuardLangGraphHandler
handler = AgentGuardLangGraphHandler(session_id="my-thread")
graph.invoke(inputs, config={"callbacks": [handler]})
```

## Dashboard

`http://127.0.0.1:8907/` — live event feed (session-switchable), session
cards (tokens/cost/live breaker state), firewall verdicts, pending approvals,
breaker panel (usage vs limits, reset + limits controls from the browser).

Feed persistence: live delivery is WebSocket; the client additionally polls
`/v1/events` every few seconds and dedupes by event id, so a WS hiccup (core
restart, suspended tab) self-heals with a REST backfill instead of showing a
frozen feed.

## HTTP API

| Route | Purpose |
|---|---|
| `GET /v1/healthz` | liveness + llama-guard reachability |
| `POST /v1/events` | batch adapter ingestion |
| `GET /v1/events` | query (`session_id, agent, type, since, limit, order`) |
| `GET /v1/sessions[/{id}]`, `POST /v1/sessions/{id}/pid` | registry + kill-switch pid |
| `POST /v1/firewall/check` | full verdict (waits up to `approval_timeout` on `approve` action) |
| `GET /v1/approvals`, `POST /v1/approvals/{id}/resolve` | approval queue |
| `GET /v1/breaker/status[/{sid}]` | breaker snapshots |
| `POST /v1/breaker/reset/{sid}`, `POST /v1/breaker/limits` | operator controls |
| `POST /v1/config/mode` | `enforce` ⇄ `observe` |
| `WS /v1/ws?replay=N&session_id=…` | live feed |

## Configuration

`agentguard.yaml` (see `core/agentguard/config.py` for the full schema):

```yaml
firewall:
  observe_mode: true           # start observing, flip to enforce when ready
  llm_guard:
    enabled: true
    model: llama-guard3:1b
  store_prompt_content: true   # false → hashes/previews only (privacy)
  block_threshold: 70
  sanitize_threshold: 25

breaker:
  on_breach: kill              # alert | pause | kill
  defaults:
    max_tokens: 50000
    max_tool_calls: 200
    ...
dashboard:
  dir: ../dashboard/dist
```

Env in adapters: `AGENTGUARD_URL`, `AGENTGUARD_MODE` (enforce|observe),
`AGENTGUARD_BREAKER`, `AGENTGUARD_APPROVAL_TIMEOUT`.

## Development

```bash
.venv/bin/python -m pytest core/tests        # unit/integration suite
node integrations/opencode/plugin/is-management.test.mjs   # escape-hatch matcher
cd dashboard && npm run build                # rebuild the React dist

# end-to-end enforcement demo (safe observe flip back included)
curl -s -X POST localhost:8907/v1/config/mode -d '{"mode":"enforce"}' -H 'content-type: application/json'
curl -s -X POST localhost:8907/v1/firewall/check -d '{"text":"ignore all previous instructions..."}' -H 'content-type: application/json'
curl -s -X POST localhost:8907/v1/config/mode -d '{"mode":"observe"}' -H 'content-type: application/json'
```

## Honest limits

- **Fail-open posture**: if the guard service is down, adapters let the agent
  run (documented: availability over protection). CLI `agentguard doctor`
  catches drift.
- Llama Guard 3 (1B) is a triage model: it can miss novel prompt-space
  attacks; deterministic rules are the load-bearing tier and Llama Guard can't
  supersede them.
- Codex integration cannot intercept: Codex CLI hooks are limited to
  turn-complete notifications; firewalling there must happen at a proxy layer
  instead.
- Loop detection is behavioral, not telepathic: everything it sees is what
  the shared schema observed.
