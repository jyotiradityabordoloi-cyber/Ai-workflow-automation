"""CLI for the AI workflow automation project.

    py main.py run [approvals|tickets] [--provider groq|gemini|openrouter|ollama|mock] [--input FILE] [--as-of YYYY-MM-DD]
    py main.py impact                        # rebuild IMPACT.md from runs/history.jsonl
    py main.py time-manual STEP --items N    # stopwatch for the manual process baseline
    py main.py providers                     # check which LLM providers are reachable
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from awa.env import load_dotenv  # noqa: E402
from awa.llm import LLM, PROVIDERS, LLMError  # noqa: E402
from awa.metrics import compute_impact, load_manual_timings, record_manual_timing, render_impact_md  # noqa: E402
from awa.orchestrator import RunContext  # noqa: E402
from awa.workflows import approval_report, ticket_triage  # noqa: E402

WORKFLOWS = {
    "approvals": {"baseline": "baseline.json", "input": ROOT / "data" / "approval_requests.csv"},
    "tickets": {"baseline": "baseline_tickets.json", "input": ROOT / "data" / "tickets" / "incoming.jsonl",
                "history": ROOT / "data" / "tickets" / "resolved.jsonl"},
}
RUNS = ROOT / "runs"
HISTORY = RUNS / "history.jsonl"
TIMINGS = ROOT / "data" / "manual_timings.jsonl"


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def read_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(x) for x in HISTORY.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_impact() -> Path:
    out = ROOT / "IMPACT.md"
    private = {p.stem for p in (ROOT / "config").glob("tickets*.json") if load_json(p).get("private")}
    out.write_text(render_impact_md(read_history(), private), encoding="utf-8")
    return out


def setup_logging(log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
                        handlers=handlers, force=True)


# ---------------------------------------------------------------- commands
def cmd_run(args: argparse.Namespace) -> int:
    try:
        llm = LLM(args.provider, args.model)
    except LLMError as e:
        print(f"error: {e}")
        return 2
    spec = WORKFLOWS[args.workflow]
    input_path = Path(args.input) if args.input else spec["input"]
    as_of = dt.datetime.combine(dt.date.fromisoformat(args.as_of), dt.time(18, 0)) if args.as_of else dt.datetime.now()
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{args.workflow}-{llm.provider}"
    out_dir = RUNS / run_id
    setup_logging(out_dir / "run.log")
    local = llm.provider in ("ollama", "mock")
    config = {
        "policy": load_json(ROOT / "config" / "policy.json"),
        "tickets": load_json(Path(args.config) if args.config else ROOT / "config" / "tickets.json"),
        "batch_size": args.batch_size or int(os.environ.get("AWA_BATCH_SIZE", 4 if local else 6)),
        "llm_concurrency": args.concurrency or int(os.environ.get("AWA_LLM_CONCURRENCY", 1 if local else 2)),
    }
    logging.info("workflow=%s provider=%s model=%s batch_size=%s concurrency=%s", args.workflow, llm.provider, llm.model,
                 config["batch_size"], config["llm_concurrency"])
    ctx = RunContext(run_id=run_id, out_dir=out_dir, config=config, llm=llm)
    if args.workflow == "tickets":
        hist = config["tickets"].get("history_file")
        history_path = ROOT / hist if hist else spec["history"]
        wf, units_fn = ticket_triage.build_workflow(input_path, history_path), ticket_triage.impact_units
    else:
        wf, units_fn = approval_report.build_workflow(input_path, as_of), None
    run = wf.run(ctx, max_workers=4)
    run["llm"] = llm.describe() | {k: round(v, 2) if isinstance(v, float) else v for k, v in llm.stats.items()}
    run["metrics"] = ctx.metrics
    run["input"] = str(input_path)
    run["as_of"] = as_of.isoformat(timespec="minutes")
    if "evaluate" in ctx.results:
        run["evaluation"] = ctx.results["evaluate"]
    baseline_file = config["tickets"].get("baseline_file", spec["baseline"]) if args.workflow == "tickets" else spec["baseline"]
    run["profile"] = Path(args.config).stem if args.config else "default"
    run["private"] = bool(config["tickets"].get("private")) if args.workflow == "tickets" else False
    run["impact"] = compute_impact(run, load_json(ROOT / "config" / baseline_file), load_manual_timings(TIMINGS),
                                   units_fn(ctx.metrics) if units_fn else None)
    (out_dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    RUNS.mkdir(exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")
    impact_path = write_impact()

    imp = run["impact"]
    print("\n" + "=" * 64)
    print(f"Run {run_id}: {run['status'].upper()} in {run['total_seconds']} s")
    if run["status"] == "success":
        print(f"Report:  {ctx.results['render_report']['html']}")
    ev = run.get("evaluation") or {}
    if ev.get("labelled"):
        print(f"Accuracy on {ev['labelled']} labelled tickets (category target {ev['target_pct']}%): " + ", ".join(
            f"{f} {ev[f + '_accuracy_pct']}% (always-most-common {ev[f + '_majority_baseline_pct']}%)" for f in ev["fields"]))
    print(f"Impact:  {impact_path}")
    print(f"Human time: manual {imp['manual_minutes']} min -> automated {imp['automated_human_minutes']} min "
          f"(saved {imp['human_minutes_saved']} min, {imp['human_time_saved_pct']}%)")
    print(f"Per month: {imp['monthly']['hours_saved']} h saved (~{imp['monthly']['currency']} {imp['monthly']['value']:,})")
    if ctx.metrics.get("ai_batch_failures"):
        print(f"WARNING: {ctx.metrics['ai_batch_failures']} LLM call(s) failed: {ctx.metrics.get('ai_last_error')}")
    print("=" * 64)
    return 0 if run["status"] == "success" else 1


def cmd_impact(_: argparse.Namespace) -> int:
    print(f"wrote {write_impact()}")
    return 0


def cmd_time_manual(args: argparse.Namespace) -> int:
    steps = {s["id"]: s for s in load_json(ROOT / "config" / WORKFLOWS[args.workflow]["baseline"])["manual_steps"]}
    if args.step not in steps:
        print(f"unknown step '{args.step}'. Choose from: {', '.join(steps)}")
        return 2
    s = steps[args.step]
    print(f"Timing manual step: {s['name']}  ({args.items} {s['per']}(s))")
    input("Press Enter to START the stopwatch... ")
    t0 = time.perf_counter()
    input("Working. Press Enter when DONE... ")
    secs = time.perf_counter() - t0
    rec = record_manual_timing(TIMINGS, args.step, args.items, secs, args.note)
    print(f"recorded {rec['seconds']} s for {args.items} unit(s) = {secs / args.items / 60:.2f} min per {s['per']}")
    print("Measured timings now override the estimate. Run `py main.py impact` to refresh IMPACT.md.")
    return 0


def cmd_providers(_: argparse.Namespace) -> int:
    for name, spec in PROVIDERS.items():
        if name == "mock":
            continue
        key = spec["key_env"]
        if key and not os.environ.get(key):
            print(f"{name:11} skipped  ({key} not set)")
            continue
        try:
            llm = LLM(name, timeout=30)
            t0 = time.perf_counter()
            status = llm.ping()
            print(f"{name:11} {status:8} {llm.model}  ({time.perf_counter() - t0:.1f}s)")
        except LLMError as e:
            print(f"{name:11} FAILED   {str(e)[:120]}")
    return 0


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="AI workflow automation: approval reporting")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a workflow: approvals (default) or tickets")
    r.add_argument("workflow", nargs="?", choices=list(WORKFLOWS), default="approvals")
    r.add_argument("--input", default=None, help="input file (default depends on workflow)")
    r.add_argument("--config", default=None, help="tickets: profile config, e.g. config/tickets_teams.json")
    r.add_argument("--provider", choices=list(PROVIDERS), default=None, help="default: LLM_PROVIDER env or groq")
    r.add_argument("--model", default=None)
    r.add_argument("--as-of", default=None, help="report date YYYY-MM-DD (default: now)")
    r.add_argument("--batch-size", type=int, default=None)
    r.add_argument("--concurrency", type=int, default=None)
    r.set_defaults(func=cmd_run)

    sub.add_parser("impact", help="rebuild IMPACT.md").set_defaults(func=cmd_impact)

    t = sub.add_parser("time-manual", help="stopwatch for a manual baseline step")
    t.add_argument("step")
    t.add_argument("--workflow", choices=list(WORKFLOWS), default="approvals")
    t.add_argument("--items", type=int, default=1, help="how many units (requests, approvers...) you handled")
    t.add_argument("--note", default="")
    t.set_defaults(func=cmd_time_manual)

    sub.add_parser("providers", help="check LLM provider connectivity").set_defaults(func=cmd_providers)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
