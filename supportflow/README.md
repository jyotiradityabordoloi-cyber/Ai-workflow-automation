# SupportFlow AI

An internal support-agent workspace: AI ticket classification, grounded response drafting and
structured escalation, with a human approving every AI output. Not a chatbot.

## Build plan (incremental)

| Step | Scope | Status |
|---|---|---|
| 1 | Frontend with realistic mock data (all 6 pages, working actions) | **done** |
| 2 | FastAPI backend + PostgreSQL + LLM classification (schema-validated JSON) | next |
| 3 | Vector retrieval (ChromaDB/Qdrant) + response drafting | |
| 4 | Escalation brief + human approval + Slack (simulated without credentials) | |
| 5 | LangGraph orchestration end to end + evaluation suite + tests | |

## Step 1: frontend (`frontend/`)

Next.js 15 (App Router) · TypeScript · Tailwind CSS v4.

```bash
cd supportflow/frontend
npm install
npm run dev        # http://localhost:3000
```

**Pages:** Overview · Inbox · Ticket workspace (AI analysis, response assistant, safety, escalation, audit trail) ·
Knowledge retrieval · Escalations (with a simulated Slack channel) · AI evaluation.

**Mock mode.** The UI calls only `src/lib/api` (`mock-api.ts` today). The mock enforces the same rules the
backend will, so every button does something real against local state (persisted in the browser):

* An AI classification is never applied until an agent accepts or overrides it.
* Confidence below 0.7, or ambiguous / unsupported-language text → manual review, with the AI's
  suggestion hidden from both the panel and the form.
* Angry + P1 → senior-agent flag with an "assign" action.
* legal / lawyer / refund / chargeback → manager review. Reply approval stays blocked until someone
  signed in as a manager records approval (switch accounts in the sidebar).
* Drafts can be edited, approved or rejected (with a reason). A draft still containing `[Agent name]`
  can't be approved. Nothing is ever sent automatically.
* Escalation briefs (2-line summary, steps already tried, priority, ticket link) are editable and are posted
  to a **simulated** Slack channel only after approval.

**No accuracy is claimed.** The mock analyses are hand-written stand-ins. The evaluation page reports
"no evaluation run yet" plus workspace activity (override and edit rates) until step 5 runs a real
evaluation on a labelled held-out set.

Use **Reset demo data** in the sidebar to return to the seed state.
