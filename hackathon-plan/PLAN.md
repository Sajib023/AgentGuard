# RannaIQ — Master Plan for International AI Builders Congress 2026 (CloudCamp BD)

> **Goal:** maximum auto-score + judge score for a RAG-based assistant for restaurant managers that analyzes customer review sentiment and seasonal trends to recommend precise ingredient purchase quantities.
> **Track:** Idea to Unicorn / Zero to Launch. **Deadline:** Oct 31, 2026, 11:59 PM GMT+6.

---

## 1. Product Concept (score-optimized)

**Name:** RannaIQ (Bengali "ranna" = cooking) — fallback names: StockSense, PantryPilot.
**Tagline:** *"The voice copilot that reads every review and every season — and tells you exactly what to buy, in kilograms, before prices climb."*

**Demo persona:** *Tuhin Bhai* — owner-manager of a 2-branch Dhaka restaurant chain (Mirpur + Banani). 60% English, 40% Bangla/Banglish reviews on Google Maps.

**Core loop (this is the 3-minute demo arc):**
1. Tuhin opens the dashboard and **speaks**: "Aila, what should I order for Friday's fish?"
2. **STT** (OpenAI Whisper) transcribes → LangGraph agent routes intent.
3. Agent calls **RAG tools**: sentiment facets over recent reviews ("re-fried fish smells fishy — 4 complaints this month") + **GraphRAG** on ingredient↔dish↔season graph (monsoon = delivery slippage, Eid spike in 12 days).
4. Agent checks **live inventory via MCP** → computes **precise quantity**: "Order 42 kg Hilsa, 120 kg chicken thigh, 15 kg onion before Thursday; onion futures rising 18% w/w."
5. **TTS** (OpenAI TTS) reads the recommendation aloud.
6. Tuhin taps **Approve PO** → n8n emails/WhatsApp's the purchase order to suppliers + logs it.

**Bangladesh-specific wedge (judges love this):** monsoon-driven supply slippage, Eid/seasonal spikes, Banglish review parsing, wholesale price volatility.

---

## 2. Exact Score Map (rubric → what we build/claim)

Auto-scored buckets from the CloudCamp knowledge base:

### 2.1 Links & Deliverables — 15/15
| Item | Pts | Plan |
|---|---|---|
| YouTube video | 10 | 2–3 min crisp demo (script in SUBMISSION_KIT.md) |
| GitHub repo | 2 | Public, killer README + one-command seed |
| Live demo URL | 1 | Deployed via Render/Vercel + Cloudflare Tunnel |
| Figma link | 1 | Dashboard mockups + system architecture diagram |
| Other links ×3 | 3 | (1) Public Langfuse trace session, (2) demo dataset, (3) DOCUMENTATION site/wiki |

### 2.2 Team Diversity — 7/7
5 registered members (5 pts) + 1 NRB member (+1) + 1 female member (+1). **Register all 5 ASAP — it's the cheapest 7 points in the rubric.**

### 2.3 AI Stack, RAG & Models — target 110+/110+

| Category | Claim | How we earn it honestly |
|---|---|---|
| LLM selection | 5 | OpenAI GPT-4o (synthesis), GPT-4o-mini (classification), whisper-1 (STT), tts-1 (TTS) |
| RAG techniques (max 5) | 5 | Naive RAG baseline, Vector DB (**pgvector**), **Contextual RAG** (Anthropic-style), **Semantic chunking**, **GraphRAG**; bonus tea-fine: ColBERT-style late-interaction rerank |
| Contextual RAG bonus | 5 | Every chunk gets an LLM-generated context prefix baked in at ingest |
| Semantic chunking bonus | 3 | Sentence-boundary + cosine-similarity chunking (no fixed token windows) |
| Contextual + chunking combo bonus | 3 | Same ingest pipeline combines both |
| GraphRAG bonus | 5 | Ingredient↔Dish↔Supplier↔Season knowledge graph in Postgres, multi-hop traversal tool |
| Frontend AI tools (max 5) | 5 | v0 (dashboard scaffold), Cursor (codebase), Claude Artifacts (pitch deck/slides), Lovable (mobile view), Gemini Canvas (infographics) — use each once for real |
| Automation tools (max 4) | 3-4 | **n8n** (ingestion + PO email/WhatsApp), **LangGraph**, Airflow (nightly forecast pipeline) |
| n8n specific bonus | 2 | n8n is load-bearing: review ingestion workflow + PO dispatch + weekly report email |
| LLM runtimes (max 3) | 2-3 | **Ollama** (primary), LM Studio (dev bench) |
| Ollama bonus | 2 | Local inference node exposed via Cloudflare Tunnel as an SSE MCP server |
| Local models run (2 each, max 8) | 8 | **Qwen2.5-7B** (seasonal summaries), **Llama 3.1-8B** (sentiment fallback), **DeepSeek-R1-8B** (forecast chain-of-thought), **GLM-4-9B** (review aspect extraction) — each actually used in a subtask; document quantization + hardware |
| Agent frameworks (max 5) | 3-5 | **LangGraph** (orchestrator), **OpenAI Agents SDK** (MCP tool-calling), CrewAI (eval-judge crew); optional AutoGen |
| AI-DLC frameworks (max 3) | 3 | **Spec-Kit** (spec-driven spec→plan→tasks), **BMAD-METHOD** (planning agents), **Cursor Rules** (.cursor/rules committed) |
| MCP built (max 3) | 3 | `inventory-mcp`, `review-mcp`, `forecast-mcp` (custom servers, below) |
| MCP used (max 3) | 3 | official `postgres-mcp`, `fetch-mcp` (Open-Meteo weather), `filesystem-mcp` (PO/PDF export) |
| MCP architecture | 6 | Full disclosure: **stdio** (local) + **SSE/Streamable HTTP** (remote via tunnel); host = FastAPI/LangGraph app; clients = OpenAI Agents SDK MCP client; permission boundaries = read-only Postgres role |
| Tunneling | 4 | **Cloudflare Tunnel** exposes the local Ollama MCP node + demo; ngrok documented as backup |
| **Bucket total** | **~110-118** | |

### 2.4 Submission text fields — ~29 pts
Every field has a char minimum (auto-checked). Pre-drafted ≥120-char answers in **SUBMISSION_KIT.md**: Prompt Strategy (5), Token Optimization ≥50 (3), AI-DLC ≥100 (3-4), Agent notes ≥80 (2), Fine-tuning ≥80 (2), Evaluation ≥80 (3), Guardrails ≥80 (3), Tunneling notes ≥80 (2), Data quality ≥80 (2), Privacy/compliance ≥80 (2-3), Lineage/observability ≥80 (2).

### 2.5 Data Lifecycle & Pipelines — 25/25
Document end-to-end in `docs/DATA_PIPELINE.md` (all 5 stages, named tools):
1. **Sources:** POS CSV export (sample), Google-Maps-style reviews dataset (synthetic Banglish + Yelp Open Dataset subset), Open-Meteo weather API.
2. **Parse:** JSON/CSV parsers, language detection, TSV→Postgres loaders.
3. **Clean/enrich:** dedupe by hash + fuzzy match, PII redaction, sentiment facets, ingredient entity-linking, seasonal index computation.
4. **Store:** PostgreSQL (transactional) + **pgvector** (embeddings) + KG tables + MinIO/S3 (raw JSON).
5. **Deliver:** React dashboard, n8n weekly PDF email, webhook → WhatsApp, REST API.

### 2.6 Estimated total — **~190+ pts available**

---

## 3. Architecture

```
                       ┌──────────────────────────────┐
   🎙 Manager voice ──▶ │ Next.js Dashboard (v0-built) │──▶ OpenAI TTS 🔊
   ⌨ and text chat      │  (Vercel)                    │
                       └──────────────┬───────────────┘
                                      │ REST/SSE
                       ┌──────────────▼───────────────┐
                       │ FastAPI Backend (Render)     │
                       │  LangGraph Orchestrator      │
                       │  OpenAI Agents SDK (tools)   │
                       └──┬──────┬─────────┬──────────┘
          MCP (stdio)     │      │ MCP(SSE)│        MCP (stdio)
        ┌─────────────────▼┐  ┌──▼─────────▼───┐  ┌────▼──────────────┐
        │ BUILT:           │  │ BUILT:         │  │ BUILT:            │
        │ inventory-mcp    │  │ review-mcp     │  │ forecast-mcp      │
        └───────┬──────────┘  └───────┬────────┘  └────┬──────────────┘
                │                     │                 │
        ┌───────▼─────────────────────▼─────────────────▼──────┐
        │ PostgreSQL (+pgvector) │ Knowledge Graph tables       │
        │ (Render)               │ MinIO object store           │
        └───────────────────────────────────────────────────────┘
                ▲                     ▲                  ▲
         USED: postgres-mcp    USED: fetch-mcp     Ollama node (local PC)
         (external)            (Open-Meteo)        Qwen2.5/Llama3.1/DeepSeek-R1/GLM-4
                                                   exposed via Cloudflare Tunnel (SSE)
        n8n (cloud): ingestion workflow · PO dispatch · weekly report · Airflow nightly forecast
        Guardrails: PII redaction · prompt-injection filter · JSON-schema validation · JWT+RBAC
        Observability: Langfuse traces · audit_log table · token ledger
```

**RAG pipeline detail (this is where the RAG bonus points live):**
- **Contextual RAG:** at ingest, gpt-4o-mini writes a 1–2 sentence context for each chunk ("Review from Table-service customer at Mirpur branch, Saturday dinner, complaining about onion-forward biryani") and prepends before embedding.
- **Semantic chunking:** embeddings cosine similarity between consecutive sentences; cut when similarity < threshold → variable-size chunks.
- **Late interaction:** lightweight ColBERT-style token-embedding rerank of top-50 → top-10 (RAGatouille or a mini ONNX ColBERT).
- **GraphRAG:** review facets land as edges in a KG (`(chicken_biryani, composure_negative_aspect, rice_freshness)`), so "what ingredient is driving my Friday dip?" becomes a 2-hop graph query.

---

## 4. The Master Prompt (hard rule)

The Zero-to-Launch/Unicorn track requires **ONE master prompt only** — humans then just click "approve / continue / deploy". Full ready-to-paste prompt: **`MASTER_PROMPT.md`** (all 8 mandated modules covered). Workflow discipline:

1. Run it once in Cursor (agent mode)/Kiro; it generates architecture → code → docs → tests → deployment config.
2. Any change is fed back as an instruction to the generated project's own maintainer-agent flow — **never** ad-hoc editing that violates the one-prompt narrative.
3. Prompt Strategy field (5 pts) = quote our exact chain-of-thought structure, system-prompt layering, and tool-selection heuristics.

---

## 5. Day-by-Day Schedule (Oct 23 → Oct 31, GMT+6)

| Day | Ship |
|---|---|
| **Fri Oct 23 (today)** | Register team (5 members, NRB + female flags). Run Master Prompt → repo scaffold, Docker compose up, Postgres+pgvector+MinIO live. |
| **Sat Oct 24** | Data pipeline: seed reviews (synthetic Banglish + Yelp subset), POS CSV schema, ingestion n8n workflow, dedupe/PII/sentiment enrichment. |
| **Sun Oct 25** | RAG core: contextual prefixes, semantic chunking, pgvector indexing, GraphRAG KG + traversal tool, ColBERT rerank. |
| **Mon Oct 26** | Agents: LangGraph graph/state tools, OpenAI Agents SDK wiring, **3 custom MCP servers** built (inventory/review/forecast), postgres/fetch/filesystem MCP integrated, **4 local models on Ollama** running real subtasks. |
| **Tue Oct 27** | Voice loop: Whisper STT → intent → TTS answer · forecast math (sales-velocity × seasonal-index × sentiment-urgency − on-hand) · PO generation · n8n email/WhatsApp · Airflow nightly forecast. |
| **Wed Oct 28** | Dashboard polish (v0), JWT+RBAC+rate-limit+guardrails, Langfuse tracing, eval harness run (F1/nDCG/MAPE + LLM-as-judge), fine-tune gpt-4o-mini on 1k labeled Banglish facets (+ LoRA Qwen cohort as bonus). |
| **Thu Oct 29** | Deploy: Vercel (frontend), Render (API+DB), Cloudflare Tunnel (Ollama node). Figma finalize. **Record & upload YouTube demo** (buffer for processing). Docs site. |
| **Fri Oct 30** | Fill submission form (char-count audit per SUBMISSION_KIT.md), debug live demo end-to-end, dry-run the video flow. Hard stop 23:59 Oct 31 buffer day (Sat Nov 1 = only emergencies). |

**Cutting rules if behind:** GraphRAG-lite > ColBERT rerank > fine-tuning > Airflow (keep n8n — 2 bonus pts).

---

## 6. Risks & Mitigations

- **Overclaiming = auto-disqualification risk:** every checkbox claim needs a real artifact (code path, screenshot, trace). The rubric's own guide says judges verify. No fabricated "Kimi local run" — 4 verifiable Ollama models is already max points.
- **API spend:** GPT-4o for synthesis only; everything cheap is 4o-mini/local. Est. <$30 total.
- **Voice demo on poor upload:** pre-record TTS audio fallback in the video.
- **Video upload processing delay:** upload by Oct 29, not Oct 31.
- **Scraping ToS:** use public/synthetic review data — don't mass-scrape Google.

---

## 7. Pre-flight audit checklist (run before submitting)

- [ ] All 5 links live (YouTube, GitHub, demo, Figma, extras ×3)
- [ ] Every text field ≥ its char minimum (audit script in SUBMISSION_KIT.md)
- [ ] README: one-command setup + seeded demo account (Access Note field filled)
- [ ] Master prompt contains all 8 mandated modules verbatim sections
- [ ] MCP disclosure: built ×3, used ×3, transports (stdio + SSE), client/host noted
- [ ] Ollama hardware + quantization notes written (they earn evaluation points)
- [ ] Langfuse public trace link shows a real multi-tool agent run
- [ ] Team page: 5 members, NRB ✅, female ✅
