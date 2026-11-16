"""Generate a realistic, deterministic approval-requests export for demos and tests.

It contains normal traffic plus planted problems (duplicates, split purchases,
missing receipts, personal spend, an over-limit discount, a vague large
purchase) so you can check that the workflow catches them.

    py scripts/generate_sample_data.py [--out data/approval_requests.csv] [--as-of 2026-11-15]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
from pathlib import Path

FIELDS = [
    "request_id", "submitted_at", "requester", "department", "type", "vendor", "amount",
    "currency", "discount_pct", "receipt_attached", "description", "status", "decided_at", "decided_by",
]

PEOPLE = {
    "Sales": ["Aarav Shah", "Neha Kapoor", "Rohan Gupta"],
    "Marketing": ["Isha Verma", "Kabir Malhotra"],
    "Engineering": ["Sneha Iyer", "Arjun Reddy", "Meera Pillai"],
    "Operations": ["Dev Patel", "Kavya Joshi"],
    "Finance": ["Tanvi Desai"],
}

CATALOG = {
    "expense": (300, 6000, [
        ("Uber", "Cab to client site visit"), ("Zomato", "Working lunch with client team"),
        ("Staples", "Printer paper and stationery"), ("Chai Point", "Snacks for sprint review"),
    ]),
    "travel": (4000, 45000, [
        ("MakeMyTrip", "Flight to Bengaluru for client workshop"), ("Taj Hotels", "Hotel stay for site inspection"),
        ("IRCTC", "Train tickets for vendor audit"),
    ]),
    "purchase": (8000, 180000, [
        ("Dell India", "Laptop replacement for new joiner"), ("Atlassian", "Jira seats annual renewal"),
        ("Amazon Business", "Ergonomic chairs for office"), ("AWS", "Reserved instances for staging"),
    ]),
    "discount": (15000, 250000, [
        ("Skyline Developers", "Bulk booking discount"), ("Greenfield Realty", "Early payment discount"),
        ("Metro Homes", "Loyalty discount on renewal"),
    ]),
}


def make_rows(as_of: dt.date, n_normal: int = 36, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    end = dt.datetime.combine(as_of, dt.time(18, 0))
    rows: list[dict] = []

    def add(**kw):
        row = {f: "" for f in FIELDS}
        row.update(currency="INR", **kw)
        rows.append(row)

    for _ in range(n_normal):
        dept = rng.choice(list(PEOPLE))
        typ = rng.choices(list(CATALOG), weights=[5, 3, 3, 2])[0]
        lo, hi, items = CATALOG[typ]
        vendor, desc = rng.choice(items)
        amount = round(rng.uniform(lo, hi) / 10) * 10
        submitted = end - dt.timedelta(days=rng.uniform(0, 12), hours=rng.uniform(0, 8))
        age_days = (end - submitted).days
        status, decided_at, decided_by = "pending", "", ""
        if age_days >= 2 and rng.random() < 0.7:
            status = "approved" if rng.random() < 0.85 else "rejected"
            decided = submitted + dt.timedelta(hours=rng.uniform(4, 96))
            decided_at, decided_by = decided.isoformat(timespec="minutes"), "manager"
        add(
            submitted_at=submitted.isoformat(timespec="minutes"), requester=rng.choice(PEOPLE[dept]),
            department=dept, type=typ, vendor=vendor, amount=amount,
            discount_pct=rng.choice([3, 5, 7, 8, 10]) if typ == "discount" else "",
            receipt_attached="n/a" if typ == "discount" else "yes",
            description=desc, status=status, decided_at=decided_at, decided_by=decided_by,
        )

    def ts(days_ago: float, hour: int = 11) -> str:
        return (dt.datetime.combine(as_of - dt.timedelta(days=int(days_ago)), dt.time(hour, 15))).isoformat(timespec="minutes")

    pend = dict(status="pending")
    # 1. Duplicate submission (same requester, vendor, amount, two days apart)
    for d in (5, 3):
        add(submitted_at=ts(d), requester="Rohan Gupta", department="Sales", type="expense", vendor="Olive Bistro",
            amount=5450, receipt_attached="yes", description="Client dinner with Skyline Developers team", **pend)
    # 2. Split purchase: three buys just under the Manager limit on the same day
    for i, item in enumerate(["27-inch monitors (batch 1)", "27-inch monitors (batch 2)", "Docking stations"]):
        add(submitted_at=ts(2, 10 + i), requester="Arjun Reddy", department="Engineering", type="purchase",
            vendor="Dell India", amount=24500, receipt_attached="yes", description=item, **pend)
    # 3. Missing receipts
    add(submitted_at=ts(1), requester="Kabir Malhotra", department="Marketing", type="expense", vendor="Chai Point",
        amount=5600, receipt_attached="no", description="Team offsite snacks", **pend)
    add(submitted_at=ts(4), requester="Kavya Joshi", department="Operations", type="travel", vendor="Taj Hotels",
        amount=18200, receipt_attached="no", description="Hotel stay for vendor audit in Pune", **pend)
    # 4. Personal spend
    add(submitted_at=ts(1), requester="Neha Kapoor", department="Sales", type="expense", vendor="Netflix",
        amount=649, receipt_attached="yes", description="Netflix subscription for home", **pend)
    add(submitted_at=ts(2), requester="Dev Patel", department="Operations", type="expense", vendor="Barbeque Nation",
        amount=6200, receipt_attached="yes", description="Family dinner during Pune trip", **pend)
    # 5. Discount above the 10% policy limit
    add(submitted_at=ts(1), requester="Aarav Shah", department="Sales", type="discount", vendor="Skyline Developers",
        amount=210000, discount_pct=18, receipt_attached="n/a",
        description="Year-end discount on bulk booking of 40 units", **pend)
    # 6. Vague, large purchase: no hard rule breaks, but a human (or the LLM) should question it
    add(submitted_at=ts(0), requester="Sneha Iyer", department="Engineering", type="purchase", vendor="TechSource Traders",
        amount=320000, receipt_attached="yes", description="misc tools", **pend)
    # 7. Missing department
    add(submitted_at=ts(6), requester="Meera Pillai", department="", type="purchase", vendor="Amazon Business",
        amount=12800, receipt_attached="yes", description="Whiteboards for project room", **pend)

    rows.sort(key=lambda r: r["submitted_at"])
    for i, r in enumerate(rows, start=1001):
        r["request_id"] = f"APR-{i}"
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/approval_requests.csv")
    ap.add_argument("--as-of", default=dt.date.today().isoformat())
    ap.add_argument("--count", type=int, default=36, help="number of normal requests")
    args = ap.parse_args()
    rows = make_rows(dt.date.fromisoformat(args.as_of), args.count)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} requests to {out}")


if __name__ == "__main__":
    main()
