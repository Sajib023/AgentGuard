# Evaluation Rubric — "Idea to Unicorn" Track
## International AI Builders Congress 2026 (CloudCamp BD)

> **Source of truth:** `cloudcamp-bd` MCP → `cloudcamp://knowledge-base` (Master Knowledge Base & Submission Guide), retrieved 2026-10-23.
> **Track:** Idea to Unicorn (incorporates the Zero to Launch one-prompt challenge)
> **Preliminary deadline:** Oct 31, 2026, 11:59 PM GMT+6 — submit at **cloudcampbd.com**
> **Scoring model:** automated **pre-judgment auto-scoring engine** (leaderboard) + judge evaluation (demo, quality, innovation). This rubric covers both layers.

---

## 0. Scoring Summary

| # | Scoring Category | Max Points |
|---|---|---|
| A | Links & Deliverables | **15** |
| B | Team Diversity | **7** |
| C | AI Stack, RAG & Models | **110+** |
| D | Data Lifecycle & Pipelines | **25** |
| E | MCP Integration & Transports | **20+** |
| F | Environment & Tunneling | **6** |

Eligibility gate (not point-scored, but disqualifying if violated): the **Single Master Prompt rule** — see §7.

> ⚠️ **Auditor note ((smoothing-over forbidden)):** where the knowledge base prints "110+" / "20+", the "+" means additional criteria exist that are not itemized in the published tables. Two internal inconsistencies in the source are flagged inline: §A (itemized 17 vs. cap 15) and §E (itemized 12 vs. cap 20+). Treat published itemization as a floor; claim conservatively and document loudly.

---

## A. Links & Deliverables — max 15 pts

Every link is machine-checked for validity. Invalid or dead links score 0 for that row.

| Field | Requirement | Pts | Full-credit anchor |
|---|---|---|---|
| YouTube Video URL | Valid YouTube link | **10** | 2–3 min demo showing **real, working software**: live UI walkthrough, features in action, complete user workflow. Crisp audio + clear screen recording. Voice-over, no dead air, no sitting on the code. |
| GitHub Repository URL | Valid, public GitHub link | **2** | Public repo, complete README (setup, env vars, run instructions), config files committed. A stranger can clone-and-run. |
| Live Demo URL | Valid public URL | **1** | App reachable from the open internet (no localhost, no login-only black hole). |
| Figma / Design Link | Valid URL | **1** | Mockups, wireframes, or system architecture diagrams — evidence of intentional design. |
| Other Links (up to 3) | Valid URLs | **3** | 1 pt per working link, up to 3 (traces, docs site, dataset, eval results, demo video extras). |
| Access Note | Optional text | 0 | Not scored, but painless judge access = smarter scoring everywhere else. |

⚠️ **Inconsistency flag:** itemized sum = **17 pts**, but the official category cap is **15 pts**. Assume 15 is the cap; treat YouTube (10) as the make-or-break deliverable.

**0-pt scorable fields (quality signals only):** Project Title (clear, memorable), Tagline / Elevator Pitch (one sentence, core value prop), Team Composition mechanics live in §B.

---

## B. Team Diversity — max 7 pts

| Item | Rule | Pts |
|---|---|---|
| Team Composition | 1 pt per **registered** member, capped at 5 members | 5 |
| NRB Member Bonus | At least 1 Non-Resident Bangladeshi member on the registered roster | 1 |
| Female Member Bonus | At least 1 female member on the registered roster | 1 |

Key mechanic: diversity points attach to the **registration record**, not the work. Unregistered contributors score nothing — register everyone before the deadline.

---

## C. AI Stack, RAG & Models — 110+ pts (the battleground)

The largest bucket. Points come from (C1) checked tech-stack selections, (C2) RAG bonus techniques, and (C3) narrative stack fields on the form.

### C1. Auto-scored stack selections

| Scoring item | Rule | Pts |
|---|---|---|
| LLM Selection | ≥ 1 LLM listed in tech stack | **5** |
| RAG Techniques | 1 pt **each** selected: Naive RAG, Vector DB, Contextual RAG, Semantic Chunking, Late Interaction, Graph RAG | **max 5** |
| — Contextual RAG bonus (Anthropic-style) | chunk-specific context prefixes before embedding | **5** |
| — Variable / Semantic Chunking bonus | semantic-boundary splitting, not fixed token windows | **3** |
| — **Combo** bonus: Contextual RAG + Variable Chunking | both in the same pipeline | **3** |
| — Graph RAG / Knowledge Graph bonus | entity–relation graph, multi-hop reasoning | **5** |
| Frontend AI Tools | 1 pt **each**: Lovable, v0, Bolt.new, Cursor, Claude Artifacts, Gemini Canvas, ChatGPT Canvas | **max 5** |
| Automation / Workflow Tools | 1 pt **each**: n8n, Zapier, Make, Airflow, Temporal, Dagster, Prefect, LangGraph, Windmill, Activepieces | **max 4** |
| — n8n specific bonus | n8n load-bearing in the workflow | **2** |
| Local LLM Runtimes | 1 pt **each**: Ollama, LM Studio, vLLM, llama.cpp, Apple MLX, GPT4All, TGI, TensorRT-LLM | **max 3** |
| — Ollama runtime bonus | Ollama actually running models | **2** |
| Local Models Run | **2 pts each** open-weight model actually executed: Kimi, DeepSeek, GLM, Llama 3, Qwen, etc. | **max 8** |
| Agent Frameworks | 1 pt **each**: Hermes, OpenClaw, LangGraph, CrewAI, AutoGen, OpenAI Swarm, OpenAI Agents SDK, Letta | **max 5** |
| AI-DLC Frameworks | 1 pt **each**: AWS Kiro, AWS AI-DLC, BMAD-METHOD, Spec-Kit, Cursor Rules, Cline Memory Bank | **max 3** |

Itemized visible total: **~58 pts**. With "110+" as the category cap, the remainder comes from non-itemized stack criteria (hardware disclosure, quantization notes, model-routing, stack depth) plus the narrative fields in C3. When stacked deliberately, the same project can collect ~78 pts across C1+C3. Claim only tools that are **actually load-bearing** — judges audit.

### C2. Bookkeeping you must not miss

- Combos pay extra: Contextual RAG + Variable Chunking is checked **twice individually (+5, +3) AND once as a combo (+3)** — three line items from one pipeline.
- Local models are the highest per-item rate in the visible table (2 pts each, 4 models = 8). Document **quantization + hardware specs** for each local model run — the KB explicitly rewards it.

### C3. Narrative stack fields (scored on the form)

See §6 for the full text-field rubric (Prompt Strategy 5, Token Optimization 3, AI-DLC 3–4, Agent/Orchestration 2, Fine-Tuning 2, Evaluation & Quality 3, Guardrails 3).

**0 points if:** field missing, under minimum characters, or generic filler ("we used RAG and agents"). **Full points if:** ≥ min chars, names the concrete mechanisms, and maps each claim to something visible in the demo or repo.

---

## D. Data Lifecycle & Pipelines — max 25 pts

Full technical credit requires a documented pipeline **end to end**, from ingestion to delivery. The KB prescribes 5 stages (⚠️ per-stage points aren't published; if split evenly, ~5 pts/stage — treat that as inference, not official):

| Stage | What evaluators look for | Evidence in repo/demo |
|---|---|---|
| 1. Data Sources & Acquisition | APIs, scrapers/crawlers, public datasets, or custom MCP data servers | source scripts, fetch jobs, provenance notes |
| 2. Parsing & Processing | format converters (JSON/CSV/PDF), schema validation logic | parser modules, schema definitions |
| 3. Cleaning & Enrichment | deduplication, imputation, LLM-assisted entity extraction | cleaning pipeline, before/after examples |
| 4. Storage Targets | relational (PostgreSQL), vector (Pinecone, pgvector), object storage (S3) | schema/migrations, vector index setup |
| 5. Analytics & Delivery | BI dashboards, real-time webhooks, outbound REST APIs, automated reports | dashboard + delivered-artifact demo |

**Scored narrative fields feeding this category:** Data Quality Measures (2), Privacy & Compliance (2–3), Lineage & Observability (2). Life-cycle credit is lost not by building nothing, but by **documenting nothing** — each stage needs text + visible artifact.

---

## E. MCP Integration & Transports — 20+ pts

MCP work is first-class. The published table:

| Scoring item | Rule | Pts |
|---|---|---|
| MCP Built | 1 pt **per custom MCP server built by the team** | **max 3** |
| MCP Used | 1 pt **per external MCP server integrated** (e.g. PostgreSQL MCP, GitHub MCP, Fetch MCP) | **max 3** |
| MCP Architecture | transports supported (**SSE / Streamable HTTP, Stdio**), client/host disclosure, reuse notes | **6** |

Itemized visible total: **12 pts**; official cap says 20+, so additional un-published MCP criteria exist (permission boundaries, security posture, depth of tool exposure). To maximize regardless of the hidden table:

1. Build ≥ 1 custom MCP server (expose real business logic / DB queries) → 3 pts.
2. Integrate ≥ 1 public MCP server → 3 pts.
3. Support standard transports (SSE or Stdio) and say so explicitly → within the 6-pt architecture line.
4. Write explicit **client/host disclosure + permission boundary notes** in the submission — declared twice in the KB as score-bearing.
5. Voting with the bonus structure: the example servers named in the KB (PostgreSQL, GitHub, Fetch) are known-scoreable — use one even if trivial.

⚠️ **Inconsistency flag:** 12 itemized vs. 20+ cap — build all four above so the hidden criteria find evidence either way.

---

## F. Environment & Tunneling — max 6 pts

| Scoring item | Rule | Pts |
|---|---|---|
| Publishing local environment to the internet | ngrok, Cloudflare Tunnel (e.g. local inference exposed as an MCP endpoint) | **4** |
| Tunneling Usage Notes (form field, ≥ 80 chars) | which tunnel, why, what's exposed, security notes | **2** |

The 4 + 2 sums exactly to the 6-pt cap — which is why Tunneling Usage Notes exists as its own form line. A working tunnel with no written explanation leaves 2 points on the floor.

---

## 6. Narrative Text-Field Rubric (form fields, all scorers read these)

Minimum character counts are auto-enforced; below the floor = automatic near-zero. Tiered fields score by depth, not volume.

| Field | Min chars | Pts | Full-credit anchor |
|---|---|---|---|
| Prompt Strategy Text | — (tiered) | **5** | Describes the actual strategy: system-prompt structure, chain-of-thought scaffolding, prompt chaining. Tiered scoring (0 = none / mid = vague mentions / 5 = structured walkthrough + example). |
| Token Optimization Notes | ≥ 50 | **3** | Concrete compression, caching, context pruning, or model-routing techniques — with measured impact if possible. |
| AI-DLC Process Notes | ≥ 100 | **3–4** | Which lifecycle methodology was adopted (AWS Kiro, BMAD-METHOD, Spec-Kit, Cursor Rules …) and how it changed the build. |
| Agent / Orchestration Notes | ≥ 80 | **2** | Multi-agent topology, tool invocation flow, decision loops. |
| Fine-Tuning / Adaptation Notes | ≥ 80 | **2** | LoRA / instruction tuning / dataset curation — or honest "why we didn't" with our alternative. |
| Evaluation & Quality Methods | ≥ 80 | **3** | LLM-as-a-judge, bench testing, automated evals — the measurement story, not vibes. |
| Guardrails / Safety / Privacy | ≥ 80 | **3** | Input/output sanitization, PII redaction, moderation layers. |
| Tunneling Usage Notes | ≥ 80 | **2** | See §F. |
| Data Quality Measures | ≥ 80 | **2** | Validation, dedup, schema enforcement, data hygiene. |
| Privacy & Compliance Notes | ≥ 80 | **2–3** | Storage decisions, user consent, security standards. |
| Lineage & Observability Notes | ≥ 80 | **2** | Logging, tracing, telemetry (LangSmith, Phoenix, Langfuse), pipeline lineage. |

Narrative total ≈ **29–30 pts** across categories C/D/F.

---

## 7. Eligibility Gate — the Single Master Prompt (Zero to Launch constraint)

**Not point-scored — pass/fail.** Violation = disqualified from the prompt challenge regardless of auto-score.

1. **ONE PROMPT ONLY.** A single master prompt must generate/initialize the entire system: architecture, modules, docs, deployment. No prompt #2, no mid-build hand-tweaking prompts.
2. The master prompt must contain **all 8 core modules** (audit each one in the prompt text):
   - [ ] **Core Product & AI Instructions** — concept, target users, features, user journeys, demo persona
   - [ ] **Data Architecture** — schemas, models, vector store setup, pipelines
   - [ ] **Admin Module** — user management, RBAC, analytics dashboard, system settings
   - [ ] **Security Module** — auth, rate limiting, encryption, vulnerability guardrails
   - [ ] **Documentation Module** — architecture doc, API reference, install guide
   - [ ] **Audit Reporting** — audit logging, token usage tracking, compliance checks
   - [ ] **Presentation & Pitch Deck** — auto-generated slide structure, value prop, market analysis
   - [ ] **Deployment Requirements** — infra config, Docker, CI/CD scripts, env configuration
3. **Post-execution interaction whitelist** (anything outside this list breaks the one-prompt rule): "Click to approve" / "Click to continue" / "Click to proceed" / "Yes" / "Continue" / "Deploy".

---

## 8. Judge Layer (post-auto-score evaluation)

The auto engine sets the leaderboard; judges score what auto-scoring can't. The KB's stated criteria map to five judged dimensions:

| Dimension | Judges reward | Fails when |
|---|---|---|
| Problem & real-world fit | Solves a **real** problem, contextually (baseline: production-grade AI-native apps, pipelines, startups) | toy demos,技术 flexing with no user |
| Production readiness | Deployed, functional, clean engineering practices, AI-DLC rigor | localhost demos, abandoned README |
| Demo & video quality | Crisp audio, clear workflow, working UI (the 10-pt video row is auto-scored, but judges re-watch it) | reading slides over a dead screen |
| Sophistication honesty | Claims match the repo — agents actually loop, RAG actually retrieves, MCP servers actually serve | checkbox-stuffed stacks with hollow evidence |
| Pitch & docs | Pitch-ready documentation, deck, live interactive demo | missing the narrative arc |

---

## 9. Final Score-Audit Checklist (100% walk-through)

Pre-deadline audit, in order:

- [ ] **Video:** 2–3 min YouTube demo of real working software (10 pts gate — re-record if audio is muddy)
- [ ] **GitHub:** public repo, README with setup steps, config files
- [ ] **Live demo + Figma** links both live and click-tested from an incognito session
- [ ] **Master prompt:** all 8 modules present; post-prompt actions within whitelist
- [ ] **Character audit:** token-opt ≥ 50; AI-DLC ≥ 100; every other note ≥ 80 chars
- [ ] **Stack checkboxes:** LLM + Contextual RAG + semantic chunking (+combo) + GraphRAG + frontend builders + n8n + LangGraph + agent framework + AI-DLC framework — each traced to load-bearing use
- [ ] **Local models:** Ollama runtime (+bonus), 2–4 open-weight models run with quantization + hardware notes
- [ ] **MCP disclosure:** built servers, used servers, transports, clients/hosts, permission boundaries — all written down
- [ ] **Tunneling:** working tunnel + 80+ char usage note (4+2)
- [ ] **Data lifecycle:** 5 stages documented with artifacts (sources → parse → clean → store → deliver)
- [ ] **Team:** all ≤ 5 members registered; NRB + female bonuses marked correctly

---

*Companion docs: `PLAN.md` (score-optimized build plan), `MASTER_PROMPT.md` (the one prompt), `SUBMISSION_KIT.md` (form-field filler text).*
