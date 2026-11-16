# Impact report

_Generated 2026-11-17 00:18 from 14 recorded run(s) in `runs/history.jsonl`._

| Workflow | Latest model | Human time saved / run | Hours saved / month |
|---|---|---:|---:|
| Approval reporting | openai/gpt-oss-120b | 267.5 min (90.2%) | 19.3 |
| Support ticket triage (sample SaaS tickets) | openai/gpt-oss-120b | 286.0 min (69.4%) | 104.9 |
| Team-routing triage (Nimbus3D demo) | openai/gpt-oss-120b | 230.0 min (73.2%) | 84.3 |

## Approval reporting

Latest run `20261115-190411-groq` at 2026-11-15T19:04:11, status **success**. LLM: groq / openai/gpt-oss-120b: 5 calls, 11,813 tokens, 0 failed, API cost 0 (free tier / local).

- 48 requests, 31 pending, 16 flagged, 15 fast-track, 12 approvers
- AI caught 1 request(s) the rules missed; 0 AI summary sentence(s) dropped for unverifiable numbers

| | Manual process | Automated |
|---|---:|---:|
| Human time | 296.5 min | 29.0 min |
| Machine time (measured) | 0 | 0.55 min |
| **Human time saved** | | **267.5 min (90.2%)** |

**Per month** (4.33 runs): **19.3 hours saved**, about **INR 11,583** at the loaded hourly cost in the baseline file.

| Step | Per | Units | Min/unit | Source | Minutes |
|---|---|---:|---:|---|---:|
| Manual: Export and consolidate requests from email / sheets | run | 1 | 20.0 | estimate | 20.0 |
| Manual: Check each request against policy (receipts, limits, dupes) | request | 48 | 3.0 | estimate | 144.0 |
| Manual: Work out the right approver and forward the request | pending_request | 31 | 1.5 | estimate | 46.5 |
| Manual: Build summary tables in Excel | run | 1 | 30.0 | estimate | 30.0 |
| Manual: Write the management summary | run | 1 | 20.0 | estimate | 20.0 |
| Manual: Send digests / reminders to each approver | approver | 12 | 3.0 | estimate | 36.0 |
| Automated, human: Read the generated report | run | 1 | 5.0 | estimate | 5.0 |
| Automated, human: Verify each flagged request by hand | flagged_request | 16 | 1.5 | estimate | 24.0 |

Task timings (measured):

| Task | Depends on | Status | Start (s) | Duration (s) | Attempts |
|---|---|---|---:|---:|---:|
| load_requests | — | success | 0.002 | 0.002 | 1 |
| policy_check | load_requests | success | 0.006 | 0.001 | 1 |
| ai_review | load_requests | success | 0.004 | 6.407 | 1 |
| route | policy_check, ai_review | success | 6.412 | 0.0 | 1 |
| compute_stats | route | success | 6.412 | 0.0 | 1 |
| exec_summary | compute_stats | success | 6.413 | 26.344 | 1 |
| render_report | route, compute_stats, exec_summary | success | 32.759 | 0.007 | 1 |
| notify | route, render_report | success | 32.767 | 0.018 | 1 |

All runs:

| Run | Provider / model | Status | Machine (s) | Human min saved |
|---|---|---|---:|---:|
| 20261115-183216-ollama | ollama / qwen2.5:3b | success | 617.471 | 266.0 |
| 20261115-184403-mock | mock / heuristic-mock | success | 0.032 | 269.0 |
| 20261115-184408-ollama | ollama / qwen2.5:3b | success | 506.215 | 263.0 |
| 20261115-190411-groq | groq / openai/gpt-oss-120b | success | 32.786 | 267.5 |

Across 3 successful real-LLM run(s): **13.3 hours saved to date**.

Baseline: 0 step(s) measured, 8 still estimates.

## Support ticket triage (sample SaaS tickets)

Latest run `20261115-194040-tickets-groq` at 2026-11-15T19:40:40, status **success**. LLM: groq / openai/gpt-oss-120b: 15 calls, 18,963 tokens, 0 failed, API cost 0 (free tier / local).

- 30 tickets: 26 AI-assisted, 4 manual review, 3 senior queue, 3 manager review, 4 escalations, 26 drafts

### Classifier accuracy (measured on 30 labelled tickets, input `C:\Users\SQY -Jyotiraditya\Projects\ai-workflow-automation\data\tickets\incoming.jsonl`)

| Field | Accuracy | Always-guess-most-common |
|---|---:|---:|
| Category | **100.0%** (meets the 94% target) | —% |
| Priority | **83.3%** | —% |
| Sentiment | **96.7%** | —% |
| Low-confidence tickets sent to manual review | 4/4 | |

Misclassifications: T-5012 priority P3→P2; T-5014 priority P3→P2; T-5015 priority P2→P1; T-5027 priority P3→P2; T-5029 priority P3→P2; T-5017 sentiment frustrated→neutral.

| | Manual process | Automated |
|---|---:|---:|
| Human time | 412.0 min | 126.0 min |
| Machine time (measured) | 0 | 3.06 min |
| **Human time saved** | | **286.0 min (69.4%)** |

**Per month** (22.0 runs): **104.9 hours saved**, about **INR 52,433** at the loaded hourly cost in the baseline file.

| Step | Per | Units | Min/unit | Source | Minutes |
|---|---|---:|---:|---|---:|
| Manual: Read the ticket, pick category and priority | ticket | 30 | 2.0 | estimate | 60.0 |
| Manual: Search past tickets for a similar resolution | ticket | 30 | 4.0 | estimate | 120.0 |
| Manual: Write the reply from scratch | ticket | 30 | 6.0 | estimate | 180.0 |
| Manual: Write the escalation message for engineering | escalation | 4 | 8.0 | estimate | 32.0 |
| Manual: Engineering asks back for missing details | escalation | 4 | 5.0 | estimate | 20.0 |
| Automated, human: Agent checks the AI tag before accepting | ai_ticket | 26 | 0.5 | estimate | 13.0 |
| Automated, human: Agent edits the AI draft before sending | drafted_ticket | 26 | 2.0 | estimate | 52.0 |
| Automated, human: Low-confidence tickets handled fully by hand (2+4+6 min) | manual_ticket | 4 | 12.0 | estimate | 48.0 |
| Automated, human: Manager reviews legal / refund / chargeback tickets | manager_ticket | 3 | 3.0 | estimate | 9.0 |
| Automated, human: Agent confirms the generated Slack brief | escalation | 4 | 1.0 | estimate | 4.0 |

Task timings (measured):

| Task | Depends on | Status | Start (s) | Duration (s) | Attempts |
|---|---|---|---:|---:|---:|
| load_tickets | — | success | 0.002 | 0.001 | 1 |
| load_history | — | success | 0.001 | 0.001 | 1 |
| precheck | load_tickets | success | 0.004 | 0.001 | 1 |
| classify | load_tickets | success | 0.003 | 61.601 | 1 |
| build_index | load_history | success | 0.003 | 0.0 | 1 |
| triage | classify, precheck | success | 61.606 | 0.0 | 1 |
| retrieve | triage, build_index | success | 61.61 | 0.004 | 1 |
| escalation_briefs | triage | success | 61.614 | 1.123 | 1 |
| evaluate | triage, load_tickets | success | 61.61 | 0.0 | 1 |
| draft_replies | triage, retrieve | success | 61.617 | 122.16 | 1 |
| render_report | triage, retrieve, draft_replies, escalation_briefs, evaluate | success | 183.777 | 0.009 | 1 |

All runs:

| Run | Provider / model | Status | Machine (s) | Human min saved |
|---|---|---|---:|---:|
| 20261115-192716-tickets-groq | groq / openai/gpt-oss-120b | success | 62.405 | 292.0 |
| 20261115-192846-tickets-groq | groq / openai/gpt-oss-120b | success | 94.596 | 298.0 |
| 20261115-193031-tickets-groq | groq / openai/gpt-oss-120b | success | 105.086 | 292.0 |
| 20261115-193247-tickets-groq | groq / openai/gpt-oss-120b | success | 243.813 | 286.0 |
| 20261115-193703-tickets-groq | groq / openai/gpt-oss-120b | success | 181.854 | 286.0 |
| 20261115-194040-tickets-groq | groq / openai/gpt-oss-120b | success | 183.787 | 286.0 |

Across 6 successful real-LLM run(s): **29.0 hours saved to date**.

Baseline: 0 step(s) measured, 10 still estimates.

## Team-routing triage (Nimbus3D demo)

Latest run `20261117-001528-tickets-groq` at 2026-11-17T00:15:28, status **success**. LLM: groq / openai/gpt-oss-120b: 13 calls, 16,054 tokens, 0 failed, API cost 0 (free tier / local).

- 24 tickets: 22 AI-assisted, 2 manual review, 1 senior queue, 1 manager review, 2 escalations, 22 drafts

### Classifier accuracy (measured on 24 labelled tickets, input `data\tickets\teams_test.jsonl`)

| Field | Accuracy | Always-guess-most-common |
|---|---:|---:|
| Category | **95.8%** (meets the 94% target) | 25.0% |
| Priority | **87.5%** | 58.3% |
| Sentiment | **75.0%** | 66.7% |
| Low-confidence tickets sent to manual review | 2/2 | |

Category errors (label→AI): developer→product ×1.

Priority errors (label→AI): P2→P1 ×2, P2→P3 ×1.

Sentiment errors (label→AI): frustrated→neutral ×4, positive→neutral ×1, neutral→frustrated ×1.

| | Manual process | Automated |
|---|---:|---:|
| Human time | 314.0 min | 84.0 min |
| Machine time (measured) | 0 | 2.08 min |
| **Human time saved** | | **230.0 min (73.2%)** |

**Per month** (22.0 runs): **84.3 hours saved**, about **INR 42,167** at the loaded hourly cost in the baseline file.

| Step | Per | Units | Min/unit | Source | Minutes |
|---|---|---:|---:|---|---:|
| Manual: Read the ticket, pick category and priority | ticket | 24 | 2.0 | estimate | 48.0 |
| Manual: Search past tickets for a similar resolution | ticket | 24 | 4.0 | estimate | 96.0 |
| Manual: Write the reply from scratch | ticket | 24 | 6.0 | estimate | 144.0 |
| Manual: Write the escalation message for engineering | escalation | 2 | 8.0 | estimate | 16.0 |
| Manual: Engineering asks back for missing details | escalation | 2 | 5.0 | estimate | 10.0 |
| Automated, human: Agent checks the AI tag before accepting | ai_ticket | 22 | 0.5 | estimate | 11.0 |
| Automated, human: Agent edits the AI draft before sending | drafted_ticket | 22 | 2.0 | estimate | 44.0 |
| Automated, human: Low-confidence tickets handled fully by hand (2+4+6 min) | manual_ticket | 2 | 12.0 | estimate | 24.0 |
| Automated, human: Manager reviews legal / refund / chargeback tickets | manager_ticket | 1 | 3.0 | estimate | 3.0 |
| Automated, human: Agent confirms the generated Slack brief | escalation | 2 | 1.0 | estimate | 2.0 |

Task timings (measured):

| Task | Depends on | Status | Start (s) | Duration (s) | Attempts |
|---|---|---|---:|---:|---:|
| load_tickets | — | success | 0.002 | 0.003 | 1 |
| load_history | — | success | 0.001 | 0.001 | 1 |
| precheck | load_tickets | success | 0.005 | 0.001 | 1 |
| classify | load_tickets | success | 0.006 | 4.535 | 1 |
| build_index | load_history | success | 0.003 | 0.001 | 1 |
| triage | classify, precheck | success | 4.542 | 0.0 | 1 |
| retrieve | triage, build_index | success | 4.552 | 0.003 | 1 |
| escalation_briefs | triage | success | 4.551 | 56.724 | 1 |
| evaluate | triage, load_tickets | success | 4.551 | 0.0 | 1 |
| draft_replies | triage, retrieve | success | 4.556 | 120.204 | 1 |
| render_report | triage, retrieve, draft_replies, escalation_briefs, evaluate | success | 124.761 | 0.012 | 1 |

All runs:

| Run | Provider / model | Status | Machine (s) | Human min saved |
|---|---|---|---:|---:|
| 20261117-001047-tickets-mock | mock / heuristic-mock | success | 0.021 | 18.0 |
| 20261117-001054-tickets-groq | groq / openai/gpt-oss-120b | success | 123.912 | 227.0 |
| 20261117-001311-tickets-groq | groq / openai/gpt-oss-120b | success | 124.77 | 227.0 |
| 20261117-001528-tickets-groq | groq / openai/gpt-oss-120b | success | 124.775 | 230.0 |

Across 3 successful real-LLM run(s): **11.4 hours saved to date**.

Baseline: 0 step(s) measured, 10 still estimates.

## How these numbers were produced

- **Measured:** task durations, run time, LLM calls/tokens, item counts, and classifier accuracy against labelled tickets.
- **Estimated until timed:** per-step manual minutes in `config/baseline*.json`. Replace them by timing the real manual work: `py main.py time-manual <step_id> [--workflow tickets] --items N`. Measured averages override estimates automatically.
- Human time saved = manual minutes − the human minutes that remain after automation (reviewing, editing, confirming). Decisions stay with people, so decision time is excluded on both sides.
