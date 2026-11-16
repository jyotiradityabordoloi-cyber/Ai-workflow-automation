"""Impact measurement: manual baseline vs. measured automated runs.

Numbers come from two places, and every output says which is which:
  * measured  - automated run timings, LLM calls/tokens (recorded by the orchestrator),
                and any manual timings you record with `main.py time-manual`
  * estimate  - per-step minutes in config/baseline.json that nobody has timed yet
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_manual_timings(path: Path) -> dict[str, dict[str, float]]:
    """Return {step_id: {"minutes_per_unit": x, "samples": n, "units": u}} from a JSONL log."""
    if not path.exists():
        return {}
    acc: dict[str, dict[str, float]] = defaultdict(lambda: {"seconds": 0.0, "units": 0.0, "samples": 0})
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        a = acc[rec["step"]]
        a["seconds"] += float(rec["seconds"])
        a["units"] += float(rec.get("items") or 1)
        a["samples"] += 1
    return {k: {"minutes_per_unit": v["seconds"] / v["units"] / 60, "samples": int(v["samples"]), "units": v["units"]}
            for k, v in acc.items() if v["units"]}


def record_manual_timing(path: Path, step: str, items: int, seconds: float, note: str = "") -> dict:
    rec = {"step": step, "items": items, "seconds": round(seconds, 1), "note": note,
           "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def compute_impact(run: dict[str, Any], baseline: dict[str, Any], timings: dict[str, dict[str, float]],
                   units: dict[str, float] | None = None) -> dict[str, Any]:
    m = run.get("metrics", {})
    units = units or {
        "run": 1,
        "request": m.get("requests_total", 0),
        "pending_request": m.get("requests_pending", 0),
        "approver": m.get("approvers_notified", 0),
        "flagged_request": m.get("flagged_requests", 0),
    }

    def price(steps: list[dict]) -> list[dict]:
        out = []
        for s in steps:
            t = timings.get(s["id"])
            per_unit = t["minutes_per_unit"] if t else float(s["minutes"])
            n = units.get(s["per"], 0)
            out.append({
                "id": s["id"], "name": s["name"], "per": s["per"], "units": n,
                "minutes_per_unit": round(per_unit, 2),
                "source": f"measured (n={t['samples']})" if t else "estimate",
                "minutes": round(per_unit * n, 1),
            })
        return out

    manual = price(baseline["manual_steps"])
    human = price(baseline["automated_human_steps"])
    manual_total = round(sum(s["minutes"] for s in manual), 1)
    human_total = round(sum(s["minutes"] for s in human), 1)
    machine_min = round(run["total_seconds"] / 60, 2)
    saved = round(manual_total - human_total, 1)
    rpm = float(baseline.get("runs_per_month", 4.33))
    hourly = float(baseline.get("loaded_hourly_cost", 0))
    all_steps = manual + human
    return {
        "units": units,
        "manual_steps": manual,
        "automated_human_steps": human,
        "manual_minutes": manual_total,
        "automated_human_minutes": human_total,
        "automated_machine_minutes": machine_min,
        "human_minutes_saved": saved,
        "human_time_saved_pct": round(100 * saved / manual_total, 1) if manual_total else None,
        "turnaround_manual_minutes": manual_total,
        "turnaround_automated_minutes": round(machine_min + human_total, 1),
        "monthly": {
            "runs": rpm,
            "hours_saved": round(saved * rpm / 60, 1),
            "value": round(saved * rpm / 60 * hourly),
            "currency": baseline.get("currency", ""),
        },
        "baseline_measured_steps": sum(s["source"] != "estimate" for s in all_steps),
        "baseline_estimated_steps": sum(s["source"] == "estimate" for s in all_steps),
    }


# ------------------------------------------------------------------ report
WORKFLOW_TITLES = {"approval_report": "Approval reporting", "ticket_triage": "Support ticket triage (sample SaaS tickets)",
                   "ticket_triage:tickets_teams": "Team-routing triage (Nimbus3D demo)"}


def _key(h: dict[str, Any]) -> str:
    p = h.get("profile", "default")
    return h["workflow"] if p == "default" else f"{h['workflow']}:{p}"


def _workflow_section(runs: list[dict[str, Any]]) -> list[str]:
    last = runs[-1]
    imp, llm, m = last["impact"], last.get("llm", {}), last.get("metrics", {})
    cur = imp["monthly"]["currency"]
    name = last["workflow"]
    L = [f"## {WORKFLOW_TITLES.get(_key(last), _key(last))}", "",
         f"Latest run `{last['run_id']}` at {last['started_at']}, status **{last['status']}**. "
         f"LLM: {llm.get('provider')} / {llm.get('model')}: {llm.get('calls', 0)} calls, "
         f"{llm.get('prompt_tokens', 0) + llm.get('completion_tokens', 0):,} tokens, {llm.get('failed_calls', 0)} failed, "
         "API cost 0 (free tier / local).", ""]
    if name == "approval_report":
        L += [f"- {m.get('requests_total', 0)} requests, {m.get('requests_pending', 0)} pending, {m.get('flagged_requests', 0)} flagged, "
              f"{m.get('fast_track_requests', 0)} fast-track, {m.get('approvers_notified', 0)} approvers",
              f"- AI caught {m.get('ai_only_catches', 0)} request(s) the rules missed; "
              f"{m.get('summary_claims_rejected', 0)} AI summary sentence(s) dropped for unverifiable numbers", ""]
    ev = last.get("evaluation") or {}
    if name == "ticket_triage":
        L += [f"- {m.get('tickets_total', 0)} tickets: {m.get('ai_assisted', 0)} AI-assisted, {m.get('manual_review', 0)} manual review, "
              f"{m.get('senior_queue', 0)} senior queue, {m.get('manager_review', 0)} manager review, {m.get('escalations', 0)} escalations, "
              f"{m.get('drafts_written', 0)} drafts", ""]
        if ev.get("labelled"):
            verdict = "meets" if ev["category_meets_target"] else "**below**"
            fields = ev.get("fields") or ["category", "priority", "sentiment"]
            L += [f"### Classifier accuracy (measured on {ev['labelled']} labelled tickets, input `{last.get('input', '')}`)", "",
                  "| Field | Accuracy | Always-guess-most-common |", "|---|---:|---:|"]
            for f in fields:
                extra = f" ({verdict} the {ev['target_pct']}% target)" if f == "category" else ""
                L.append(f"| {f.title()} | **{ev.get(f + '_accuracy_pct')}%**{extra} | {ev.get(f + '_majority_baseline_pct', '—')}% |")
            if ev.get("manual_review_expected"):
                L.append(f"| Low-confidence tickets sent to manual review | {ev['manual_review_caught']}/{ev['manual_review_expected']} | |")
            L.append("")
            if ev.get("manual_review_extra"):
                L += [f"Also sent to manual review (not expected): {', '.join(ev['manual_review_extra'])}.", ""]
            for f in fields:
                conf = {k: v for k, v in (ev.get(f + "_confusion") or {}).items() if k.split("->")[0] != k.split("->")[1]}
                if conf:
                    L += [f"{f.title()} errors (label→AI): " + ", ".join(f"{k.replace('->', '→')} ×{v}" for k, v in conf.items()) + ".", ""]
            if ev.get("misses") and not any(ev.get(f + "_confusion") for f in fields):
                L += ["Misclassifications: " + "; ".join(f"{x['ticket']} {x['field']} {x['expected']}→{x['got']}" for x in ev["misses"][:15]) + ".", ""]
    L += ["| | Manual process | Automated |", "|---|---:|---:|",
          f"| Human time | {imp['manual_minutes']} min | {imp['automated_human_minutes']} min |",
          f"| Machine time (measured) | 0 | {imp['automated_machine_minutes']} min |",
          f"| **Human time saved** | | **{imp['human_minutes_saved']} min ({imp['human_time_saved_pct']}%)** |", "",
          f"**Per month** ({imp['monthly']['runs']} runs): **{imp['monthly']['hours_saved']} hours saved**, "
          f"about **{cur} {imp['monthly']['value']:,}** at the loaded hourly cost in the baseline file.", "",
          "| Step | Per | Units | Min/unit | Source | Minutes |", "|---|---|---:|---:|---|---:|"]
    for s in imp["manual_steps"]:
        L.append(f"| Manual: {s['name']} | {s['per']} | {s['units']} | {s['minutes_per_unit']} | {s['source']} | {s['minutes']} |")
    for s in imp["automated_human_steps"]:
        L.append(f"| Automated, human: {s['name']} | {s['per']} | {s['units']} | {s['minutes_per_unit']} | {s['source']} | {s['minutes']} |")
    L += ["", "Task timings (measured):", "", "| Task | Depends on | Status | Start (s) | Duration (s) | Attempts |", "|---|---|---|---:|---:|---:|"]
    for t in last["tasks"]:
        L.append(f"| {t['name']} | {', '.join(t['deps']) or '—'} | {t['status']} | {t['start_offset']} | {t['seconds']} | {t['attempts']} |")
    L += ["", "All runs:", "", "| Run | Provider / model | Status | Machine (s) | Human min saved |", "|---|---|---|---:|---:|"]
    for h in runs:
        hl = h.get("llm", {})
        L.append(f"| {h['run_id']} | {hl.get('provider')} / {hl.get('model')} | {h['status']} | {h['total_seconds']} | {h['impact']['human_minutes_saved']} |")
    real = [h for h in runs if h.get("llm", {}).get("provider") != "mock" and h["status"] == "success"]
    if real:
        L += ["", f"Across {len(real)} successful real-LLM run(s): **{sum(h['impact']['human_minutes_saved'] for h in real) / 60:.1f} hours saved to date**."]
    est = imp["baseline_estimated_steps"]
    L += ["", f"Baseline: {imp['baseline_measured_steps']} step(s) measured, {est} still estimates.", ""]
    return L


def render_impact_md(history: list[dict[str, Any]], exclude_profiles: set[str] | frozenset[str] = frozenset()) -> str:
    # Runs on private (e.g. client) data never appear in the shareable report.
    history = [h for h in history if not h.get("private") and h.get("profile", "default") not in exclude_profiles]
    if not history:
        return "# Impact report\n\nNo runs yet. Run `py main.py run` first.\n"
    by_wf: dict[str, list[dict[str, Any]]] = {}
    for h in history:
        by_wf.setdefault(_key(h), []).append(h)
    L = ["# Impact report", "",
         f"_Generated {time.strftime('%Y-%m-%d %H:%M')} from {len(history)} recorded run(s) in `runs/history.jsonl`._", "",
         "| Workflow | Latest model | Human time saved / run | Hours saved / month |", "|---|---|---:|---:|"]
    for name, runs in by_wf.items():
        imp, llm = runs[-1]["impact"], runs[-1].get("llm", {})
        L.append(f"| {WORKFLOW_TITLES.get(name, name)} | {llm.get('model')} | {imp['human_minutes_saved']} min ({imp['human_time_saved_pct']}%) | {imp['monthly']['hours_saved']} |")
    L.append("")
    for runs in by_wf.values():
        L += _workflow_section(runs)
    L += ["## How these numbers were produced", "",
          "- **Measured:** task durations, run time, LLM calls/tokens, item counts, and classifier accuracy against labelled tickets.",
          "- **Estimated until timed:** per-step manual minutes in `config/baseline*.json`. Replace them by timing the real manual work: "
          "`py main.py time-manual <step_id> [--workflow tickets] --items N`. Measured averages override estimates automatically.",
          "- Human time saved = manual minutes − the human minutes that remain after automation (reviewing, editing, confirming). "
          "Decisions stay with people, so decision time is excluded on both sides."]
    return "\n".join(L) + "\n"
