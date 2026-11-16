"""Export the measured results shown on the live demo page to web/showcase.json.

runs/ is not deployed (and may hold private data), so the page reads this small,
reviewed summary instead. Re-run after new evaluation runs:

    py scripts/export_showcase.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    hist = [json.loads(x) for x in (ROOT / "runs" / "history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    hist = [h for h in hist if not h.get("private") and h["status"] == "success" and h.get("llm", {}).get("provider") != "mock"]

    test = [h for h in hist if h.get("profile") == "tickets_teams" and "teams_test" in h.get("input", "")]
    if not test:
        raise SystemExit("no held-out test run found: run `py main.py run tickets --config config/tickets_teams.json --input data/tickets/teams_test.jsonl`")
    t = test[-1]
    dev = [h for h in hist if h.get("profile") == "tickets_teams" and "teams_dev" in h.get("input", "")]
    ev, imp = t["evaluation"], t["impact"]

    def field(f: str) -> dict:
        return {"ai": ev[f"{f}_accuracy_pct"], "baseline": ev[f"{f}_majority_baseline_pct"]}

    appr = [h for h in hist if h["workflow"] == "approval_report"]
    groq = [h for h in appr if h["llm"]["provider"] == "groq"][-1]
    local = [h for h in appr if h["llm"]["provider"] == "ollama"][-1]

    out = {
        "routing": {
            "run_id": t["run_id"], "model": t["llm"]["model"],
            "test_size": ev["labelled"], "dev_size": dev[-1]["evaluation"]["labelled"] if dev else None,
            "category": field("category"), "priority": field("priority"), "sentiment": field("sentiment"),
            "manual_caught": f"{ev['manual_review_caught']}/{ev['manual_review_expected']}",
            "misses": [m for m in ev["misses"] if m["field"] == "category"],
            "impact": {"batch": imp["units"]["ticket"], "manual_min": imp["manual_minutes"],
                       "automated_min": imp["automated_human_minutes"], "machine_s": round(t["total_seconds"]),
                       "saved_pct": imp["human_time_saved_pct"]},
        },
        "approvals": {
            "requests": groq["metrics"]["requests_total"], "machine_s": round(groq["total_seconds"]),
            "manual_min": groq["impact"]["manual_minutes"], "human_min": groq["impact"]["automated_human_minutes"],
            "saved_pct": groq["impact"]["human_time_saved_pct"], "local_s": round(local["total_seconds"]),
        },
    }
    path = ROOT / "web" / "showcase.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {path}: routing {out['routing']['category']['ai']}% on {out['routing']['test_size']} held-out tickets")


if __name__ == "__main__":
    main()
