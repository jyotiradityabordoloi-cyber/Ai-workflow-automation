# SupportFlow AI

An internal support-agent workspace: AI ticket classification, grounded response drafting and
structured escalation, with a human approving every AI output. Not a chatbot.

## Build plan (incremental)

| Step | Scope | Status |
|---|---|---|
| 1 | Frontend with realistic mock data (all 6 pages, working actions) | done |
| 2 | FastAPI + PostgreSQL + LangGraph classification with schema-validated LLM output | **done** |
| 3 | Vector retrieval (ChromaDB/Qdrant) + response drafting | next |
| 4 | Escalation brief + human approval + Slack (simulated without credentials) | |
| 5 | Full LangGraph workflow, held-out evaluation, end-to-end tests | |

## Architecture

```
frontend/ (Next.js)  ──HTTP──▶  backend/app/api.py (FastAPI routes, thin)
                                   │
                                   ├─ services/tickets.py   workflow rules, audit trail   ──▶ PostgreSQL (SQLAlchemy + Alembic)
                                   └─ ai/classification.py  LangGraph graph
                                        precheck ─┬─▶ classify (LLM, JSON Schema + Pydantic) ─┐
                                                  └─▶ fallback (no LLM call) ─────────────────┴─▶ apply_rules ─▶ END
                                        ai/llm.py    Groq client: schema output, retries, token pacing (FakeLLM for tests)
                                        ai/rules.py  Module 4 safety rules (deterministic code)
```

## Run it

```bash
cd supportflow
docker compose up -d                       # PostgreSQL 16 on localhost:5433

cd backend
py -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.seed.load --reset --analyze   # 28 tickets, classified by the real model
.venv\Scripts\uvicorn app.main:app --port 8000

cd ..\frontend
copy .env.example .env.local               # NEXT_PUBLIC_API_MODE=live
npm install && npm run dev                 # http://localhost:3000
```

The backend reads `GROQ_API_KEY` from the repo-root `.env`. Without a key it uses a clearly labelled keyword
classifier. Set `NEXT_PUBLIC_API_MODE=mock` to run the frontend alone on mock data.

## What step 2 does

**API:** `GET /api/tickets`, `POST /api/tickets` (intake form, optional immediate classification),
`POST /api/tickets/{id}/analyze | decision | assign-senior | manager-approval`, `GET /api/audit`,
`GET /api/evaluations/latest`, `GET /api/health`. Errors always come back as `{"error": "..."}` with a meaningful status
(404 / 403 / 409 / 422); unexpected errors return 500 with a request ID and are logged. Ticket text is never logged.

**Classification safety, in layers:**

1. *Precheck (code, before any LLM call):* non-Latin script, non-English text (function-word detection for es/fr/de/pt/it/nl),
   or fewer than 4 words → manual review, and no tokens are spent.
2. *Structured output:* the LLM must return JSON matching `ClassificationOutput`. A bad reply is retried once with the
   validation error; a second failure, or an outage, stores a fallback that forces manual review instead of raising an error.
3. *Rules (code):* confidence < 0.7 → manual review · model-reported language ≠ en → manual review ·
   angry + P1 → senior agent · legal / lawyer / refund / chargeback → manager review.
4. *Humans:* a classification is never applied until an agent accepts or overrides it. A manual-review ticket can't be
   accepted, only classified by hand. Only a manager can clear a manager-review flag. Re-analysis resets the decision.

Drafting and escalation still run on the frontend mock until steps 3–4.

## Measured results (step 2)

`python -m eval.run_eval --dataset eval/datasets/dev.jsonl --split dev` · 30 labelled tickets · `openai/gpt-oss-120b` on Groq · 0 LLM failures

| Field | AI | Always guess the most common answer |
|---|---:|---:|
| Category | **100%** (macro-F1 100%) | 26.7% |
| Priority | **90.0%** (P3→P2 ×2, P2→P3 ×1) | 46.7% |
| Sentiment | **93.3%** (frustrated→neutral ×2) | 53.3% |
| Manual-review routing (vague / non-English) | **4 of 4 caught, 0 unexpected** | |
| Model latency | p50 445 ms · p95 770 ms (excludes free-tier rate-limit pacing) | |

**Read these with care:**

* **This is a dev split, not a held-out score.** The prompt's definitions were written with these tickets in view, so
  the numbers are optimistic. Step 5 scores a held-out test set once.
* **Model confidence isn't a useful signal yet.** On every classified ticket the model reported 0.90–0.97; only the
  precheck fallbacks scored below 0.7. Manual review is therefore driven by the precheck and the language rule, not by
  the 0.7 threshold. Step 5 checks calibration on held-out data.
* **A real gap was found and closed in this step.** A German ticket was classified "bug, 0.80" and could be accepted;
  the language precheck and the `language` field in the output schema now route it to manual review (tests cover both).

## Landing page (`site/`)

A static product page for SupportFlow AI, built with the design-taste skill and passing its finish gate
(`GATE: PASS`; performance 0 FAIL, 285 KB transferred, LCP 740 ms, no layout shift).

* Shows the real product: the agent workspace as live HTML (inbox beside the open ticket), the safety rules
  as SupportFlow's own screens, the pipeline as a scroll moment, the measured dev-set accuracy, the stack.
* Plain, sourced copy: every number on the page comes from a run; the dev-set caveat is on the page.
* Ships only what it loads: 36 files, 624 KB of kit assets. No photographs (none exist for a software product).
* Open `site/index.html` through any static server (`py -m http.server -d site 8090`). The main button points at
  the workspace on `http://localhost:3000/`; replace it with the deployed URL.

The dashboard uses the same system: palette (white, ink, one mint accent; no violet), Epilogue with
JetBrains Mono, the same mark, and buttons that step on hover and press on click.

## Tests

```bash
cd supportflow/backend && .venv\Scripts\python -m pytest -q
```

44 tests (rules, schema validation, graph retry/fallback paths, API contract and permissions). They run on SQLite
in memory with a fake LLM, so they need no Docker and no API key.
