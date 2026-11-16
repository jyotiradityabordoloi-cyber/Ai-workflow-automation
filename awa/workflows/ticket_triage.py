"""Support-ticket triage workflow (intake -> drafting -> escalation) with human fallbacks.

DAG (rows run in parallel):

    load_tickets        load_history
    precheck  classify  build_index
    triage              (fallback rules: confidence, angry+P1, legal/refund keywords)
    retrieve            (top-3 similar resolved tickets, BM25)
    draft_replies       escalation_briefs     evaluate
    render_report

Humans stay in charge: AI tags are suggestions the agent accepts, drafts are never
sent as-is, Slack briefs are written to outbox/ and wait for agent confirmation.
"""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..llm import LLMError
from ..orchestrator import RunContext, Workflow
from ..retrieval import BM25

SENTIMENTS = ("positive", "neutral", "frustrated", "angry")
PRIORITIES = ("P1", "P2", "P3")
FALLBACK_SUMMARY = "Insufficient information to classify. Recommend manual review."


def impact_units(m: dict) -> dict:
    return {
        "run": 1,
        "ticket": m.get("tickets_total", 0),
        "ai_ticket": m.get("ai_assisted", 0),
        "drafted_ticket": m.get("drafts_written", 0),
        "manual_ticket": m.get("manual_review", 0),
        "manager_ticket": m.get("manager_review", 0),
        "escalation": m.get("escalations", 0),
    }


DEFAULT_EXAMPLE = ("I've been charged twice this month and I've sent 3 emails already. This is unacceptable.",
                   {"category": "billing", "priority": "P1", "sentiment": "angry", "confidence": 0.95,
                    "summary": "Customer reports double billing this month. Has attempted contact 3 times without resolution."})


def classify_system(cfg: dict) -> str:
    ex_msg, ex_res = (cfg["example_message"], cfg["example_result"]) if cfg.get("example_message") else DEFAULT_EXAMPLE
    return (
        f"You are a support ticket classifier for {cfg.get('product_context', 'a SaaS product')}. For each message produce: "
        f"category (one of: {', '.join(cfg['categories'])}), priority (P1/P2/P3), "
        "sentiment (positive/neutral/frustrated/angry), confidence (a number from 0 to 1: how sure you are "
        "of the category), summary (max 2 sentences, for an agent's quick scan).\n"
        f"Category rubric: {cfg.get('category_rubric', '')}\n"
        f"Sentiment rubric: {cfg.get('sentiment_rubric', '')}\n"
        f"Priority rubric: {cfg['priority_rubric']}\n"
        "If the message is too short, ambiguous, or in a language other than English, return "
        f'category "{cfg.get("fallback_category", "other")}", priority "P2", sentiment "neutral", confidence 0.3 '
        f'and summary "{FALLBACK_SUMMARY}"\n\n'
        f"Example message: {json.dumps(ex_msg, ensure_ascii=False)}\n"
        f"Example result: {json.dumps(ex_res, ensure_ascii=False)}\n\n"
        'Output ONLY a JSON object: {"results": [{"ticket_id": "...", "category": "...", "priority": "...", '
        '"sentiment": "...", "confidence": 0.0, "summary": "..."}]} with one entry per ticket.'
    )


def _conf(v: Any) -> float:
    if isinstance(v, str):
        word = {"low": 0.3, "medium": 0.6, "high": 0.9}.get(v.strip().lower())
        if word is not None:
            return word
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def mock_classify(batch: list[dict], cfg: dict) -> dict:
    """Keyword heuristics standing in for the LLM (provider=mock), for tests only."""
    rules = [("billing", r"charg|invoice|bill|refund|payment|price|seat"), ("bug", r"error|crash|fail|blank|broken|delay|wrong|shows"),
             ("feature_request", r"would (love|be great)|any plan|dark mode|endpoint"), ("account", r"password|owner|access|delete|admin|account")]
    out = []
    for t in batch:
        text = f"{t['subject']} {t['body']}".lower()
        cat = next((c for c, rx in rules if re.search(rx, text)), "other")
        angry = bool(re.search(r"unacceptable|now\b|lawyer|embarrass", text))
        short = len(text.split()) < cfg["min_words"]
        out.append({"ticket_id": t["id"], "category": "other" if short else cat,
                    "priority": "P1" if angry or "whole team" in text else "P2" if not short else "P2",
                    "sentiment": "angry" if angry else "neutral", "confidence": 0.3 if short else 0.85,
                    "summary": FALLBACK_SUMMARY if short else t["body"][:160]})
    return {"results": out}


def build_workflow(input_path: Path | None, history_path: Path, tickets: list[dict] | None = None) -> Workflow:
    """Pass `input_path` (JSONL file) for batch runs, or `tickets` for in-memory runs (the web API)."""
    wf = Workflow("ticket_triage")

    @wf.task("load_tickets", description="Read incoming tickets (JSONL, e.g. a Zendesk export or webhook dump)")
    def load_tickets(ctx: RunContext) -> list[dict]:
        if tickets is not None:
            rows = [dict(t) for t in tickets]
        else:
            rows = [json.loads(x) for x in input_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            r.setdefault("subject", "")
            r.setdefault("agent_escalate", False)
        ctx.set_metric("tickets_total", len(rows))
        return rows

    @wf.task("load_history", description="Read resolved ticket history for retrieval")
    def load_history(ctx: RunContext) -> list[dict]:
        if not ctx.config["tickets"].get("draft_replies", True) or not history_path or not history_path.exists():
            return []
        return [json.loads(x) for x in history_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    @wf.task("build_index", deps=("load_history",), description="BM25 index over resolved tickets")
    def build_index(ctx: RunContext) -> BM25:
        return BM25(ctx.result("load_history"))

    @wf.task("precheck", deps=("load_tickets",), description="Deterministic checks: too short / non-Latin script / review keywords")
    def precheck(ctx: RunContext) -> dict:
        cfg = ctx.config["tickets"]
        kw = re.compile(r"\b(" + "|".join(re.escape(k) for k in cfg["manager_review_keywords"]) + r")\w*", re.I)
        out = {}
        for t in ctx.result("load_tickets"):
            text = f"{t['subject']} {t['body']}"
            letters = [c for c in text if c.isalpha()]
            non_latin = sum(1 for c in letters if ord(c) > 0x24F) / len(letters) if letters else 0
            reasons = []
            if len(re.findall(r"\w+", f"{t['subject']} {t['body']}")) < cfg["min_words"]:
                reasons.append("too short")
            if non_latin > 0.3:
                reasons.append("non-English script")
            out[t["id"]] = {"low_info": reasons, "keywords": sorted({m.group(1).lower() for m in kw.finditer(text)})}
        return out

    @wf.task("classify", deps=("load_tickets",), description="LLM: category, priority, sentiment, confidence, summary")
    def classify(ctx: RunContext) -> dict:
        cfg, tickets = ctx.config["tickets"], ctx.result("load_tickets")
        size = int(ctx.config.get("batch_size", 6))
        batches = [tickets[i : i + size] for i in range(0, len(tickets), size)]
        system = classify_system(cfg)

        def run(batch: list[dict]) -> list[dict]:
            payload = [{"ticket_id": t["id"], "subject": t["subject"], "message": t["body"]} for t in batch]
            try:
                out = ctx.llm.chat_json(system, "Classify these tickets:\n" + json.dumps(payload, ensure_ascii=False),
                                        mock=lambda: mock_classify(batch, cfg))
                items = out.get("results", []) if isinstance(out, dict) else out if isinstance(out, list) else []
                return [x for x in items if isinstance(x, dict)]
            except LLMError as e:
                ctx.count("ai_batch_failures")
                ctx.set_metric("ai_last_error", str(e)[:300])
                return []

        with ThreadPoolExecutor(max_workers=int(ctx.config.get("llm_concurrency", 1))) as pool:
            results = list(pool.map(run, batches))
        out: dict[str, dict] = {}
        for batch, items in zip(batches, results):
            by_id = {str(x.get("ticket_id", "")).strip(): x for x in items}
            for t in batch:
                x = by_id.get(t["id"])
                if not x:
                    ctx.count("ai_missing")
                    out[t["id"]] = {"category": cfg.get("fallback_category", "other"), "priority": "P2", "sentiment": "neutral", "confidence": 0.0,
                                    "summary": "AI classification unavailable.", "valid": False}
                    continue
                cat = str(x.get("category", "")).lower().strip().replace(" ", "_")
                pri = str(x.get("priority", "")).upper().strip()
                sen = str(x.get("sentiment", "")).lower().strip()
                valid = cat in cfg["categories"] and pri in PRIORITIES and sen in SENTIMENTS
                out[t["id"]] = {
                    "category": cat if cat in cfg["categories"] else cfg.get("fallback_category", "other"),
                    "priority": pri if pri in PRIORITIES else "P2",
                    "sentiment": sen if sen in SENTIMENTS else "neutral",
                    "confidence": _conf(x.get("confidence")) if valid else 0.0,
                    "summary": str(x.get("summary", ""))[:300],
                    "valid": valid,
                }
        return out

    @wf.task("triage", deps=("classify", "precheck"), description="Apply human-fallback triggers and pick a queue")
    def triage(ctx: RunContext) -> list[dict]:
        cfg = ctx.config["tickets"]
        cls, pre = ctx.result("classify"), ctx.result("precheck")
        out = []
        for t in ctx.result("load_tickets"):
            c, p = cls[t["id"]], pre[t["id"]]
            conf = min(c["confidence"], 0.3) if p["low_info"] else c["confidence"]
            reasons = []
            if conf < cfg["confidence_threshold"]:
                queue = "manual_review"
                reasons.append(f"Confidence {conf:.2f} < {cfg['confidence_threshold']}" + (f" ({', '.join(p['low_info'])})" if p["low_info"] else ""))
            elif c["sentiment"] == "angry" and c["priority"] == "P1":
                queue = "senior"
                reasons.append("Angry + P1: skip junior queue")
            else:
                queue = "standard"
            manager = bool(p["keywords"])
            if manager:
                reasons.append(f"Mentions {', '.join(p['keywords'])}: manager review before any response")
            ai_visible = queue != "manual_review"
            out.append({
                "id": t["id"], "created_at": t.get("created_at", ""), "customer": t.get("customer", ""), "plan": t.get("plan", ""),
                "subject": t["subject"], "body": t["body"], "agent_escalate": bool(t["agent_escalate"]),
                "queue": queue, "manager_review": manager, "reasons": reasons, "confidence": round(conf, 2),
                # The agent sees AI suggestions only when confidence is high enough.
                "ai": {k: c[k] for k in ("category", "priority", "sentiment", "summary")} if ai_visible else None,
                "_raw": c,
            })
        order = {"senior": 0, "standard": 1, "manual_review": 2}
        out.sort(key=lambda d: ((d["ai"] or {}).get("priority", "P2"), order[d["queue"]], d["created_at"]))
        ctx.set_metric("manual_review", sum(d["queue"] == "manual_review" for d in out))
        ctx.set_metric("senior_queue", sum(d["queue"] == "senior" for d in out))
        ctx.set_metric("manager_review", sum(d["manager_review"] for d in out))
        ctx.set_metric("ai_assisted", sum(d["ai"] is not None for d in out))
        return out

    @wf.task("retrieve", deps=("triage", "build_index"), description="Top-k similar resolved tickets (RAG retrieval)")
    def retrieve(ctx: RunContext) -> dict:
        idx, k = ctx.result("build_index"), int(ctx.config["tickets"]["top_k_similar"])
        if not idx.docs:
            return {}
        return {d["id"]: [{"id": doc["id"], "score": s, "subject": doc["subject"], "resolution": doc["resolution"]}
                          for s, doc in idx.search(f"{d['subject']} {d['body']}", k=k)]
                for d in ctx.result("triage") if d["ai"]}

    @wf.task("draft_replies", deps=("triage", "retrieve"), description="LLM drafts a reply from similar resolutions")
    def draft_replies(ctx: RunContext) -> dict:
        cfg = ctx.config["tickets"]
        if not cfg.get("draft_replies", True):
            ctx.set_metric("drafts_written", 0)
            return {}
        todo = [d for d in ctx.result("triage") if d["ai"]]
        sims = ctx.result("retrieve")
        system = (
            f"You draft first-pass replies for {cfg['product_name']} support agents. An agent always edits your draft "
            "before sending. Use the similar resolved tickets as your source of truth; never promise refunds, credits, "
            "dates or fixes that they do not support, and never invent email addresses, links or names. If the references "
            "don't cover the issue, write a short holding reply and add a line starting 'AGENT CHECK:' saying what to verify. "
            "When manager_review_pending is true, write ONLY an acknowledgement that the team is reviewing the case and will "
            "follow up; do not mention or promise any refund, credit, approval or outcome. Under 120 words, warm and plain, "
            "sign off as [Agent name]. Output ONLY JSON: "
            '{"drafts": [{"ticket_id": "...", "draft": "...", "used_references": ["R-..."]}]}'
        )
        batches = [todo[i : i + 3] for i in range(0, len(todo), 3)]

        def run(batch: list[dict]) -> list[dict]:
            payload = [{"ticket_id": d["id"], "customer": d["customer"], "message": d["body"], "category": d["ai"]["category"],
                        "manager_review_pending": d["manager_review"],
                        "similar_resolved_tickets": sims.get(d["id"], [])} for d in batch]
            mock = lambda: {"drafts": [{"ticket_id": d["id"], "draft": f"Hi {d['customer']}, thanks for reaching out. "
                                        + (sims[d["id"]][0]["resolution"] if sims.get(d["id"]) else "AGENT CHECK: no similar ticket found.")
                                        + "\n[Agent name]", "used_references": [s["id"] for s in sims.get(d["id"], [])[:1]]} for d in batch]}
            try:
                out = ctx.llm.chat_json(system, json.dumps(payload, ensure_ascii=False), mock=mock)
                return [x for x in (out.get("drafts", []) if isinstance(out, dict) else []) if isinstance(x, dict)]
            except LLMError as e:
                ctx.count("ai_batch_failures")
                ctx.set_metric("ai_last_error", str(e)[:300])
                return []

        with ThreadPoolExecutor(max_workers=int(ctx.config.get("llm_concurrency", 1))) as pool:
            results = [x for chunk in pool.map(run, batches) for x in chunk]
        by_id = {d["id"]: d for d in todo}
        drafts = {str(x.get("ticket_id")): {"draft": str(x.get("draft", "")).strip(),
                                            "used_references": [str(r) for r in (x.get("used_references") or [])]}
                  for x in results if str(x.get("ticket_id")) in by_id and x.get("draft")}
        # Deterministic safety checks on every draft (the model's instructions are not enough on their own).
        promise = re.compile(r"\b(refund\w*|credit\w*|approv\w*|reimburs\w*|compensat\w*)\b", re.I)
        contact = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|www\.\S+")
        for tid, v in drafts.items():
            d = by_id[tid]
            if d["manager_review"] and promise.search(v["draft"]):
                v["draft"] = (f"Hi {d['customer']},\n\nThank you for your message. I'm sorry for the trouble. Your case is "
                              "being reviewed by our team lead and we will come back to you with an update shortly.\n\n[Agent name]")
                v["blocked"] = "Draft mentioned refund/credit/approval on a manager-review ticket; replaced with a holding reply."
                ctx.count("unsafe_drafts_blocked")
            source = " ".join([d["body"]] + [s["resolution"] for s in sims.get(tid, [])])
            invented = [m for m in contact.findall(v["draft"]) if m.rstrip(".,)") not in source]
            if invented:
                v["draft"] += "\n\nAGENT CHECK: verify " + ", ".join(sorted(set(invented))) + " (not in the reference tickets)."
                ctx.count("invented_contacts_flagged")
        ctx.set_metric("drafts_written", len(drafts))
        ctx.set_metric("drafts_needing_agent_check", sum("AGENT CHECK" in v["draft"] for v in drafts.values()))
        return drafts

    @wf.task("escalation_briefs", deps=("triage",), description="LLM writes Slack briefs for agent-escalated tickets")
    def escalation_briefs(ctx: RunContext) -> dict:
        cfg = ctx.config["tickets"]
        esc = [d for d in ctx.result("triage") if d["agent_escalate"]]
        ctx.set_metric("escalations", len(esc))
        ai_esc = [d for d in esc if d["ai"]]
        briefs: dict[str, dict] = {}
        if ai_esc:
            payload = [{"ticket_id": d["id"], "subject": d["subject"], "message": d["body"]} for d in ai_esc]
            system = ("You turn escalated support tickets into briefs for the engineering team. For each ticket return "
                      "issue_summary (exactly 2 short lines, what is broken and the impact) and steps_tried (what the "
                      "customer already tried, taken only from the message; empty list if none). Output ONLY JSON: "
                      '{"briefs": [{"ticket_id": "...", "issue_summary": "...", "steps_tried": ["..."]}]}')
            mock = lambda: {"briefs": [{"ticket_id": d["id"], "issue_summary": d["body"][:150], "steps_tried": []} for d in ai_esc]}
            try:
                out = ctx.llm.chat_json(system, json.dumps(payload, ensure_ascii=False), mock=mock)
                for x in out.get("briefs", []) if isinstance(out, dict) else []:
                    briefs[str(x.get("ticket_id"))] = x
            except LLMError as e:
                ctx.count("ai_batch_failures")
                ctx.set_metric("ai_last_error", str(e)[:300])
        slack_dir = ctx.out_dir / "outbox" / "slack"
        slack_dir.mkdir(parents=True, exist_ok=True)
        messages = {}
        for d in esc:
            b = briefs.get(d["id"])
            url = cfg["ticket_url_template"].format(id=d["id"])
            pri = (d["ai"] or {}).get("priority", "unclassified")
            if b:
                tried = b.get("steps_tried") or []
                tried_txt = "\n".join(f"  • {s}" for s in tried) if tried else "  • Nothing mentioned"
                text = (f":rotating_light: *[{pri}] {d['subject'] or d['id']}*\n*Issue:* {str(b.get('issue_summary', '')).strip()}\n"
                        f"*Customer already tried:*\n{tried_txt}\n*Customer:* {d['customer']} ({d['plan']})\n"
                        f"*Ticket:* <{url}|{d['id']}> · priority {pri}")
            else:
                text = f"[{pri}] {d['id']}: low-confidence ticket, agent must write this brief by hand. <{url}|{d['id']}>"
            team = (d["ai"] or {}).get("category", "")
            msg = {"channel": cfg.get("team_channels", {}).get(team, cfg["slack_channel"]), "text": text, "status": "awaiting_agent_confirmation",
                   "ticket_id": d["id"], "ai_generated": bool(b)}
            (slack_dir / f"{d['id']}.json").write_text(json.dumps(msg, indent=2, ensure_ascii=False), encoding="utf-8")
            messages[d["id"]] = msg
        return messages

    @wf.task("evaluate", deps=("triage", "load_tickets"), description="Accuracy vs labelled tickets (if labels exist)")
    def evaluate(ctx: RunContext) -> dict:
        cfg = ctx.config["tickets"]
        labelled = {t["id"]: t["label"] for t in ctx.result("load_tickets") if t.get("label")}
        if not labelled:
            return {"labelled": 0}
        tri = {d["id"]: d for d in ctx.result("triage")}
        res: dict[str, Any] = {"labelled": len(labelled), "target_pct": cfg["accuracy_target_pct"]}
        misses = []
        res["fields"] = []
        for field in ("category", "priority", "sentiment"):
            pairs = [(tid, lab[field]) for tid, lab in labelled.items() if field in lab]
            if not pairs:
                res[f"{field}_accuracy_pct"] = None
                continue
            res["fields"].append(field)
            ok = 0
            confusion: Counter = Counter()
            for tid, want in pairs:
                got = tri[tid]["_raw"][field]
                confusion[f"{want}->{got}"] += 1
                if got == want:
                    ok += 1
                else:
                    misses.append({"ticket": tid, "field": field, "expected": want, "got": got})
            res[f"{field}_accuracy_pct"] = round(100 * ok / len(pairs), 1)
            # "always guess the most common label" - the number any classifier must beat to be useful
            res[f"{field}_majority_baseline_pct"] = round(100 * Counter(w for _, w in pairs).most_common(1)[0][1] / len(pairs), 1)
            res[f"{field}_confusion"] = dict(confusion.most_common())
        exp_manual = {tid for tid, lab in labelled.items() if lab.get("expect_manual")}
        got_manual = {tid for tid in labelled if tri[tid]["queue"] == "manual_review"}
        res["manual_review_expected"] = len(exp_manual)
        res["manual_review_caught"] = len(exp_manual & got_manual)
        res["manual_review_extra"] = sorted(got_manual - exp_manual)
        res["misses"] = misses
        res["category_meets_target"] = (res["category_accuracy_pct"] or 0) >= cfg["accuracy_target_pct"]
        ctx.set_metric("category_accuracy_pct", res["category_accuracy_pct"])
        ctx.set_metric("priority_accuracy_pct", res["priority_accuracy_pct"])
        ctx.set_metric("sentiment_accuracy_pct", res["sentiment_accuracy_pct"])
        return res

    @wf.task("render_report", deps=("triage", "retrieve", "draft_replies", "escalation_briefs", "evaluate"),
             description="Agent queue (HTML/MD), triage.csv")
    def render_report(ctx: RunContext) -> dict:
        tri, sims, drafts = ctx.result("triage"), ctx.result("retrieve"), ctx.result("draft_replies")
        slack, ev = ctx.result("escalation_briefs"), ctx.result("evaluate")
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = ctx.out_dir / "triage.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ticket_id", "queue", "manager_review", "confidence", "category", "priority", "sentiment",
                        "summary", "similar_tickets", "draft", "escalation_brief", "reasons"])
            for d in tri:
                a = d["ai"] or {}
                w.writerow([d["id"], d["queue"], d["manager_review"], d["confidence"], a.get("category", ""), a.get("priority", ""),
                            a.get("sentiment", ""), a.get("summary", ""), " ".join(s["id"] for s in sims.get(d["id"], [])),
                            drafts.get(d["id"], {}).get("draft", ""), slack.get(d["id"], {}).get("text", ""), "; ".join(d["reasons"])])
        html_path = ctx.out_dir / "queue.html"
        html_path.write_text(_render_html(tri, sims, drafts, slack, ev, ctx.llm.describe()), encoding="utf-8")
        md_path = ctx.out_dir / "queue.md"
        md_path.write_text(_render_md(tri, drafts, ev), encoding="utf-8")
        return {"html": str(html_path), "markdown": str(md_path), "csv": str(csv_path)}

    return wf


# ------------------------------------------------------------- rendering
QUEUE_LABEL = {"senior": "Senior agent", "standard": "Standard queue", "manual_review": "Needs manual review"}


def _render_md(tri: list[dict], drafts: dict, ev: dict) -> str:
    L = ["# Support triage queue", ""]
    if ev.get("labelled"):
        L += [f"Accuracy on {ev['labelled']} labelled tickets (target {ev['target_pct']}% for category): " + ", ".join(
            f"{f} **{ev[f + '_accuracy_pct']}%** (always-most-common baseline {ev[f + '_majority_baseline_pct']}%)" for f in ev["fields"]) + ".", ""]
    L += ["| Ticket | Queue | Manager | Category | Priority | Sentiment | Conf. | Summary |", "|---|---|---|---|---|---|---:|---|"]
    for d in tri:
        a = d["ai"] or {}
        L.append(f"| {d['id']} | {QUEUE_LABEL[d['queue']]} | {'yes' if d['manager_review'] else ''} | {a.get('category', '—')} | "
                 f"{a.get('priority', '—')} | {a.get('sentiment', '—')} | {d['confidence']} | {(a.get('summary') or '; '.join(d['reasons'])).replace('|', '/')} |")
    return "\n".join(L) + "\n"


def _render_html(tri, sims, drafts, slack, ev, llm) -> str:
    e = html.escape
    cards = []
    for d in tri:
        a = d["ai"]
        tags = [f"<span class='pill {'bad' if d['queue'] != 'standard' else ''}'>{e(QUEUE_LABEL[d['queue']])}</span>"]
        if d["manager_review"]:
            tags.append("<span class='pill bad'>Manager review before reply</span>")
        if a:
            tags += [f"<span class=pill>{e(a['category'])}</span>", f"<span class='pill {'bad' if a['priority'] == 'P1' else ''}'>{e(a['priority'])}</span>",
                     f"<span class=pill>{e(a['sentiment'])}</span>"]
        body = f"<p class=muted>{e(d['body'])}</p>"
        if a:
            body += f"<p><b>AI summary</b> (confidence {d['confidence']}): {e(a['summary'])}</p>"
        if d["reasons"]:
            body += "<ul>" + "".join(f"<li>{e(r)}</li>" for r in d["reasons"]) + "</ul>"
        if sims.get(d["id"]):
            body += "<details><summary>Similar resolved tickets</summary><ul>" + "".join(
                f"<li><b>{e(s['id'])}</b> {e(s['subject'])} <span class=muted>(score {s['score']})</span><br>{e(s['resolution'])}</li>" for s in sims[d["id"]]) + "</ul></details>"
        if d["id"] in drafts:
            hold = " · HOLD for manager" if d["manager_review"] else ""
            body += f"<details open><summary>Draft reply (edit before sending{hold})</summary><pre>{e(drafts[d['id']]['draft'])}</pre></details>"
        if d["id"] in slack:
            body += f"<details open><summary>Slack escalation brief (awaiting agent confirmation)</summary><pre>{e(slack[d['id']]['text'])}</pre></details>"
        cards.append(f"<section class=card><div class=row><b class=mono>{e(d['id'])}</b> <b>{e(d['subject'] or '(no subject)')}</b>"
                     f"<span class=muted>{e(d['customer'])} · {e(d['plan'])}</span></div><div class=tags>{''.join(tags)}</div>{body}</section>")
    acc = ""
    if ev.get("labelled"):
        ok = ev["category_meets_target"]
        tiles = []
        for f in ev["fields"]:
            cls = ("ok" if ok else "bad") if f == "category" else ""
            note = f"target {ev['target_pct']}% · " if f == "category" else ""
            tiles.append(f"<div class=kpi><div class=muted>{e(f.title())} accuracy</div><div class='big {cls}'>{ev[f + '_accuracy_pct']}%</div>"
                         f"<div class=muted>{note}always-most-common: {ev[f + '_majority_baseline_pct']}%</div></div>")
        if ev["manual_review_expected"]:
            tiles.append(f"<div class=kpi><div class=muted>Manual-review catches</div><div class=big>{ev['manual_review_caught']}/{ev['manual_review_expected']}</div></div>")
        acc = f"<div class=kpis>{''.join(tiles)}</div>"
    counts = Counter(d["queue"] for d in tri)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Support triage queue</title><style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--ok:#1f7a4d;--bad:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1e1e1c;--ink:#ecece8;--muted:#9a9a94;--line:#2f2f2c;--ok:#5cc28f;--bad:#f07167}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}} main{{max-width:900px;margin:0 auto;padding:24px 16px}}
h1{{font-size:24px;margin:0}} .muted{{color:var(--muted);font-size:13px}} .mono{{font-family:ui-monospace,Consolas,monospace}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}} .row{{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}}
.tags{{margin:6px 0;display:flex;gap:6px;flex-wrap:wrap}} .pill{{padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}} .pill.bad{{color:var(--bad);border-color:currentColor}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:16px 0}} .kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}
.big{{font-size:24px;font-weight:600}} .ok{{color:var(--ok)}} .bad{{color:var(--bad)}} pre{{white-space:pre-wrap;font:13px/1.5 ui-monospace,Consolas,monospace;background:var(--bg);padding:10px;border-radius:8px}}
details{{margin-top:8px}} summary{{cursor:pointer;font-weight:600;font-size:13px}} ul{{margin:4px 0;padding-left:18px;font-size:14px}}
</style></head><body><main><h1>Support triage queue</h1>
<div class=muted>{len(tri)} tickets · {counts['senior']} senior · {counts['standard']} standard · {counts['manual_review']} manual review · AI: {e(llm['provider'])} / {e(llm['model'])}</div>
{acc}{''.join(cards)}
<p class=muted>AI tags are suggestions the agent accepts; drafts are never sent unedited; Slack briefs are posted only after the agent confirms.</p>
</main></body></html>"""
