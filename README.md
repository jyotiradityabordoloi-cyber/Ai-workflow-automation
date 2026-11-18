# AI Workflow Automation

> **Live: SupportFlow AI**, the agent workspace built on this work:
> [product page](https://ai-workflow-automation-site.vercel.app) ·
> [try the workspace](https://ai-workflow-automation-rose.vercel.app) ·
> [how it's built](supportflow/README.md)

Two business processes automated with a free LLM, run by a small task orchestrator, with the time saved
and the AI's accuracy **measured rather than claimed**.

> Portfolio project. The company (**Nimbus3D**, a SaaS for 3D virtual property tours), its clients and all
> tickets are fictional. The code is standard-library Python with zero dependencies.

| Workflow | What it automates | Headline result |
|---|---|---|
| **Support ticket routing** | Tag every incoming ticket, route it to one of 5 teams, draft a reply, write the escalation brief | **95.8% routing accuracy on a held-out test set** (target 94%) |
| **Approval reporting** | Weekly check of expense / purchase / discount approvals against policy, routing and a management report | **~4.5 h of manual work per week → 33 s machine + ~29 min human review** |

---

## 1. Support ticket routing (Nimbus3D demo)

### The process

```
ticket arrives
 ├─ precheck (code): too short? non-Latin script? legal / refund / chargeback mentioned?
 ├─ classify (LLM): team · priority P1-P3 · sentiment · confidence · 2-line summary
 └─ build_index: BM25 search over resolved tickets
        │
 triage (code) ── confidence < 0.7 ───────► "Needs manual review" (AI suggestion hidden)
               ── angry + P1 ─────────────► senior agent queue
               ── legal/refund/chargeback ► manager review before ANY reply
        │
 ├─ retrieve: 3 most similar resolved tickets
 ├─ draft_replies (LLM): reply grounded in those tickets ─► safety checks (code)
 ├─ escalation_briefs (LLM): Slack brief to the owning team's channel, awaiting agent confirmation
 └─ evaluate: accuracy vs labelled tickets
        │
 render_report: agent queue (HTML), triage.csv
```

**Teams:** Business · Developer · Support · Product · QA/Automation.

### Results

The prompt was tuned on a **dev set** of 24 tickets, then frozen and scored **once** on a separate
**test set** of 24 tickets. Every score is shown next to "always guess the most common answer",
which is the bar a classifier has to beat to be useful.

| Held-out test set (24 tickets) | AI | Always-most-common |
|---|---:|---:|
| **Team routing** | **95.8%** | 25.0% |
| Priority (P1-P3) | 87.5% | 58.3% |
| Sentiment | 75.0% | 66.7% |
| Low-information tickets sent to manual review | 2 / 2 | |

* The only routing miss was "tooltip text overflows" (labelled Developer), which the AI sent to Product. That's a defensible call.
* Sentiment is the weakest field. The model under-calls "frustrated" when people describe problems calmly. One attempted
  fix on the dev set made it worse, so it was reverted rather than tuned to the test set.
* 24 tickets is a small sample: one miss moves routing accuracy by 4.2 points.

### Guardrails, enforced in code rather than just asked of the model

* Drafts on legal / refund / chargeback tickets may only acknowledge. Any draft mentioning a refund, credit or approval is replaced.
  (This was added after a real run in which the model copied "manager approved an immediate refund" from a past ticket.)
* Email addresses or links that are not in the reference tickets are flagged `AGENT CHECK`.
* Slack briefs are written to `outbox/slack/` with status `awaiting_agent_confirmation`. Nothing is posted automatically.

---

## 2. Approval reporting

Reads an approvals export, checks it against policy, and produces the weekly report.

* **Rules (code):** missing receipts, discount over limit, duplicates, split purchases that dodge an approval level,
  personal spend, SLA breaches, and amounts too large to fast-track.
* **LLM, running in parallel with the rules:** reads every pending request and flags vague or risky ones.
  It can **only escalate**: it never approves or rejects anything.
* **Outputs:** the approval route per request, a report with an LLM-written summary, and one digest per approver.
* **Number guardrail:** any summary sentence containing a number that isn't in the computed stats is dropped.

| Approval run (48 requests) | Local 3B model (Ollama, CPU) | Groq `gpt-oss-120b` |
|---|---:|---:|
| Machine time | 506 s | **33 s** |
| Vague ₹3.2L "misc tools" purchase | missed by the AI (caught by a rule) | **flagged** |
| Summary sentences dropped by the number guardrail | 2 | 0 |

---

## Measuring impact

Every run appends to `runs/history.jsonl` and regenerates **[IMPACT.md](IMPACT.md)**.

* **Measured:** task durations, LLM calls and tokens, item counts, accuracy.
* **Baseline (estimate until timed):** manual minutes per step in `config/baseline*.json`. To replace an estimate, time the real
  manual work with `py main.py time-manual <step> --items N`. Measured averages automatically replace the estimates,
  and IMPACT.md labels every number as *measured* or *estimate*.
* **Time saved** = manual minutes − the human minutes that remain (reviewing tags, editing drafts, confirming briefs, handling
  manual-review tickets by hand).

## Engineering notes

* **Orchestrator** (`awa/orchestrator.py`): a dependency graph of tasks. Independent tasks run in parallel; each has retries;
  a failure skips only the tasks downstream of it; every task is timed.
* **One client for any free LLM** (`awa/llm.py`): Groq, Gemini, OpenRouter and Ollama all use the OpenAI-compatible API.
  It includes JSON repair, retry-after handling, and client-side token pacing for Groq's free-tier limit of 8,000 tokens per minute (0 failed calls across runs).
* **Retrieval** (`awa/retrieval.py`): BM25 in pure Python, so no embedding API is needed.
* **Real-data path:** `scripts/import_servicedesk.py` imports ServiceDesk Plus exports. Profiles marked `"private": true` are
  kept out of git and out of IMPACT.md.
* **Tests:** `py -m unittest discover -s tests` runs 23 tests and needs no LLM, thanks to a deterministic `mock` provider.

## Run it

```bash
cp .env.example .env                       # add a free GROQ_API_KEY (or use --provider ollama)
py main.py providers                       # check which LLMs are reachable
py main.py run tickets --config config/tickets_teams.json --input data/tickets/teams_test.jsonl
py main.py run approvals --as-of 2026-11-15
```

Outputs land in `runs/<run_id>/` (queue.html / report.html, CSVs, outbox/), and IMPACT.md is refreshed after each run.

```
awa/orchestrator.py            DAG runner
awa/llm.py                     free-LLM client (Groq / Gemini / OpenRouter / Ollama / mock)
awa/retrieval.py               BM25 search
awa/metrics.py                 impact + accuracy reporting
awa/workflows/ticket_triage.py support ticket routing
awa/workflows/approval_report.py approval reporting
config/                        profiles, policy, baselines
data/tickets/                  Nimbus3D dev / test / resolved tickets (fictional)
```
