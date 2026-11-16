"""Weekly approval reporting workflow.

DAG (tasks on the same row run in parallel):

    load_requests
      |-- policy_check   (deterministic rules)
      |-- ai_review      (LLM reads every pending request)
    route              (merge rules + AI, pick approver, prioritise)
    compute_stats
    exec_summary       (LLM writes the management summary from the numbers)
    render_report      (Markdown + HTML + decisions.csv)
    notify             (one digest per approver in outbox/)

Design rule: the AI can only *escalate*. It can never approve or reject on its
own, and deterministic policy violations always win.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..llm import LLMError
from ..orchestrator import RunContext, Workflow

HARD_FLAGS = {"duplicate", "blocked_keyword", "discount_over_limit", "missing_field", "invalid_amount"}
FLAG_LABELS = {
    "missing_field": "Missing required field",
    "invalid_amount": "Invalid amount",
    "missing_receipt": "Receipt missing",
    "discount_over_limit": "Discount above policy limit",
    "blocked_keyword": "Looks like personal / non-business spend",
    "duplicate": "Possible duplicate submission",
    "split_purchase": "Possible split purchase to avoid a higher approval level",
    "sla_breach": "Pending longer than SLA",
    "above_fast_track_limit": "Too large to fast-track",
}
SUGGESTION_LABELS = {
    "return_or_reject": "Return to requester / reject",
    "needs_review": "Needs careful review",
    "fast_track": "Fast-track (clean)",
}

REVIEW_SYSTEM = (
    "You are a meticulous finance-operations analyst reviewing internal approval requests "
    "(expenses, travel, purchases, client discounts). You flag risk; you never make the final decision. "
    "Reply with a single JSON object and nothing else."
)
SUMMARY_SYSTEM = (
    "You write crisp management summaries for a weekly approvals report. Use ONLY numbers that appear "
    "in the data you are given; never invent or round differently. Reply with a single JSON object."
)


# ---------------------------------------------------------------- helpers
def _f(value: str | None) -> float | None:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else None
    except ValueError:
        return None


def _dt(value: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def level_for(amount: float, policy: dict) -> str:
    for tier in policy["approval_matrix"]:
        if tier["max_amount"] is None or amount <= tier["max_amount"]:
            return tier["level"]
    return policy["approval_matrix"][-1]["level"]


def approver_for(dept: str, level: str, policy: dict) -> str:
    return policy["approvers"].get(dept, {}).get(level) or policy["approvers"].get("*", {}).get(level) or "Unassigned"


def money(x: float, cur: str = "INR") -> str:
    return f"{cur} {x:,.0f}"


def policy_brief(policy: dict) -> str:
    tiers = "; ".join(
        f"up to {t['max_amount']:,} -> {t['level']}" if t["max_amount"] else f"above -> {t['level']}"
        for t in policy["approval_matrix"]
    )
    return (
        f"Currency {policy['currency']}. Receipts required for {', '.join(policy['receipt_required_types'])} "
        f"above {policy['receipt_required_above']:,}. Max client discount {policy['max_discount_pct']}%. "
        f"Personal spend is not reimbursable. Approval levels by amount: {tiers}. "
        "Descriptions must make the business purpose clear; vague descriptions on large amounts are high risk."
    )


def mock_review(batch: list[dict], policy: dict) -> dict:
    """Heuristic stand-in for the LLM (provider=mock) so tests need no model."""
    out = []
    for r in batch:
        concerns, risk = [], "low"
        amt = r["amount"] or 0
        if len(r["description"].split()) <= 2 and amt > 50000:
            concerns.append("Description too vague for the amount")
            risk = "high"
        if amt > 100000 and risk != "high":
            risk = "medium"
        if r["type"] in policy["receipt_required_types"] and not r["receipt_attached"] and amt > policy["receipt_required_above"]:
            concerns.append("No receipt attached")
            risk = "high" if risk == "high" else "medium"
        out.append({
            "request_id": r["request_id"], "category": r["type"], "risk": risk,
            "recommendation": "approve" if risk == "low" else "needs_review",
            "concerns": concerns, "summary": f"{r['type'].title()} of {money(amt)} with {r['vendor']}: {r['description']}",
        })
    return {"reviews": out}


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _collect_numbers(obj: Any, out: set[float]) -> set[float]:
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            out.add(float(tok.replace(",", "")))
    return out


def is_grounded(text: str, allowed: set[float]) -> bool:
    """True if every number in `text` appears in the source data (small counts <= 10 always allowed)."""
    for tok in _NUM_RE.findall(text):
        v = float(tok.replace(",", "").rstrip("."))
        if v <= 10:
            continue
        if not any(abs(v - a) <= max(0.051, 0.005 * abs(a)) for a in allowed):
            return False
    return True


def mock_summary(stats: dict) -> dict:
    return {
        "headline": f"{stats['pending_count']} requests worth {money(stats['pending_value'])} await approval; "
                    f"{stats['flagged_count']} need attention.",
        "bullets": [
            f"{stats['total_requests']} requests in the export, {stats['decided_count']} already decided.",
            f"{stats['sla_breaches']} pending requests are past the {stats['sla_days']}-day SLA.",
            f"{stats['fast_track_count']} clean requests can be fast-tracked.",
        ],
        "actions": ["Clear SLA breaches first.", "Return requests with hard policy violations to requesters."],
    }


# --------------------------------------------------------------- workflow
def build_workflow(input_path: Path, as_of: dt.datetime) -> Workflow:
    wf = Workflow("approval_report")

    @wf.task("load_requests", description="Read the approval-requests export (CSV)")
    def load_requests(ctx: RunContext) -> list[dict]:
        rows = []
        with open(input_path, newline="", encoding="utf-8-sig") as f:
            for raw in csv.DictReader(f):
                r = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                r["amount"] = _f(r.get("amount"))
                r["discount_pct"] = _f(r.get("discount_pct"))
                r["receipt_attached"] = r.get("receipt_attached", "").lower() in ("yes", "y", "true", "1")
                r["status"] = (r.get("status") or "pending").lower()
                r["type"] = (r.get("type") or "").lower()
                r["_submitted"] = _dt(r.get("submitted_at"))
                r["_decided"] = _dt(r.get("decided_at"))
                r["age_days"] = round((as_of - r["_submitted"]).total_seconds() / 86400, 1) if r["_submitted"] else None
                rows.append(r)
        if not rows:
            raise ValueError(f"no rows in {input_path}")
        ctx.set_metric("requests_total", len(rows))
        ctx.set_metric("requests_pending", sum(r["status"] == "pending" for r in rows))
        return rows

    @wf.task("policy_check", deps=("load_requests",), description="Deterministic policy rules")
    def policy_check(ctx: RunContext) -> dict:
        rows, policy = ctx.result("load_requests"), ctx.config["policy"]
        flags: dict[str, list[tuple[str, str]]] = defaultdict(list)
        levels: dict[str, str] = {}
        kw_re = [(k, re.compile(rf"\b{re.escape(k)}\b", re.I)) for k in policy["blocked_keywords"]]

        for r in rows:
            rid = r["request_id"]
            for fld in ("requester", "department", "description", "type"):
                if not r.get(fld):
                    flags[rid].append(("missing_field", f"Missing {fld}"))
            if r["amount"] is None or r["amount"] <= 0:
                flags[rid].append(("invalid_amount", f"Amount is '{r['amount']}'"))
            amt = r["amount"] or 0
            levels[rid] = level_for(amt, policy)
            if r["type"] in policy["receipt_required_types"] and amt > policy["receipt_required_above"] and not r["receipt_attached"]:
                flags[rid].append(("missing_receipt", f"No receipt for {money(amt)} (required above {money(policy['receipt_required_above'])})"))
            if r["type"] == "discount" and (r["discount_pct"] or 0) > policy["max_discount_pct"]:
                flags[rid].append(("discount_over_limit", f"{r['discount_pct']:g}% requested, limit is {policy['max_discount_pct']}%"))
            text = f"{r['description']} {r['vendor']}"
            hits = [k for k, rx in kw_re if rx.search(text)]
            if hits:
                flags[rid].append(("blocked_keyword", f"Mentions: {', '.join(hits)}"))
            if r["status"] == "pending" and r["age_days"] is not None and r["age_days"] > policy["sla_days"]:
                flags[rid].append(("sla_breach", f"Pending {r['age_days']:.1f} days (SLA {policy['sla_days']})"))

            if r["status"] == "pending" and amt > policy.get("fast_track_max_amount", float("inf")):
                flags[rid].append(("above_fast_track_limit", f"{money(amt)} is above the fast-track limit of {money(policy['fast_track_max_amount'])}"))

        # duplicates: same requester + vendor + amount + description
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            desc = re.sub(r"\W+", " ", r["description"].lower()).strip()
            groups[(r["requester"].lower(), r["vendor"].lower(), r["amount"], desc)].append(r)
        for g in groups.values():
            for r in g[1:]:
                flags[r["request_id"]].append(("duplicate", f"Same requester, vendor, amount and description as {g[0]['request_id']}"))

        # split purchases: same requester + vendor on the same day whose total needs a higher approval level
        days: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            if r["_submitted"] and r["type"] in ("purchase", "expense", "travel"):
                days[(r["requester"].lower(), r["vendor"].lower(), r["_submitted"].date())].append(r)
        for g in days.values():
            if len(g) < 2:
                continue
            total = sum(x["amount"] or 0 for x in g)
            if level_for(total, policy) != max((level_for(x["amount"] or 0, policy) for x in g),
                                                 key=[t["level"] for t in policy["approval_matrix"]].index):
                ids = ", ".join(x["request_id"] for x in g)
                for x in g:
                    flags[x["request_id"]].append(
                        ("split_purchase", f"{len(g)} same-day requests ({ids}) total {money(total)} -> needs {level_for(total, policy)}"))
                    levels[x["request_id"]] = level_for(total, policy)

        counts = Counter(code for fl in flags.values() for code, _ in fl)
        ctx.set_metric("rule_flags", dict(counts))
        return {"flags": dict(flags), "levels": levels}

    @wf.task("ai_review", deps=("load_requests",), description="LLM risk review of every pending request")
    def ai_review(ctx: RunContext) -> dict:
        policy = ctx.config["policy"]
        pending = [r for r in ctx.result("load_requests") if r["status"] == "pending"]
        size = int(ctx.config.get("batch_size", 5))
        batches = [pending[i : i + size] for i in range(0, len(pending), size)]
        brief = policy_brief(policy)

        def review(batch: list[dict]) -> list[dict]:
            payload = [{
                "request_id": r["request_id"], "type": r["type"], "department": r["department"],
                "requester": r["requester"], "vendor": r["vendor"], "amount": r["amount"],
                "discount_pct": r["discount_pct"], "receipt_attached": r["receipt_attached"],
                "description": r["description"],
            } for r in batch]
            user = (
                f"POLICY: {brief}\n\n"
                "Review each request below. For EVERY request_id return one entry. Output format:\n"
                '{"reviews": [{"request_id": "APR-1", "category": "short spend category", '
                '"risk": "low|medium|high", "recommendation": "approve|needs_review|reject", '
                '"concerns": ["short concern", ...], "summary": "one sentence plain-English summary"}]}\n'
                "Use risk=low and recommendation=approve when the request is clearly business-related, "
                "within policy and well described.\n\n"
                f"REQUESTS:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            try:
                out = ctx.llm.chat_json(REVIEW_SYSTEM, user, mock=lambda: mock_review(batch, policy))
                items = out.get("reviews", []) if isinstance(out, dict) else out if isinstance(out, list) else []
                return [x for x in items if isinstance(x, dict)]
            except LLMError as e:
                ctx.count("ai_batch_failures")
                ctx.set_metric("ai_last_error", str(e)[:300])
                return []

        with ThreadPoolExecutor(max_workers=int(ctx.config.get("llm_concurrency", 1))) as pool:
            results = list(pool.map(review, batches))

        reviews: dict[str, dict] = {}
        for batch, items in zip(batches, results):
            by_id = {str(x.get("request_id", "")).strip(): x for x in items}
            for r in batch:
                x = by_id.get(r["request_id"])
                if not x:
                    ctx.count("ai_missing_reviews")
                    reviews[r["request_id"]] = {"category": r["type"], "risk": "unknown", "recommendation": "needs_review",
                                                "concerns": ["AI review unavailable for this request"], "summary": r["description"]}
                    continue
                risk = str(x.get("risk", "")).lower()
                rec = str(x.get("recommendation", "")).lower().replace(" ", "_")
                concerns = x.get("concerns") or []
                if isinstance(concerns, str):
                    concerns = [concerns]
                reviews[r["request_id"]] = {
                    "category": str(x.get("category") or r["type"])[:40],
                    "risk": risk if risk in ("low", "medium", "high") else "unknown",
                    "recommendation": rec if rec in ("approve", "needs_review", "reject") else "needs_review",
                    "concerns": [str(c)[:160] for c in concerns][:4],
                    "summary": str(x.get("summary") or r["description"])[:240],
                }
        ctx.set_metric("ai_reviewed", sum(v["risk"] != "unknown" for v in reviews.values()))
        return reviews

    @wf.task("route", deps=("policy_check", "ai_review"), description="Merge rules + AI, assign approver, prioritise")
    def route(ctx: RunContext) -> list[dict]:
        policy, rows = ctx.config["policy"], ctx.result("load_requests")
        pc, ai = ctx.result("policy_check"), ctx.result("ai_review")
        out = []
        ai_only = disagreements = 0
        for r in rows:
            if r["status"] != "pending":
                continue
            rid = r["request_id"]
            rule_flags = pc["flags"].get(rid, [])
            codes = {c for c, _ in rule_flags}
            a = ai.get(rid, {"risk": "unknown", "recommendation": "needs_review", "concerns": [], "summary": r["description"], "category": r["type"]})
            level = pc["levels"][rid]
            if codes & HARD_FLAGS:
                suggestion = "return_or_reject"
            elif (codes - {"sla_breach"}) or a["risk"] in ("high", "unknown") or a["recommendation"] != "approve":
                suggestion = "needs_review"
            else:
                suggestion = "fast_track"
            if not (codes - {"sla_breach"}) and (a["risk"] in ("medium", "high") or a["recommendation"] != "approve") and a["risk"] != "unknown":
                ai_only += 1  # AI raised something the rules did not
            if codes & HARD_FLAGS and a["recommendation"] == "approve":
                disagreements += 1
            priority = (3 * bool(codes & HARD_FLAGS) + 2 * ("sla_breach" in codes) + 2 * (a["risk"] == "high")
                        + (a["risk"] == "medium") + ((r["amount"] or 0) > 100000))
            out.append({
                "request_id": rid, "submitted_at": r.get("submitted_at", ""), "age_days": r["age_days"],
                "requester": r["requester"], "department": r["department"] or "(missing)", "type": r["type"],
                "vendor": r["vendor"], "amount": r["amount"] or 0, "discount_pct": r["discount_pct"],
                "description": r["description"], "level": level,
                "approver": approver_for(r["department"], level, policy),
                "rule_flags": [{"code": c, "label": FLAG_LABELS.get(c, c), "detail": d} for c, d in rule_flags],
                "ai": a, "suggestion": suggestion, "priority": priority,
            })
        out.sort(key=lambda d: (-d["priority"], -(d["age_days"] or 0)))
        ctx.set_metric("flagged_requests", sum(d["suggestion"] != "fast_track" for d in out))
        ctx.set_metric("fast_track_requests", sum(d["suggestion"] == "fast_track" for d in out))
        ctx.set_metric("ai_only_catches", ai_only)
        ctx.set_metric("ai_rule_disagreements", disagreements)
        ctx.set_metric("approvers_notified", len({d["approver"] for d in out}))
        return out

    @wf.task("compute_stats", deps=("route",), description="Aggregate numbers for the report")
    def compute_stats(ctx: RunContext) -> dict:
        policy, rows, decisions = ctx.config["policy"], ctx.result("load_requests"), ctx.result("route")
        decided = [r for r in rows if r["status"] in ("approved", "rejected") and r["_decided"] and r["_submitted"]]
        cycle_h = [(r["_decided"] - r["_submitted"]).total_seconds() / 3600 for r in decided]
        by_dept: dict[str, dict] = defaultdict(lambda: {"requests": 0, "value": 0.0, "pending": 0, "pending_value": 0.0})
        for r in rows:
            d = by_dept[r["department"] or "(missing)"]
            d["requests"] += 1
            d["value"] += r["amount"] or 0
            if r["status"] == "pending":
                d["pending"] += 1
                d["pending_value"] += r["amount"] or 0
        by_approver: dict[str, dict] = defaultdict(lambda: {"pending": 0, "value": 0.0, "oldest_days": 0.0, "flagged": 0})
        for d in decisions:
            a = by_approver[d["approver"]]
            a["pending"] += 1
            a["value"] += d["amount"]
            a["oldest_days"] = max(a["oldest_days"], d["age_days"] or 0)
            a["flagged"] += d["suggestion"] != "fast_track"
        aging = Counter()
        for d in decisions:
            age = d["age_days"] or 0
            aging["0-1 days" if age <= 1 else "2-3 days" if age <= 3 else "4-7 days" if age <= 7 else "8+ days"] += 1
        statuses = Counter(r["status"] for r in rows)
        total_value = sum(r["amount"] or 0 for r in rows)
        flag_counts = Counter(f["code"] for d in decisions for f in d["rule_flags"])
        return {
            "as_of": as_of.isoformat(timespec="minutes"),
            "currency": policy["currency"],
            "sla_days": policy["sla_days"],
            "total_requests": len(rows),
            "total_value": round(sum(r["amount"] or 0 for r in rows), 2),
            "status_counts": dict(statuses),
            "decided_count": len(decided),
            "approval_rate_pct": round(100 * statuses.get("approved", 0) / len(decided), 1) if decided else None,
            "avg_cycle_hours": round(statistics.mean(cycle_h), 1) if cycle_h else None,
            "median_cycle_hours": round(statistics.median(cycle_h), 1) if cycle_h else None,
            "pending_count": len(decisions),
            "pending_value": round(sum(d["amount"] for d in decisions), 2),
            "pending_count_share_pct": round(100 * len(decisions) / len(rows), 1) if rows else 0,
            "pending_value_share_pct": round(100 * sum(d["amount"] for d in decisions) / total_value, 1) if total_value else 0,
            "flagged_count": sum(d["suggestion"] != "fast_track" for d in decisions),
            "fast_track_count": sum(d["suggestion"] == "fast_track" for d in decisions),
            "return_count": sum(d["suggestion"] == "return_or_reject" for d in decisions),
            "sla_breaches": flag_counts.get("sla_breach", 0),
            "flag_counts": dict(flag_counts),
            "aging": {k: aging.get(k, 0) for k in ("0-1 days", "2-3 days", "4-7 days", "8+ days")},
            "by_department": {k: {**v, "value": round(v["value"]), "pending_value": round(v["pending_value"])} for k, v in sorted(by_dept.items())},
            "by_approver": {k: {**v, "value": round(v["value"])} for k, v in sorted(by_approver.items(), key=lambda kv: -kv[1]["pending"])},
        }

    @wf.task("exec_summary", deps=("compute_stats",), description="LLM writes the management summary")
    def exec_summary(ctx: RunContext) -> dict:
        stats = ctx.result("compute_stats")
        top = [{"id": d["request_id"], "amount": d["amount"], "suggestion": d["suggestion"],
                "flags": [f["code"] for f in d["rule_flags"]], "ai_risk": d["ai"]["risk"]}
               for d in ctx.result("route")[:8]]
        user = (
            "Write the summary for this week's approvals report.\n"
            'Format: {"headline": "one sentence", "bullets": ["3-5 factual bullets"], "actions": ["2-4 concrete next actions"]}\n\n'
            f"STATS:\n{json.dumps(stats, ensure_ascii=False)}\n\nTOP PRIORITY ITEMS:\n{json.dumps(top)}"
        )
        try:
            out = ctx.llm.chat_json(SUMMARY_SYSTEM, user, mock=lambda: mock_summary(stats))
            if not isinstance(out, dict) or "headline" not in out:
                raise LLMError("summary missing headline")
            # Guardrail: drop any sentence containing a number that is not in the data we gave the model.
            allowed = _collect_numbers([stats, top], set())
            rejected: list[str] = []

            def keep(items: Any) -> list[str]:
                good = []
                for s in (items if isinstance(items, list) else [items])[:6]:
                    (good if is_grounded(str(s), allowed) else rejected).append(str(s))
                return good

            headline = keep(out["headline"])
            bullets, actions = keep(out.get("bullets", [])), keep(out.get("actions", []))
            ctx.set_metric("summary_claims_rejected", len(rejected))
            ctx.set_metric("summary_claims_kept", len(headline) + len(bullets) + len(actions))
            if rejected:
                ctx.set_metric("summary_rejected_examples", rejected[:3])
            if not bullets:
                bullets = mock_summary(stats)["bullets"]
            return {"headline": headline[0] if headline else mock_summary(stats)["headline"],
                    "bullets": bullets, "actions": actions[:5] or mock_summary(stats)["actions"],
                    "source": ctx.llm.provider}
        except LLMError as e:
            ctx.count("ai_batch_failures")
            ctx.set_metric("ai_last_error", str(e)[:300])
            return {**mock_summary(stats), "source": "fallback (LLM unavailable)"}

    @wf.task("render_report", deps=("route", "compute_stats", "exec_summary"), description="Write report.md, report.html, decisions.csv")
    def render_report(ctx: RunContext) -> dict:
        stats, decisions, summary = ctx.result("compute_stats"), ctx.result("route"), ctx.result("exec_summary")
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        md_path, html_path, csv_path = ctx.out_dir / "report.md", ctx.out_dir / "report.html", ctx.out_dir / "decisions.csv"
        llm_desc = ctx.llm.describe()
        md_path.write_text(_render_md(stats, decisions, summary, llm_desc), encoding="utf-8")
        html_path.write_text(_render_html(stats, decisions, summary, llm_desc), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["request_id", "priority", "suggestion", "approver", "level", "requester", "department", "type",
                        "vendor", "amount", "age_days", "rule_flags", "ai_risk", "ai_recommendation", "ai_concerns", "ai_summary"])
            for d in decisions:
                w.writerow([d["request_id"], d["priority"], d["suggestion"], d["approver"], d["level"], d["requester"],
                            d["department"], d["type"], d["vendor"], d["amount"], d["age_days"],
                            "; ".join(f"{x['code']}: {x['detail']}" for x in d["rule_flags"]),
                            d["ai"]["risk"], d["ai"]["recommendation"], "; ".join(d["ai"]["concerns"]), d["ai"]["summary"]])
        return {"markdown": str(md_path), "html": str(html_path), "csv": str(csv_path)}

    @wf.task("notify", deps=("route", "render_report"), description="Write one digest per approver to outbox/")
    def notify(ctx: RunContext) -> list[str]:
        decisions, cur = ctx.result("route"), ctx.config["policy"]["currency"]
        outbox = ctx.out_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        per: dict[str, list[dict]] = defaultdict(list)
        for d in decisions:
            per[d["approver"]].append(d)
        paths = []
        for approver, items in per.items():
            lines = [f"Subject: {len(items)} approval request(s) waiting for you", "",
                     f"Hi {approver},", "", "Here is your approval queue, most urgent first:", ""]
            for d in items:
                why = [x["label"] for x in d["rule_flags"]] + d["ai"]["concerns"]
                lines.append(f"- [{SUGGESTION_LABELS[d['suggestion']]}] {d['request_id']} | {d['requester']} | "
                             f"{money(d['amount'], cur)} | {d['vendor']} | waiting {d['age_days']} days")
                if why:
                    lines.append(f"    why: {'; '.join(why)}")
            lines += ["", "Full report: report.html", "", "(Generated by the approval-reporting workflow; AI notes are advisory.)"]
            p = outbox / (re.sub(r"[^A-Za-z0-9]+", "_", approver).strip("_") + ".txt")
            p.write_text("\n".join(lines), encoding="utf-8")
            paths.append(str(p))
        return paths

    return wf


# ------------------------------------------------------------- rendering
def _render_md(stats: dict, decisions: list[dict], summary: dict, llm: dict) -> str:
    cur = stats["currency"]
    L = [f"# Approvals report — as of {stats['as_of']}", "",
         f"**{summary['headline']}**", ""]
    L += [f"- {b}" for b in summary["bullets"]] + ["", "**Recommended actions**", ""] + [f"1. {a}" for a in summary["actions"]]
    L += ["", "## Key numbers", "", "| Metric | Value |", "|---|---|",
          f"| Requests in export | {stats['total_requests']} ({money(stats['total_value'], cur)}) |",
          f"| Pending | {stats['pending_count']} ({money(stats['pending_value'], cur)}) |",
          f"| Needs attention / return | {stats['flagged_count']} / {stats['return_count']} |",
          f"| Fast-track (clean) | {stats['fast_track_count']} |",
          f"| Past {stats['sla_days']}-day SLA | {stats['sla_breaches']} |",
          f"| Avg / median decision time | {stats['avg_cycle_hours']} h / {stats['median_cycle_hours']} h |",
          f"| Approval rate (decided) | {stats['approval_rate_pct']}% |", "",
          "## Queue by approver", "", "| Approver | Pending | Value | Flagged | Oldest (days) |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v['pending']} | {money(v['value'], cur)} | {v['flagged']} | {v['oldest_days']} |" for k, v in stats["by_approver"].items()]
    L += ["", "## Pending requests (priority order)", "",
          "| ID | Suggestion | Approver | Requester | Amount | Age (d) | Why |", "|---|---|---|---|---|---|---|"]
    for d in decisions:
        why = "; ".join([x["label"] for x in d["rule_flags"]] + [f"AI: {c}" for c in d["ai"]["concerns"]]) or "—"
        L.append(f"| {d['request_id']} | {SUGGESTION_LABELS[d['suggestion']]} | {d['approver']} | {d['requester']} | "
                 f"{money(d['amount'], cur)} | {d['age_days']} | {why.replace('|', '/')} |")
    L += ["", f"_AI reviews by {llm['provider']} / {llm['model']}. AI notes are advisory; policy rules and the approver decide._", ""]
    return "\n".join(L)


def _render_html(stats: dict, decisions: list[dict], summary: dict, llm: dict) -> str:
    e, cur = html.escape, stats["currency"]
    pill = {"return_or_reject": "bad", "needs_review": "warn", "fast_track": "ok"}
    rows = []
    for d in decisions:
        why = "".join(f"<li>{e(x['label'])}: <span class=muted>{e(x['detail'])}</span></li>" for x in d["rule_flags"])
        why += "".join(f"<li><b>AI</b>: {e(c)}</li>" for c in d["ai"]["concerns"])
        rows.append(
            f"<tr><td class=mono>{e(d['request_id'])}</td><td><span class='pill {pill[d['suggestion']]}'>{e(SUGGESTION_LABELS[d['suggestion']])}</span></td>"
            f"<td>{e(d['approver'])}<div class=muted>{e(d['level'])}</div></td><td>{e(d['requester'])}<div class=muted>{e(d['department'])}</div></td>"
            f"<td class=num>{e(money(d['amount'], cur))}</td><td class=num>{d['age_days']}</td>"
            f"<td>{e(d['ai']['summary'])}<ul>{why}</ul></td></tr>")
    approvers = "".join(
        f"<tr><td>{e(k)}</td><td class=num>{v['pending']}</td><td class=num>{e(money(v['value'], cur))}</td><td class=num>{v['flagged']}</td><td class=num>{v['oldest_days']}</td></tr>"
        for k, v in stats["by_approver"].items())
    kpis = [("Pending", f"{stats['pending_count']}", money(stats['pending_value'], cur)),
            ("Needs attention", f"{stats['flagged_count']}", f"{stats['return_count']} to return"),
            ("Fast-track", f"{stats['fast_track_count']}", "clean, one-click"),
            ("Past SLA", f"{stats['sla_breaches']}", f"> {stats['sla_days']} days"),
            ("Median decision time", f"{stats['median_cycle_hours']} h", f"avg {stats['avg_cycle_hours']} h")]
    kpi_html = "".join(f"<div class=kpi><div class=muted>{e(a)}</div><div class=big>{e(b)}</div><div class=muted>{e(c)}</div></div>" for a, b, c in kpis)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Approvals report</title><style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--ok:#1f7a4d;--warn:#a15c00;--bad:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1e1e1c;--ink:#ecece8;--muted:#9a9a94;--line:#2f2f2c;--ok:#5cc28f;--warn:#e0a24a;--bad:#f07167}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}} h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 10px}}
.muted{{color:var(--muted);font-size:13px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}} .big{{font-size:24px;font-weight:600}}
.scroll{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;background:var(--card)}} th,td{{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid var(--line)}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}} .num{{text-align:right;white-space:nowrap}} .mono{{font-family:ui-monospace,Consolas,monospace}}
ul{{margin:4px 0 0;padding-left:18px;font-size:13px}} .pill{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;border:1px solid currentColor;white-space:nowrap}}
.ok{{color:var(--ok)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}}
</style></head><body><main>
<h1>Approvals report</h1><div class=muted>As of {e(stats['as_of'])} · {stats['total_requests']} requests in export</div>
<div class="card" style="margin-top:16px"><b>{e(summary['headline'])}</b><ul>{''.join(f'<li>{e(b)}</li>' for b in summary['bullets'])}</ul>
<div style="margin-top:8px"><b>Next actions</b><ol>{''.join(f'<li>{e(a)}</li>' for a in summary['actions'])}</ol></div></div>
<div class=kpis>{kpi_html}</div>
<h2>Queue by approver</h2><div class=scroll><table><tr><th>Approver</th><th class=num>Pending</th><th class=num>Value</th><th class=num>Flagged</th><th class=num>Oldest (days)</th></tr>{approvers}</table></div>
<h2>Pending requests, most urgent first</h2><div class=scroll><table><tr><th>ID</th><th>Suggestion</th><th>Approver</th><th>Requester</th><th class=num>Amount</th><th class=num>Age (d)</th><th>Summary and reasons</th></tr>{''.join(rows)}</table></div>
<p class=muted>AI reviews by {e(llm['provider'])} / {e(llm['model'])}. AI notes are advisory: they can escalate a request but never approve or reject it. Policy rules and the approver decide.</p>
</main></body></html>"""
