# Submission Kit — RannaIQ (fill-ready)

## 1. Form fields (with character-count safe draft answers)

Every notes field must clear its minimum (auto-scorer checks). Drafts below are all ≥120 chars — trim but never under.

| Field | Min | Draft answer |
|---|---|---|
| Title | — | RannaIQ — Voice Procurement Copilot for Restaurants |
| Tagline | — | Reads every customer review and every seasonal pattern, then tells restaurant managers exactly what to buy, in kilograms, before prices rise. |
| Prompt Strategy (5) | — | *Write after code exists; explain:* single master prompt with 8 mandated modules executed sequentially with approval checkpoints; layered system prompts (router → per-agent persona → tool contracts); chain-of-thought enforced via structured ReAct state in LangGraph; JSON-schema tool contracts eliminate malformed calls. **(Aim 800+ chars, quote fragments of the actual prompt.)** |
| Token Optimization (3) | ≥50 | OpenAI prompt caching for system+retrieved context, semantic cache in pgvector for repeated questions, context pruning (reviews >30 days summarized), tiered model routing: GPT-4o only for synthesis, GPT-4o-mini for classification/context-writing, Ollama 7–9B local models for summaries and cheap chains. |
| AI-DLC (3-4) | ≥100 | Spec-Kit spec→plan→tasks flow captured in /specs, BMAD-METHOD agents for planning docs, Cursor Rules committed in .cursor/rules for generation discipline; the whole product was initialized from ONE master prompt per Zero-to-Launch rules, with 8 modules gated by approval checkpoints. |
| Agent / Orchestration (2) | ≥80 | LangGraph state machine orchestrates: intent router → retrieval (contextual RAG) → GraphRAG traversal → inventory MCP → forecast tool → synthesis + TTS. OpenAI Agents SDK executes MCP tool calls; CrewAI pair acts as second-opinion judges during evaluation. Full traces in Langfuse. |
| Fine-tuning (2) | ≥80 | Fine-tuned GPT-4o-mini on 1,000 labeled Banglish/English review facets (synthetic + hand-labeled) for aspect extraction; LoRA adapter on Qwen2.5-1.5B as the local fallback classifier; dataset curated via dedupe hash and stratified facet-balanced split. |
| Evaluation & Quality (3) | ≥80 | Sentiment F1 on a 200-review labeled set, retrieval hit@10 and nDCG over 60 QA pairs, forecast MAPE vs. seeded ground truth, and LLM-as-judge (GPT-4o + 5-point fixed rubric, cross-checked by a CrewAI reviewer pair) scoring 50 generated recommendations against human baselines. |
| Guardrails / Safety (3) | ≥80 | Input: PII redaction (Presidio-style + regex) on reviews before ingestion, delimiter + canary-token prompt-injection wrapping for review text, schema-validated tool args. Output: JSON schema enforcement, quantity sanity bands, refusal on out-of-scope asks. Rate limiting per user; JWT + RBAC. |
| Tunneling (2) | ≥80 | Cloudflare Tunnel exposes the local Ollama inference node as a Streamable-HTTP/SSE MCP endpoint so the cloud backend reaches on-prem model reasoning; ngrok configured as documented backup; configs live in deploy/tunnel/. |
| Data Quality (2) | ≥80 | Content-hash + fuzzy dedupe on reviews, language detection (Bangla/Banglish/English), unit normalization for kg/L/dzn, Pydantic schema enforcement on every ingest row, 3% manual audit sample per batch, and seasonal-index outliers >4σ flagged for review. |
| Privacy & Compliance (2-3) | ≥80 | No PII is ever sent to LLMs — redaction happens pre-embedding; reviews stored as faceted aggregates; demo data is synthetic; Postgres role separation (read-only MCP role), TLS everywhere, AES-256 at rest for price data; audit_log provides full traceability and a monthly compliance summary export. |
| Lineage & Observability (2) | ≥80 | Every agent run emits a Langfuse trace (retrie ids, scores, tokens, latency); audit_log + token_ledger tables give request-level lineage; Airflow runs tag sources and dataset versions; Langfuse public session link submitted for judge verification. |

## 2. Other links (3 pts) — candidates
1. Public Langfuse trace session (of a real end-to-end run)
2. Demo dataset / interactive evaluation scorecard notebook
3. docs site (GitHub Pages of ARCHITECTURE + DATA_PIPELINE)

## 3. Access Note
> "Judge account: manager@rannaiq.demo / rannaiq (pre-seeded 2-branch Dhaka restaurant, 14 days of history). Open dashboard → press the mic → try 'What should I order for Friday?'. PO approval is simulated and n8n dispatch logs to the test channel."

## 4. YouTube video — 10 pts (script, 2:30)

| Time | Shot | Narration |
|---|---|---|
| 0:00–0:15 | Dashboard loads, Tuhin's two branches | "RannaIQ reads every review and every season — and tells a restaurant manager exactly what to buy." |
| 0:15–0:45 | Press mic, ask "What should I order for Friday?" (Whisper STT shown) | "A voice question kicks off a LangGraph agent: contextual RAG over 600 reviews…" |
| 0:45–1:20 | Show reasoning panel: sentiment facets w/ citations → GraphRAG path → inventory MCP numbers | "…complaint facets, an ingredient-season knowledge graph, and live stock through three custom MCP servers." |
| 1:20–1:45 | Recommendation card: 42 kg Hilsa / 120 kg chicken / 15 kg onion, confidence + citations; TTS reads it aloud | "Quantities, not vibes — with math shown: velocity × seasonal index × sentiment urgency − stock." |
| 1:45–2:10 | Approve PO → n8n email screenshot; weekly report; charts | "Approval dispatches the PO via n8n; Airflow re-forecasts nightly." |
| 2:10–2:30 | Architecture slide + trace in Langfuse + GitHub | "Open source, fully traced, local models included — RannaIQ." |

**Audio rule:** record voiceover separately; judge criteria explicitly mention crisp audio.

## 5. GitHub repo requirements (2 pts + credibility)
- README: hero GIF of the voice demo, one-command setup, seeded login (Access Note echo), tech-stack table matching all claimed rubric checkboxes, docs links
- `/docs`: ARCHITECTURE, DATA_PIPELINE, EVALS, MCP, ADR, PITCH
- `.cursor/rules` committed (AI-DLC point), `/specs` folder (Spec-Kit artifacts), badges: CI, license

## 6. Character-count audit helper

```bash
# run before submitting; every row must pass
node -e '
const min = { "Token Optimization": 50, "AI-DLC": 100, "Agent": 80, "Fine-tuning": 80, "Evaluation": 80, "Guardrails": 80, "Tunneling": 80, "Data Quality": 80, "Privacy": 80, "Lineage": 80 };
'  # final script: read answers.json, assert lengths, exit non-zero on failure
```

## 7. Pre-submission final order (Oct 30–31)
1. Team registration 5/5 + NRB + female (×7 pts)
2. Upload video → verify it plays logged-out
3. Deploy → hit every page logged-in as judge account
4. Fill form → run char audit → paste → submit
5. Screenshot every field for the record
