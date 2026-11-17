"""Load the seeded ticket dataset into PostgreSQL, optionally classifying every ticket with the real LLM.

    python -m app.seed.load --reset --analyze
"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..ai.classification import build_classifier
from ..ai.llm import build_llm
from ..config import get_settings
from ..db import get_engine
from ..main import configure_logging
from ..memory.semantic import build_semantic_memory
from ..models import AuditEvent, Ticket
from ..services.tickets import analyze_ticket, record_opened

SEED = Path(__file__).with_name("tickets.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete all tickets first")
    ap.add_argument("--analyze", action="store_true", help="classify every ticket with the configured LLM")
    args = ap.parse_args()
    configure_logging("WARNING")

    rows = json.loads(SEED.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    settings = get_settings()
    memory = build_semantic_memory(settings.memory_dir, settings.embedding_provider)
    with Session(get_engine()) as db:
        if args.reset:
            db.execute(delete(Ticket))  # analyses, audit events and episodes cascade
            db.commit()
            memory.reset()  # learned corrections and consolidated tickets go; curated KB articles are re-seeded
            print(f"memory reset: {memory.stats()}")
        existing = {t for (t,) in db.query(Ticket.id).all()}
        added = 0
        for r in rows:
            if r["id"] in existing:
                continue
            c = r["customer"]
            db.add(Ticket(id=r["id"], subject=r["subject"], body=r["body"], channel=r["channel"],
                          created_at=now - timedelta(minutes=r["minutesAgo"]), status="new",
                          customer_name=c["name"], customer_company=c["company"], customer_email=c["email"], customer_plan=c["plan"]))
            added += 1
        db.flush()  # tickets must exist before their audit events (FK)
        for r in rows:
            if r["id"] not in existing:
                db.add(AuditEvent(ticket_id=r["id"], actor="system", action="Imported ticket", detail="seed dataset"))
                record_opened(db, db.get(Ticket, r["id"]))
        db.commit()
        print(f"seeded {added} ticket(s)")

        if args.analyze:
            llm = build_llm(settings)
            classifier = build_classifier(llm, memory)
            print(f"classifying with {llm.model} …")
            started = time.perf_counter()
            # oldest first, as tickets would have arrived, so each one can recall the customer's earlier tickets
            ordered = sorted(rows, key=lambda r: -r["minutesAgo"])
            for i, r in enumerate(ordered, 1):
                t = analyze_ticket(db, r["id"], classifier)
                a = t.latest_analysis
                flags = ",".join(f["type"] for f in a.flags) or "-"
                recalled = f" history={len(a.memory['history'])}" if a.memory and a.memory["history"] else ""
                print(f"[{i:2}/{len(rows)}] {t.id} {a.category:15} {a.priority} {a.sentiment:10} conf={a.confidence:.2f} flags={flags}{recalled}"
                      + (f"  ERROR={a.error}" if a.error else ""))
            print(f"done in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
