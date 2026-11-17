"""Semantic memory: what the support team knows, recalled by meaning (ChromaDB, cosine similarity).

Two collections, both keyed by the embedder's name so vectors from different models never mix:

* ``knowledge``: resolved problems and how they were fixed. Seeded from ``seed/knowledge.json`` (KB-xxx) and
  grown by consolidation: every ticket an agent resolves is added under its own id (SF-xxxx). The vector is the
  problem (subject + message) so a new ticket finds problems like itself; the resolution rides along as metadata.
* ``corrections``: tickets where an agent overrode the AI's category or priority. A near-identical new ticket is
  shown the correction, so the classifier stops repeating a mistake a human already fixed, without retraining.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .embeddings import Embedder

log = logging.getLogger("supportflow.memory")

KNOWLEDGE_SEED = Path(__file__).resolve().parents[1] / "seed" / "knowledge.json"
_SPACE = {"hnsw:space": "cosine"}


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    subject: str
    body: str
    resolution: str
    category: str
    source: str = "kb"  # kb = curated article, ticket = consolidated from a resolved ticket
    resolved_at: str = ""


def _problem(subject: str, body: str) -> str:
    return ". ".join(p for p in (subject.strip(), body.strip()) if p)


def _similarity(distance: float) -> float:
    return round(max(0.0, 1.0 - distance), 2)  # cosine distance -> similarity


class SemanticMemory:
    def __init__(self, client: Any, embedder: Embedder, namespace: str = "") -> None:
        self.client, self.embedder, self.namespace = client, embedder, namespace
        self._open()

    def _open(self) -> None:
        ns, e = self.namespace, self.embedder.name
        self.knowledge = self.client.get_or_create_collection(f"{ns}knowledge_{e}", metadata=_SPACE, embedding_function=None)
        self.corrections = self.client.get_or_create_collection(f"{ns}corrections_{e}", metadata=_SPACE, embedding_function=None)

    # ------------------------------------------------------------ knowledge
    def upsert_knowledge(self, items: list[KnowledgeItem]) -> None:
        if not items:
            return
        docs = [_problem(i.subject, i.body) for i in items]
        self.knowledge.upsert(
            ids=[i.id for i in items], documents=docs, embeddings=self.embedder.embed(docs),
            metadatas=[{"subject": i.subject, "body": i.body, "resolution": i.resolution, "category": i.category,
                        "source": i.source, "resolved_at": i.resolved_at} for i in items])

    def search_knowledge(self, text: str, k: int = 3, min_similarity: float = 0.0, exclude_id: str | None = None) -> list[dict]:
        hits = self._query(self.knowledge, text, k, exclude_id)
        return [{"id": i, "similarity": s, **_knowledge_meta(m)} for i, s, m, _ in hits if s >= min_similarity]

    def list_knowledge(self) -> list[dict]:
        got = self.knowledge.get(include=["metadatas"])
        items = [{"id": i, "similarity": None, **_knowledge_meta(m)} for i, m in zip(got["ids"], got["metadatas"])]
        # newest consolidated tickets first, then the curated articles in id order
        return sorted(items, key=lambda x: (x["source"] != "ticket", -_ts(x["resolvedAt"]), x["id"]))

    # ------------------------------------------------------------ corrections
    def add_correction(self, ticket_id: str, subject: str, body: str, ai: dict[str, str], agent: dict[str, str]) -> None:
        doc = _problem(subject, body)
        self.corrections.upsert(
            ids=[ticket_id], documents=[doc], embeddings=self.embedder.embed([doc]),
            metadatas=[{"ai_category": ai["category"], "ai_priority": ai["priority"], "category": agent["category"],
                        "priority": agent["priority"], "at": datetime.now(timezone.utc).isoformat()}])

    def search_corrections(self, text: str, k: int = 2, min_similarity: float = 0.0, exclude_id: str | None = None) -> list[dict]:
        hits = self._query(self.corrections, text, k, exclude_id)
        return [{"ticketId": i, "similarity": s, "excerpt": doc[:240],
                 "ai": {"category": m["ai_category"], "priority": m["ai_priority"]},
                 "agent": {"category": m["category"], "priority": m["priority"]}}
                for i, s, m, doc in hits if s >= min_similarity]

    # ------------------------------------------------------------ housekeeping
    def stats(self) -> dict[str, Any]:
        return {"embedder": self.embedder.name, "knowledge": self.knowledge.count(), "corrections": self.corrections.count()}

    def reset(self) -> None:
        """Drop learned memory: corrections and consolidated tickets. Curated KB articles are re-seeded."""
        for c in (self.knowledge, self.corrections):
            self.client.delete_collection(c.name)
        self._open()
        seed_knowledge(self)

    def _query(self, coll: Any, text: str, k: int, exclude_id: str | None) -> list[tuple[str, float, dict, str]]:
        n = coll.count()
        if n == 0 or not text.strip():
            return []
        res = coll.query(query_embeddings=self.embedder.embed([text]), n_results=min(k + (1 if exclude_id else 0), n),
                         include=["metadatas", "distances", "documents"])
        rows = zip(res["ids"][0], res["distances"][0], res["metadatas"][0], res["documents"][0])
        return [(i, _similarity(d), m, doc) for i, d, m, doc in rows if i != exclude_id][:k]


def _knowledge_meta(m: dict) -> dict:
    return {"subject": m["subject"], "body": m.get("body", ""), "resolution": m["resolution"], "category": m["category"],
            "source": m.get("source", "kb"), "resolvedAt": m.get("resolved_at") or None}


def _ts(iso: str | None) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def seed_knowledge(memory: SemanticMemory, path: Path = KNOWLEDGE_SEED) -> int:
    """Load the curated KB articles if the collection is empty. Returns how many were added."""
    if memory.knowledge.count():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    memory.upsert_knowledge([KnowledgeItem(id=r["id"], subject=r["subject"], body=r["body"], resolution=r["resolution"],
                                           category=r["category"], source="kb") for r in rows])
    log.info("seeded %d knowledge articles into semantic memory (%s)", len(rows), memory.embedder.name)
    return len(rows)


def build_semantic_memory(memory_dir: Path, provider: str) -> SemanticMemory:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    from .embeddings import build_embedder

    client = chromadb.PersistentClient(path=str(memory_dir), settings=ChromaSettings(anonymized_telemetry=False))
    memory = SemanticMemory(client, build_embedder(provider))
    seed_knowledge(memory)
    return memory
