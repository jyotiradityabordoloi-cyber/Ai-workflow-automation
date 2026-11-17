"""Evaluate the classification graph against a labelled dataset.

    python -m eval.run_eval --dataset eval/datasets/dev.jsonl --split dev

Reports, per field, accuracy next to the "always guess the most common label" baseline, macro-F1
for category, a confusion list, manual-review routing precision/recall, a confidence calibration check
and latency percentiles. Results are written to eval/results/ and served by GET /api/evaluations/latest.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.ai.classification import build_classifier
from app.ai.llm import build_llm
from app.config import get_settings
from app.main import configure_logging

RESULTS = Path(__file__).with_name("results")


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    labels = {w for w, _ in pairs} | {g for _, g in pairs}
    f1s = []
    for lab in labels:
        tp = sum(1 for w, g in pairs if w == lab and g == lab)
        fp = sum(1 for w, g in pairs if w != lab and g == lab)
        fn = sum(1 for w, g in pairs if w == lab and g != lab)
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f1s.append(2 * p * r / (p + r) if p + r else 0)
    return round(100 * sum(f1s) / len(f1s), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="eval/datasets/dev.jsonl")
    ap.add_argument("--split", default="dev", help="dev (used while designing prompts) or test (held out, run once)")
    args = ap.parse_args()
    configure_logging("WARNING")

    rows = [json.loads(x) for x in Path(args.dataset).read_text(encoding="utf-8").splitlines() if x.strip()]
    llm = build_llm(get_settings())
    graph = build_classifier(llm)
    threshold = get_settings().confidence_threshold
    print(f"evaluating {len(rows)} tickets with {llm.model} …")

    preds = []
    started = time.perf_counter()
    for r in rows:
        s = graph.invoke({"subject": r.get("subject", ""), "body": r["body"]})
        manual = any(f["type"] == "manual_review" for f in s["flags"])
        preds.append({"id": r["id"], "label": r["label"], "pred": {k: s["output"][k] for k in ("category", "priority", "sentiment")},
                      "confidence": s["output"]["confidence"], "manual": manual, "error": s.get("error"), "latency_ms": s["latency_ms"]})
    elapsed = time.perf_counter() - started

    fields = {}
    for f in ("category", "priority", "sentiment"):
        pairs = [(p["label"][f], p["pred"][f]) for p in preds if f in p["label"]]
        majority = Counter(w for w, _ in pairs).most_common(1)[0]
        fields[f] = {
            "accuracy_pct": pct(sum(w == g for w, g in pairs), len(pairs)),
            "majority_baseline_pct": pct(majority[1], len(pairs)), "majority_label": majority[0],
            "errors": dict(Counter(f"{w}->{g}" for w, g in pairs if w != g).most_common()),
        }
    fields["category"]["macro_f1"] = macro_f1([(p["label"]["category"], p["pred"]["category"]) for p in preds])

    exp = {p["id"] for p in preds if p["label"].get("expect_manual")}
    got = {p["id"] for p in preds if p["manual"]}
    hi = [p for p in preds if p["confidence"] >= threshold]
    lo = [p for p in preds if p["confidence"] < threshold]
    ok = lambda p: p["pred"]["category"] == p["label"]["category"]  # noqa: E731
    lat = sorted(p["latency_ms"] for p in preds if p["latency_ms"])

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset": Path(args.dataset).name, "split": args.split,
        "n": len(preds), "model": llm.model, "fields": fields,
        "manual_review": {"expected": len(exp), "caught": len(exp & got), "recall_pct": pct(len(exp & got), len(exp)),
                          "extra": sorted(got - exp), "precision_pct": pct(len(exp & got), len(got))},
        "calibration": {"threshold": threshold, "above_n": len(hi), "above_accuracy_pct": pct(sum(map(ok, hi)), len(hi)),
                        "below_n": len(lo), "below_accuracy_pct": pct(sum(map(ok, lo)), len(lo)),
                        "confidence_values": dict(Counter(round(p["confidence"], 2) for p in preds).most_common(6))},
        "latency_ms": {"p50": statistics.median(lat) if lat else None, "p95": lat[int(0.95 * (len(lat) - 1))] if lat else None},
        "llm_failures": sum(1 for p in preds if p["error"]), "wall_clock_s": round(elapsed, 1),
        "predictions": preds,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}_{args.split}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n{args.split.upper()} set · {len(preds)} tickets · {llm.model}")
    for f, m in fields.items():
        extra = f" · macro-F1 {m['macro_f1']}%" if "macro_f1" in m else ""
        print(f"  {f:9} {m['accuracy_pct']:5}%  (always '{m['majority_label']}': {m['majority_baseline_pct']}%){extra}")
        if m["errors"]:
            print(f"            errors: {m['errors']}")
    mr = result["manual_review"]
    print(f"  manual review: caught {mr['caught']}/{mr['expected']} expected · extra {mr['extra'] or 'none'}")
    c = result["calibration"]
    print(f"  calibration: conf>={c['threshold']}: {c['above_n']} tickets, {c['above_accuracy_pct']}% correct · "
          f"below: {c['below_n']} tickets, {c['below_accuracy_pct']}% · values {c['confidence_values']}")
    print(f"  latency p50 {result['latency_ms']['p50']} ms · p95 {result['latency_ms']['p95']} ms · LLM failures {result['llm_failures']}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
