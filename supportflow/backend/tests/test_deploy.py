"""Deployment concerns: rebuilding memory from PostgreSQL, rate limits, hosted-Postgres URLs, Qdrant Cloud Inference."""
from types import SimpleNamespace

from app.ai.llm import FakeLLM
from app.config import Settings
from app.memory.rebuild import ensure_ready, rebuild_learned
from app.memory.semantic import CLOUD_MODEL, QdrantIndex

from .conftest import AGENT, new_ticket

BUG_P2 = {"language": "en", "category": "bug", "priority": "P2", "sentiment": "neutral", "confidence": 0.81, "summary": "Broken."}
SSO = "Our SSO login keeps looping back to the sign-in page for everyone since we rotated the Okta certificate."


def test_a_wiped_vector_store_is_rebuilt_from_postgres(make_client, memory, session_factory):
    with make_client(FakeLLM([BUG_P2, BUG_P2])) as c:
        a = new_ticket(c, SSO, subject="SSO loop")
        c.post(f"/api/tickets/{a['id']}/decision", json={"category": "account", "priority": "P1"}, headers=AGENT)
        b = new_ticket(c, "Please resend the October invoice with our VAT number on it.", subject="VAT invoice")
        c.post(f"/api/tickets/{b['id']}/decision", json={"accept": True}, headers=AGENT)
        c.post(f"/api/tickets/{b['id']}/resolve", json={"resolution": "Added the VAT ID and re-sent the invoice."}, headers=AGENT)
    before = memory.stats()
    assert before["knowledge"] == 22 and before["corrections"] == 1

    memory.knowledge.clear()   # e.g. the free Qdrant cluster was deleted after inactivity
    memory.corrections.clear()
    with session_factory() as db:
        ensure_ready(db, memory)
        assert memory.stats() == before
        assert rebuild_learned(db, memory) == {"knowledge": 1, "corrections": 1}  # idempotent: upserts, no duplicates
    assert memory.stats() == before
    learned = next(k for k in memory.list_knowledge() if k["id"] == b["id"])
    assert learned["source"] == "ticket" and "VAT" in learned["resolution"]
    assert memory.search_corrections(SSO, min_similarity=0.6)[0]["agent"] == {"category": "account", "priority": "P1"}


def test_rate_limits_answer_429_with_cors_and_a_plain_message(make_client, monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(rate_limit_ai_per_10min=2, rate_limit_writes_per_10min=4))
    origin = {"Origin": "http://localhost:3000"}
    with make_client() as c:
        ids = [new_ticket(c, f"The export button does nothing, attempt {i}.")["id"] for i in range(2)]
        r = c.post("/api/tickets", json={"body": "One more ticket please.", "customer": {"name": "x"}}, headers={**AGENT, **origin})
        assert r.status_code == 429 and "public demo" in r.json()["error"] and int(r.headers["Retry-After"]) > 0
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
        # non-AI writes still have budget left; reads are never limited
        assert c.post("/api/tickets?analyze=false", json={"body": "No AI needed here.", "customer": {"name": "x"}}, headers=AGENT).status_code == 201
        assert c.post(f"/api/tickets/{ids[0]}/decision", json={"accept": True}, headers=AGENT).status_code == 200
        assert c.post(f"/api/tickets/{ids[1]}/decision", json={"accept": True}, headers=AGENT).status_code == 429
        assert c.get("/api/tickets").status_code == 200


def test_a_different_client_has_its_own_budget(make_client, monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(rate_limit_ai_per_10min=1))
    with make_client() as c:
        body = {"body": "The export button does nothing.", "customer": {"name": "x"}}
        assert c.post("/api/tickets", json=body, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 201
        assert c.post("/api/tickets", json=body, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 429
        # only the address the proxy appended counts; a forged first entry does not buy a new budget
        assert c.post("/api/tickets", json=body, headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.5"}).status_code == 429
        assert c.post("/api/tickets", json=body, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 201


def test_hosted_postgres_urls_use_psycopg():
    for url in ("postgres://u:p@ep-x.neon.tech/db?sslmode=require", "postgresql://u:p@ep-x.neon.tech/db?sslmode=require"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"
    assert Settings(database_url="sqlite://").database_url == "sqlite://"


class RecordingQdrant:
    """Stands in for QdrantClient to check what is sent when Qdrant Cloud Inference does the embedding."""

    def __init__(self):
        self.created, self.upserts, self.queries = [], [], []

    def collection_exists(self, name):
        return False

    def create_collection(self, name, vectors_config):
        self.created.append((name, vectors_config.size))

    def upsert(self, name, points, wait):
        self.upserts.append(points)

    def query_points(self, name, query, limit, with_payload):
        self.queries.append(query)
        return SimpleNamespace(points=[SimpleNamespace(score=0.91, payload={"key": "KB-101", "document": "Double charge", "subject": "x"})])


def test_cloud_inference_sends_text_not_vectors():
    client = RecordingQdrant()
    idx = QdrantIndex(client, "knowledge_minilm", embedder=None)
    idx.upsert(["KB-101"], ["Double charge on card"], [{"subject": "Double charge on card"}])
    hits = idx.query("charged twice", 3)
    assert client.created == [("knowledge_minilm", 384)]
    point = client.upserts[0][0]
    assert point.vector.text == "Double charge on card" and point.vector.model == CLOUD_MODEL
    assert point.payload["key"] == "KB-101" and point.id != "KB-101"  # ids become UUIDs; ours stays in the payload
    assert client.queries[0].text == "charged twice" and client.queries[0].model == CLOUD_MODEL
    assert hits == [("KB-101", 0.91, {"subject": "x"}, "Double charge")]
