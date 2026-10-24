# Dashboard redesign verification

The redesign uses the taste skill's Data terminal direction, seed 627674947. No redraws. It retains the AMOLED ground, green/cyan identity, existing fonts, React/Vite stack, and existing API contracts. Its signature is a chronological, selectable incident trail above the event stream. It does not infer causal relationships between unrelated events.

## Implemented

- Compact workspace rail, readable page titles, session scope, service status, and an explicit mode control.
- Sessions / event stream / context desktop composition, with mobile panes that keep sessions and attention reachable.
- Combined approval and breaker attention queue with pending/error feedback and expandable usage details.
- Searchable, keyboard-operable event rows, pause-safe inspection, payload copy, and one export menu retaining all three formats.
- Firewall verdict distribution, expandable top rules, and a token chart with time labels, numeric scale, and two matching legend swatches.
- Search/lineage, policy ingestion, and runtime subviews for Threat RAG; server, runner, budget, and rule subviews for MCP administration.
- Explicit missing, loading, failure, and stale states. Fixed success-looking corpus/server/rule fallbacks and unconditional engine readiness were removed from the active UI.
- MCP JSON validation, current session limit initialization, budget validation, and corrected RAG token-alignment field names.

## Checks

`npm run build` passes. The taste app inspector passes at 1440×900, 768×1024, and 390×844 with zero failures. Screenshots and the machine-readable report are in `.taste-skill/agentguard/after/`.

The source lint on the redesigned components and stylesheet reports zero failures. Its warnings are expected: zero-padding formats dates, monospace is intentional for telemetry/IDs/numbers, dashes represent missing values, and the shadow declaration explicitly removes legacy shadows. Existing unused legacy styling and Markdown export content are outside that focused visual-source lint.

Browser interaction checks used an isolated API and a temporary SQLite database, not the user's stored AgentGuard database. They covered workspace navigation, mobile sessions/attention, session scoping, event search, pause/resume with row inspection, invalid JSON rejection, compliance query results, approval resolution, rule filtering, threat retrieval, and saving a session's token limit. The saved limit was then visible in the session budget table.

All three exporters were also executed against that isolated API. Markdown, processed JSON, and raw JSON produced nonempty output with the selected session ID; JSON event counts reconciled with the API response. The browser's download-event observer timed out, so filesystem delivery was not asserted through that observer; the exporter output and menu invocation were checked independently.

## App-screen critique

1. **Question and hierarchy:** the largest working region is the event stream. The title finding names monitoring availability or pending intervention; the attention queue is adjacent to its evidence.
2. **Edges and density:** the rail, 24px workspace gutters, and three-column grid close across the canvas. Context blocks have content-sized heights; long feeds and session lists scroll in their own regions. The inspector's remaining `unused-canvas` warning is accepted: the actual right context column and service controls occupy the grid edge, while its text-based heuristic stops at a shorter label. The desktop screenshot was checked directly.
3. **Color and identity:** black surfaces, the AG identity, telemetry type, and cyan selection rules remain visible. Color primarily marks live state, interventions, verdicts, and the token series. No decorative panel glows remain in the active UI.
4. **Data agreement:** all displayed verdict counts derive from the same capped event set; token sums derive from the plotted calls. Chart windows, selected-session scope, and the global attention queue are labeled separately.
5. **Zeros and missing values:** successful zeros remain numbers. Missing status is a dash or explicit unavailable/loading copy; an API failure does not manufacture an empty healthy state.
6. **Marks and labels:** token legends match the cyan input and neutral output segments. The chart has a zero baseline, token scale, and first/last timestamps. Raw details retain full precision and identifiers.
7. **Phone composition:** the rail becomes labeled bottom navigation. Events, Sessions, and Attention are separate panes; filters remain within their container; event evidence wraps to two lines and payload details remain available.

All final inspector screenshots were opened and reviewed. RAG/MCP screens were also reviewed in the connected browser, including mobile administration controls.

## Data and scope

Production code contains no generated session or usage fixtures. Synthetic sessions named AgentGuard, security-review, policy-audit, and integrations were used only in the temporary verification server and screenshots. The real built-in threat corpus supplies the preview RAG results. No stock photography or generated image assets were needed.

No backend code or production database was changed by this redesign. Existing user edits were preserved. The implementation uses a dedicated `dashboard/src/redesign.css` layer over the existing stylesheet so unrelated legacy styling remains recoverable.

## Token flow, costs, and Ollama status follow-up

Added a dedicated Usage workspace with hour, day, and available-history ranges; session and model filters; input/output token flow; recorded USD cost over time; and model/session breakdowns. It fetches LLM history independently of the monitor's capped event buffer, refreshes every ten seconds, and preserves previous results on a failed refresh. Its 10,000-call retrieval cap is disclosed when reached. Prices use reported telemetry with six-decimal USD display. Missing prices remain unpriced, and known zero prices remain zero. All breakdowns and plotted intervals share the same filtered call set. Cache counters remain separate from input + output totals.

Llama Guard / Ollama is visible in the desktop header and a dedicated status strip on tablet/phone. It maps the engine signal to Checking, Online, Unreachable, Disabled, or Unknown. Disabled explicitly means guard checks are disabled; it does not assert Ollama is offline.

The production build passes. Focused calculation checks cover ID deduplication, time filtering, token sums, micro-USD rounding, reconciliation between totals/intervals/models/sessions, missing versus zero prices, empty data, and all five guard states. Browser checks at 1440, 768, and 390 pixels cover filter behavior, session drill-down, interval inspection, visible guard status, and absence of page overflow. API interruption also confirmed that usage results remain visible while engine status becomes Unknown. These checks used synthetic telemetry and a temporary database.

The follow-up source lint has zero failures; telemetry monospace and missing-value dashes remain intentional. The automated app inspector checks the default Monitor screen and updated shared navigation/status at all three widths, with zero failures. Its two accepted warnings are the existing text-based unused-canvas heuristic and the centered final phone navigation label's 14px edge distance. All six inspector images were opened and reviewed. Dedicated Usage layouts were checked separately in the browser. Inspector evidence is in `.taste-skill/agentguard/usage-check/`; the final Usage screenshot is `.taste-skill/agentguard/usage-desktop.png`.
