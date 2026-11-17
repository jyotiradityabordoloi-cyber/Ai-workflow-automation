"""Semantic memory: what the support team knows, recalled by meaning (cosine similarity over embeddings).

Two collections, both keyed by the embedder's name so vectors from different models never mix:

* ``knowledge``: resolved problems and how they were fixed. Seeded from ``seed/knowledge.json`` (KB-xxx) and
  grown by consolidation: every ticket an agent resolves is added under its own id (SF-xxxx). The vector is the
  problem (subject + message) so a new ticket finds problems like itself; the resolution rides along as metadata.
* ``corrections``: tickets where an agent overrode the AI's category or priority. A near-identical new ticket is
  shown the correction, so the classifier stops repeating a mistake a human already fixed, without retraining.

Two interchangeable vector stores sit behind a four-method ``VectorIndex``:

* ``ChromaIndex``: a local folder (``backend/.memory``), embeddings computed in-process. Local development.
* ``QdrantIndex``: Qdrant (Cloud or self-hosted). With ``embedder=None`` Qdrant Cloud Inference computes the
  embeddings server-side (all-MiniLM-L6-v2, free on the free tier), so the API server needs no model and no disk.

PostgreSQL stays the source of truth: everything learned here can be rebuilt from it (``memory/rebuild.py``).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .embeddings import Embedder

log = logging.getLogger("supportflow.memory")

KNOWLEDGE_SEED = Path(__file__).resolve().parents[1] / "seed" / "knowledge.json"
CLOUD_MODEL = "sentence-transformers/all-minilm-l6-v2"  # Qdrant Cloud Inference, 384 dimensions, free
CLOUD_DIM = 384

Hit = tuple[str, float, dict, str]  # id, similarity, metadata, document


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


# ---------------------------------------------------------------- vector stores
class VectorIndex(Protocol):
    def upsert(self, ids: list[str], docs: list[str], metas: list[dict]) -> None: ...
    def query(self, text: str, n: int) -> list[Hit]: ...
    def all(self) -> list[tuple[str, dict]]: ...
    def count(self) -> int: ...
    def clear(self) -> None: ...


class ChromaIndex:
    def __init__(self, client: Any, name: str, embedder: Embedder) -> None:
        self.client, self.name, self.embedder = client, name, embedder
        self._open()

    def _open(self) -> None:
        self.coll = self.client.get_or_create_collection(self.name, metadata={"hnsw:space": "cosine"}, embedding_function=None)

    def upsert(self, ids: list[str], docs: list[str], metas: list[dict]) -> None:
        self.coll.upsert(ids=ids, documents=docs, embeddings=self.embedder.embed(docs), metadatas=metas)

    def query(self, text: str, n: int) -> list[Hit]:
        res = self.coll.query(query_embeddings=self.embedder.embed([text]), n_results=n, include=["metadatas", "distances", "documents"])
        # Chroma returns cosine *distance*
        return [(i, round(max(0.0, 1.0 - d), 2), m, doc)
                for i, d, m, doc in zip(res["ids"][0], res["distances"][0], res["metadatas"][0], res["documents"][0])]

    def all(self) -> list[tuple[str, dict]]:
        got = self.coll.get(include=["metadatas"])
        return list(zip(got["ids"], got["metadatas"]))

    def count(self) -> int:
        return self.coll.count()

    def clear(self) -> None:
        self.client.delete_collection(self.name)
        self._open()


class QdrantIndex:
    """Qdrant collection. Point ids must be ints or UUIDs, so ours (KB-101, SF-1042) become UUIDv5 and live in the payload."""

    def __init__(self, client: Any, name: str, embedder: Embedder | None) -> None:
        from qdrant_client import models

        self.client, self.name, self.embedder, self.m = client, name, embedder, models
        self._open()

    def _dim(self) -> int:
        return getattr(self.embedder, "dim", CLOUD_DIM) if self.embedder else CLOUD_DIM

    def _open(self) -> None:
        if not self.client.collection_exists(self.name):
            self.client.create_collection(self.name, vectors_config=self.m.VectorParams(size=self._dim(), distance=self.m.Distance.COSINE))

    def _vectors(self, docs: list[str]) -> list[Any]:
        if self.embedder is None:  # Qdrant Cloud Inference embeds server-side
            return [self.m.Document(text=d, model=CLOUD_MODEL) for d in docs]
        return self.embedder.embed(docs)

    def upsert(self, ids: list[str], docs: list[str], metas: list[dict]) -> None:
        points = [self.m.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, i)), vector=v, payload={**meta, "key": i, "document": d})
                  for i, d, meta, v in zip(ids, docs, metas, self._vectors(docs))]
        self.client.upsert(self.name, points=points, wait=True)

    def query(self, text: str, n: int) -> list[Hit]:
        res = self.client.query_points(self.name, query=self._vectors([text])[0], limit=n, with_payload=True)
        out = []
        for p in res.points:
            meta = dict(p.payload or {})
            key, doc = meta.pop("key"), meta.pop("document", "")
            out.append((key, round(max(0.0, float(p.score)), 2), meta, doc))  # Qdrant returns cosine *similarity*
        return out

    def all(self) -> list[tuple[str, dict]]:
        rows, offset = [], None
        while True:
            points, offset = self.client.scroll(self.name, limit=256, offset=offset, with_payload=True)
            rows += [(p.payload["key"], {k: v for k, v in p.payload.items() if k not in ("key", "document")}) for p in points]
            if offset is None:
                return rows

    def count(self) -> int:
        return self.client.count(self.name, exact=True).count

    def clear(self) -> None:
        self.client.delete_collection(self.name)
        self._open()


# ---------------------------------------------------------------- memory
class SemanticMemory:
    def __init__(self, knowledge: VectorIndex, corrections: VectorIndex, embedder_name: str) -> None:
        self.knowledge, self.corrections, self.embedder_name = knowledge, corrections, embedder_name

    @classmethod
    def chroma(cls, client: Any, embedder: Embedder, namespace: str = "") -> SemanticMemory:
        e = embedder.name
        return cls(ChromaIndex(client, f"{namespace}knowledge_{e}", embedder), ChromaIndex(client, f"{namespace}corrections_{e}", embedder), e)

    @classmethod
    def qdrant(cls, client: Any, embedder: Embedder | None, namespace: str = "") -> SemanticMemory:
        e = embedder.name if embedder else "minilm"  # cloud inference runs the same all-MiniLM-L6-v2 model
        return cls(QdrantIndex(client, f"{namespace}knowledge_{e}", embedder), QdrantIndex(client, f"{namespace}corrections_{e}", embedder), e)

    # ------------------------------------------------------------ knowledge
    def upsert_knowledge(self, items: list[KnowledgeItem]) -> None:
        if not items:
            return
        self.knowledge.upsert(
            [i.id for i in items], [_problem(i.subject, i.body) for i in items],
            [{"subject": i.subject, "body": i.body, "resolution": i.resolution, "category": i.category,
              "source": i.source, "resolved_at": i.resolved_at} for i in items])

    def search_knowledge(self, text: str, k: int = 3, min_similarity: float = 0.0, exclude_id: str | None = None) -> list[dict]:
        hits = _query(self.knowledge, text, k, exclude_id)
        return [{"id": i, "similarity": s, **_knowledge_meta(m)} for i, s, m, _ in hits if s >= min_similarity]

    def list_knowledge(self) -> list[dict]:
        items = [{"id": i, "similarity": None, **_knowledge_meta(m)} for i, m in self.knowledge.all()]
        # newest consolidated tickets first, then the curated articles in id order
        return sorted(items, key=lambda x: (x["source"] != "ticket", -_ts(x["resolvedAt"]), x["id"]))

    # ------------------------------------------------------------ corrections
    def add_correction(self, ticket_id: str, subject: str, body: str, ai: dict[str, str], agent: dict[str, str]) -> None:
        self.corrections.upsert(
            [ticket_id], [_problem(subject, body)],
            [{"ai_category": ai["category"], "ai_priority": ai["priority"], "category": agent["category"],
              "priority": agent["priority"], "at": datetime.now(timezone.utc).isoformat()}])

    def search_corrections(self, text: str, k: int = 2, min_similarity: float = 0.0, exclude_id: str | None = None) -> list[dict]:
        hits = _query(self.corrections, text, k, exclude_id)
        return [{"ticketId": i, "similarity": s, "excerpt": doc[:240],
                 "ai": {"category": m["ai_category"], "priority": m["ai_priority"]},
                 "agent": {"category": m["category"], "priority": m["priority"]}}
                for i, s, m, doc in hits if s >= min_similarity]

    # ------------------------------------------------------------ housekeeping
    def stats(self) -> dict[str, Any]:
        return {"embedder": self.embedder_name, "knowledge": self.knowledge.count(), "corrections": self.corrections.count()}

    def reset(self) -> None:
        """Drop learned memory: corrections and consolidated tickets. Curated KB articles are re-seeded."""
        self.knowledge.clear()
        self.corrections.clear()
        seed_knowledge(self)


def _query(index: VectorIndex, text: str, k: int, exclude_id: str | None) -> list[Hit]:
    n = index.count()
    if n == 0 or not text.strip():
        return []
    hits = index.query(text, min(k + (1 if exclude_id else 0), n))
    return [h for h in hits if h[0] != exclude_id][:k]


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
    log.info("seeded %d knowledge articles into semantic memory (%s)", len(rows), memory.embedder_name)
    return len(rows)


def build_semantic_memory(settings: Any) -> SemanticMemory:
    """Open the configured store: ``memory_backend`` chroma (local folder) or qdrant (``qdrant_url``)."""
    from .embeddings import build_embedder

    if settings.memory_backend == "qdrant":
        from qdrant_client import QdrantClient

        if not settings.qdrant_url:
            raise ValueError("MEMORY_BACKEND=qdrant needs QDRANT_URL (and QDRANT_API_KEY for Qdrant Cloud)")
        cloud = settings.embedding_provider == "qdrant-cloud"
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, cloud_inference=cloud, timeout=30)
        return SemanticMemory.qdrant(client, None if cloud else build_embedder(settings.embedding_provider))

    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.PersistentClient(path=str(settings.memory_dir), settings=ChromaSettings(anonymized_telemetry=False))
    return SemanticMemory.chroma(client, build_embedder(settings.embedding_provider))
