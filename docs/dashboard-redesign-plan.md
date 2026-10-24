# AgentGuard dashboard redesign plan

Status: implemented. The final verification notes are in `docs/dashboard-redesign-verification.md`.

## Direction and intent

Use the taste skill's **Data terminal** direction, seed **627674947**, selected from the two dark app directions it dealt. It suits a security console used for sustained monitoring: a strong event stream, aligned telemetry, compact controls, and a consistent 1px cyan selection line. No redraws were made. The saved direction is `.taste-skill/agentguard/direction.json`.

Keep AgentGuard's AMOLED black ground, near-black surfaces, green live indicators, cyan interaction accents, and JetBrains Mono identity. Keep React, Vite, plain CSS, the three existing workspaces, and the current API contracts.

The product-specific idea: **AgentGuard's prompt, tool, verdict, and breaker events become an inspectable incident trail.** This gives the interface its identity through the security evidence it handles. An incident trail is chronological unless explicit parent IDs or graph edges establish a relationship; proximity alone must never imply causation.

The main question is: **Which agent activity needs my attention, and what evidence explains it?** The event stream remains the largest working area; unresolved approvals and breaker actions stay visible beside it.

## Current findings

Reviewed the current React/CSS source and all three workspaces in the existing browser tab at `http://127.0.0.1:8907/`.

| Finding | Evidence | Planned change |
| --- | --- | --- |
| The header has too many competing elements | Product subtitle, three long workspace tabs, duplicated RAG/MCP counts, session count, uptime, guard status, and mode control share one row | Move workspace navigation to a compact rail; retain product, scope, connection, and mode in the header |
| Text is difficult to scan | Many CSS labels and controls use 8–10px text; the whole interface defaults to 12px mono | Use 13px working text, 12px metadata, 16px section headings, and a 26px page title; no text below 11px |
| Safety actions are separated from their evidence | Breakers are below sessions on the left; approvals are on the right; the event stream is in the middle | Group approvals and breaker exceptions in one attention area beside the stream |
| Secondary tools consume monitoring space | The monitor includes a RAG query form and MCP audit action alongside the main feed | Keep useful status summaries and links on the monitor; provide the complete tools in their existing workspaces |
| Several unknown values look like confirmed data | Header and workspace fallbacks include 8 documents, 16 chunks, 3 servers, 10 tools, and 21 rules; the footer always says READY | Show loading, unknown, stale, disabled, and error states distinctly; render counts only from successful responses |
| The token chart lacks an explicit scale and time labels | `TokenChart` renders proportional CSS bars and hover titles | Draw a compact SVG chart with token units, a zero baseline, and timestamps |
| Advanced workspaces open with implementation explanations | RAG opens with a five-stage pipeline banner; MCP opens with protocol and architecture details | Lead with retrieval or administration tasks; move technical explanations into relevant disclosures |
| Mobile loses important functions | Below 860px both monitor sidebars are `display: none` | Give sessions and attention their own accessible mobile panes |
| Feed state and engine state can disagree visually | The inspected monitor showed DISCONNECTED while the footer showed ENGINE: READY | Report API availability, stream connection, and freshness separately |

The taste source lint reported **18 FAIL and 41 WARN** on the current source. It flagged emoji UI, shadows/glows, broad transitions, and monospace use. Date zero-padding is valid; JetBrains Mono for telemetry, IDs, and code is intentional. Emoji in downloaded Markdown is outside the dashboard UI and should not be removed merely to satisfy a broad source scan.

The automated browser inspector could not connect to port 8907 from its separate process. The visual findings above come from the existing connected browser and source inspection; no responsive inspector score or completed redesign is claimed.

## Theme contract

| Role | Decision |
| --- | --- |
| Ground | Preserve `#000000` |
| Surfaces | Preserve `#050608`, `#090b0f`, and `#0f1218`; use flat fills and subtle existing borders |
| Main text | Preserve `#f3f5f8` and `#dbe0ea` |
| Secondary text | Start with existing `#8c96a8`; lift darker word-bearing greys until they meet 4.5:1 on their actual surface |
| Cyan `#00e5ff` | Selected control lines, links where needed, and the principal chart series |
| Green `#00ff88` | Live/healthy status, used sparingly; ordinary counts remain neutral |
| Amber `#ffaa00` | Pending approval, observation mode, warning, or stale state |
| Red `#ff3355` | Blocked, breached, stopped, or failed facts; one clear signal per object |
| Typography | Keep existing loaded Inter and JetBrains Mono. Inter handles navigation, labels, and explanations; JetBrains Mono handles telemetry, timestamps, identifiers, code, and numeric columns |
| Geometry | 24px workspace gutters and gaps; 16px internal panel padding; 6px panel radius; 34px desktop controls; 42px event rows |
| Selection | One 1px cyan line on the nearest existing edge, with bright text; no filled colored tab treatment |
| Icons | One small outline SVG set, without colored containers; accessible names and tooltips |
| Motion | Brief control feedback and quiet incoming-row feedback; respect reduced motion |

The existing AMOLED ground takes precedence over the dealt style's charcoal ground and darker cards. Keep the brand's surface roles rather than introducing a new dark palette. The green/cyan values stay; reduce their coverage and remove decorative glow from controls and panels. A cyan chart series may use a readable 2px stroke; the 1px rule applies to selection marks.

## Shared shell

Use a 56px navigation rail for the three workspaces, with the existing AG identity at the top. The header retains the AgentGuard wordmark so the product remains recognizable without relying on icon tooltips. Rail destinations are Monitor, Threat RAG, and MCP & policy. Keep the full current names in accessible labels.

Use a 56px header with product name, current scope (`All agents` or the selected session), stream status, and the explicit Observe/Enforce control. Put detailed service health in a popover and version/uptime in a quiet status footer. Use actual service state; an unknown engine or guard must not look healthy.

Each workspace gets one visible `h1`, a short data-driven finding, and its relevant action. Preserve session selection when changing workspaces, but label global data separately: corpus counts, MCP configuration, and the all-session attention queue are not silently filtered by a selected session.

## Live Monitor

Question: **What needs intervention, and what happened around it?**

At 1440px, use this layout:

```text
┌──────┬─────────────────────────────────────────────────────────────┐
│ AG   │ AgentGuard   All agents       Connection       Enforce mode │
│      ├─────────────────────────────────────────────────────────────┤
│ Mon  │ Live Monitor                                                │
│ RAG  │ Finding / freshness, with a relevant Review action           │
│ MCP  ├─────────────────────────────────────────────────────────────┤
│      │ Incident trail: timestamps and security events              │
│      ├──────────────┬────────────────────────────┬─────────────────┤
│      │ Sessions     │ Event stream               │ Attention       │
│      │              │ Search · category filters  │ Approvals       │
│      │ All agents   │ Pause · Export menu        │ Breaker actions │
│      │ Recent / all │                            ├─────────────────┤
│      │ Agent filter │ Time   Agent   Event       │ Firewall        │
│      │ Session rows │       Evidence summary     │ Verdicts/rules  │
│      │              │                            ├─────────────────┤
│      │              │ Select a row to inspect    │ Token usage     │
│      │              │ payload and relationships  ├─────────────────┤
│      │              │                            │ RAG / MCP state │
└──────┴──────────────┴────────────────────────────┴─────────────────┘
```

Grid arithmetic: `56 rail + 48 outer gutters + 248 sessions + 24 gap + 720 stream + 24 gap + 320 context = 1440px`. Above this width the stream absorbs additional space. Below the desktop breakpoint, switch compositions rather than compressing all three columns.

The first 1440×900 screen must show the headers and meaningful content for sessions, stream, attention, firewall, token usage, and RAG/MCP status. Cap attention previews at two rows with a visible View all action; expand the full queue in a drawer. When no action is pending, use one short sentence rather than a tall empty card.

1. **Finding and incident trail.** First surface missing/stale monitoring data, then unresolved approvals and breaker exceptions. If data is current and nothing is pending, say so. Use a small, approximately 48px chronological security strip to locate verdicts and stops in the loaded event window. Selecting a mark filters/highlights its event. Show explicit relationships only where IDs/graph data support them. Omit a large timeline when there is insufficient history.
2. **Sessions.** Keep Recent/All, agent filtering, search, current session status, project/model, counts, and context download. Replace stacks of tiny badges with two readable lines per session. Selecting a session updates the feed and session-scoped evidence; show a visible All agents reset and retain Escape behavior. Describe the current 30-minute activity heuristic as recent activity, rather than implying a verified live process.
3. **Event stream.** Keep all event kinds, search, category filters, pause/resume, raw JSON inspection, and copy. Use aligned timestamp/agent/type columns with most width assigned to the evidence summary. Group dates rather than repeating a long date on every dense row; retain full timestamps in details and accessible text. Keep the first rows visible without a deep toolbar.
4. **Inspection.** A selected event opens a readable detail region with Summary, Payload, and related evidence where available. Keep the originating row visible. On narrow screens, event details become a single pane with a Back control. Missing event fields produce a dash or a plain explanation, never `undefined chars` or an empty iteration number.
5. **Attention.** Combine approvals and nonhealthy breaker snapshots in one section, with separate labeled groups and counts. Preserve Approve/Deny and Reset actions and show their session, reason, metric, value, and limit. Keep all-session coverage explicit when a session is selected. Historical breaker-stop events remain distinguishable from current breaker state.
6. **Exports and utilities.** Replace three adjacent export buttons with one Export menu containing Context Markdown, Context JSON, and Raw events JSON. Retain the current export scope and behavior. Keep Pause visible, and place Clear view in a utility menu with wording that describes its in-memory effect; it does not delete stored telemetry.
7. **Firewall and tokens.** Use a compact verdict breakdown and top triggered rules. Use cyan plus a neutral tone for prompt/completion tokens, with units and time labels. Label the actual windows (`Latest 36 LLM calls`, `Latest 150 verdicts in loaded events`) so summaries are not mistaken for lifetime totals. Chart totals must equal the calls actually plotted.
8. **RAG/MCP summary.** Show compact, real service counts/status and direct links to the existing workspaces. Full retrieval, ingestion, and tool-running forms live there.

## Threat RAG & GraphRAG

Question: **Which threat or policy evidence matches this activity, and how is it connected?**

Lead with `Threat RAG` and one query toolbar. Place search results in the wider left column and lineage/evidence in the right column. At desktop width, the first result or a meaningful empty/error state and the lineage heading must appear immediately.

Use a compact divided corpus strip for documents, chunks, nodes, and edges, sourced from successful status responses. Search controls keep query, category, top-K, presets, and measured query time. Each hit shows title/source, category, excerpt, recommended action, and hybrid score; expose dense and ColBERT details in a disclosure rather than putting every technique name in the heading.

Give lineage a clear list of known paths and a graph only when data exists. Selecting a hit or node exposes its real evidence. Distinguish `No matching paths` from `Lineage unavailable`; zero nodes is not proof that the workspace is safe.

Keep policy ingestion available as an `Add policy` drawer or subview with title, category, action, content, progress, result, and inline failure. Retain the five-stage explanation in an expandable Pipeline section. Move model routing/runtime details into a labeled Runtime subview, distinguishing configured models from verified availability. These are local subviews of the existing workspace, not new backend features.

## MCP & Policy Admin

Question: **Which tools and policies apply, and what configuration needs changing?**

Keep this workspace under the same shell and add local tabs for **Servers**, **Tool runner**, **Session budgets**, and **Firewall rules**. The selected tab's actual work begins on the first screen.

| Subview | Layout and behavior |
| --- | --- |
| Servers | Compact table of built and external servers, transport, tool count, and reported/configured status. A selected server reveals permissions and tool descriptions. Configuration is not presented as proof of connectivity |
| Tool runner | Tool selector and labeled arguments editor beside the result. Retain presets and session context. Show invalid JSON inline and prevent execution until corrected; never silently execute with `{}` after a parse failure |
| Session budgets | Label/description column beside the selected session's current values and limits. Show token, iteration, and USD units; keep Save limits and Reset breaker as separate actions with pending, success, and error feedback |
| Firewall rules | Searchable table with sentence-case headers, a wide identity/description column, and right-aligned weight/confidence. Keep all current rule fields |

Move protocol, transport endpoints, pipeline mechanics, and permission explanations into server details or a Technical details disclosure. Show a tunnel/public-access claim only when a real response supports it; otherwise treat it as documentation rather than runtime state.

## Responsive behavior

| Width | Composition |
| --- | --- |
| 1440px and wider | 56px rail; sessions, stream, context columns; full working toolbar |
| 1101–1439px | Rail plus stream/context; sessions move into a drawer opened from scope. Avoid a narrow three-column squeeze |
| 641–1100px | Compact top navigation; stream is the main pane; attention summary stays above it; sessions and context use drawers/local tabs. RAG columns stack once either would fall below 340px |
| 390–640px | 48px header and three labeled bottom destinations. Monitor has Events, Sessions, and Attention panes. Show pending actions above events. Event rows become two lines; detail opens with Back. Use 16px margins, 14px data text, 12px metadata, and 44px touch targets |

Filters may scroll inside their own row; the page must never scroll horizontally. Tables that require all columns scroll within their frame with identity retained. Scope, filters, selection, and scroll position survive switching between panes.

## States and data rules

- Load labels and layout immediately; use flat placeholders for pending values. Refresh retains last good data and a freshness stamp.
- A successful zero is `0`; unavailable data is a small dash plus a useful status. A failed request never becomes a green empty state.
- Report API availability and WebSocket state separately. REST backfill can remain functional when the stream socket disconnects; do not describe all data as live merely because polling succeeds.
- Preserve the existing reconnect, REST backfill, deduplication, feed buffer, and polling behavior. Add presentation state for last successful fetch and errors as needed.
- Display an error and Retry in the affected block. Search failure, empty results, and a query that has not run are distinct states.
- Derive repeated scope/count/status copy from one value. Label whether numbers describe all sessions, the selected session, loaded events, or a chart's capped window.
- Use semantic buttons for selectable rows, `aria-selected`/`aria-current` where appropriate, associated field labels, visible keyboard focus, and keyboard-operable drawers/menus. Escape closes overlays before clearing the session or leaving a workspace.
- Keep approval, reset, mode, ingestion, and budget API actions intact. Disable a pending action, show success/failure, and avoid showing a state change before the API confirms it.

## Implementation sequence

1. **Foundation and shell.** Consolidate typography, spacing, surface, contrast, and focus tokens in `styles.css`. Build the rail, header, scope control, page titles, and responsive shell in `App.tsx`. Establish desktop and mobile frames before moving data.
2. **Monitor and evidence.** Refactor `Sessions`, `EventFeed`, `Approvals`, and `Breaker` around the layout above. Add the incident trail and inspection region using existing event fields. Consolidate exports and preserve pause/search/filter behavior.
3. **Secondary telemetry.** Rework `TokenChart`, `FirewallDigest`, and compact service summaries. Add actual scales and explicit data windows. Remove fixed success-looking fallback counts.
4. **Advanced workspaces.** Split `ThreatRAGWorkspace` and `MCPAdminWorkspace` into focused components/subviews while preserving their APIs and current actions. Introduce explicit async states and JSON/form validation in the frontend.
5. **Responsive and interaction pass.** Complete all mobile panes, keyboard paths, menu/drawer focus, empty/loading/error views, and freshness behavior.
6. **Verify and compare.** Run the build and taste app checks, inspect screenshots, exercise the existing workflows, and fix the three largest visual issues before repeating the visual check.

Likely component extraction: `AppShell`, `ScopeControl`, `ServiceStatus`, `MonitorWorkspace`, `AttentionQueue`, `IncidentTrail`, `EventInspector`, `ExportMenu`, and separate RAG/MCP subview components. Reuse current components where this produces a smaller change; no new UI framework or chart dependency is required. Changes should stay in the dashboard unless a real missing API field is discovered and separately scoped.

The repository already contains user changes in the dashboard and backend. Implementation must preserve those changes and avoid replacing entire files from an older baseline.

## Acceptance criteria

- The black/green/cyan AgentGuard identity remains recognizable in the first screenshot.
- Within five seconds, a reader can identify scope, connection/freshness, pending intervention, and the event evidence to inspect.
- At 1440×900, each monitor block shows its title and useful content; no long explanatory banner pushes the main job down.
- At 768px and 390px, sessions, approvals, breaker actions, retrieval, and administration remain reachable.
- Missing/failed data never produces fixed corpus/server/rule counts, unconditional READY, or a false all-clear.
- Timestamps and numeric columns align; charts name units and show scales; chart totals reconcile with their displayed rows/window.
- Existing session selection, Escape, search, event categories, pause/resume, copy, exports, approvals, breaker reset, mode switch, RAG retrieval/ingestion, MCP runner, limit saves, and rule filtering still work.
- `npm run build` succeeds. Run the taste app lint and inspector on the implemented version at 1440×900, 768×1024, and 390×844; inspect every resulting screenshot and document any justified warnings.
- Verify empty, zero, loading, partial failure, stale/disconnected, long identifiers, dense event streams, and pending action states with controlled fixtures. Treat fixtures as development data; no invented security or usage claims enter production.

The planning baseline above is retained for comparison. Implementation and final verification are recorded in `docs/dashboard-redesign-verification.md`.
