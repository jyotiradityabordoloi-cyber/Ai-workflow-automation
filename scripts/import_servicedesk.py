"""Convert a ManageEngine ServiceDesk Plus "Ticket Listing" CSV export into triage JSONL.

The export has a few report-header lines before the real table; we find the row that
starts with "Group" and read from there. The desk's own Category and Priority become
the `label` used to measure classifier accuracy.

    py scripts/import_servicedesk.py "path/to/Ticket Listing.csv" [--out data/real/servicedesk_tickets.jsonl]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

FMT = "%b %d, %Y %I:%M %p"


def slug(category: str) -> str:
    """'Corporate Websites' -> 'websites' style labels: last word, lowercased. Override with --map if needed."""
    words = re.findall(r"[A-Za-z]+", category)
    return words[-1].lower() if words else "other"


def iso(value: str) -> str:
    try:
        return dt.datetime.strptime(value.strip(), FMT).isoformat(timespec="minutes")
    except ValueError:
        return ""


def convert(src: Path, mapping: dict[str, str] | None = None) -> list[dict]:
    mapping = mapping or {}
    with src.open(encoding="utf-8-sig", newline="") as f:
        lines = list(csv.reader(f))
    start = next(i for i, r in enumerate(lines) if r and r[0].strip() == "Group")
    hdr = [h.strip() for h in lines[start]]
    out = []
    for r in lines[start + 1 :]:
        if len(r) < len(hdr) - 1 or not r[1].strip().isdigit():
            continue
        row = dict(zip(hdr, r))
        pri = re.match(r"(P\d)", row.get("Priority", ""))
        raw_cat = row.get("Category", "").strip()
        label = {"category": mapping.get(raw_cat, slug(raw_cat))}
        if pri:
            label["priority"] = pri.group(1)
        label["type"] = "service_request" if "Service Request" in row.get("Template Name", "") else "issue"
        out.append({
            "id": row["Request ID"].strip(),
            "created_at": iso(row.get("Created Time", "")),
            "resolved_at": iso(row.get("Resolved Time", "")),
            "customer": row.get("Department", "").strip(),
            "plan": "",
            "subject": row.get("Subject", "").strip(),
            "body": " ".join(row.get("Description", "").split()),
            "agent_escalate": False,
            "status": row.get("Request Status", "").strip(),
            "overdue": row.get("Overdue Status", "").strip() == "true",
            "first_response_overdue": row.get("First Response Overdue Status", "").strip() == "true",
            "label": label,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="data/real/servicedesk_tickets.jsonl")
    ap.add_argument("--map", action="append", default=[], metavar="'Desk Category=label'",
                    help="override a category mapping, e.g. --map 'Applications=applications'")
    args = ap.parse_args()
    mapping = dict(m.split("=", 1) for m in args.map)
    rows = convert(Path(args.src), mapping)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} tickets to {out}")
    print("categories:", dict(Counter(r["label"]["category"] for r in rows)))
    print("priorities:", dict(Counter(r["label"].get("priority") for r in rows)))


if __name__ == "__main__":
    main()
