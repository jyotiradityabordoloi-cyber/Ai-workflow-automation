import uuid

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.ai.llm import FakeLLM
from app.db import Base, get_session
from app.main import create_app
from app.memory.embeddings import HashEmbedder
from app.memory.semantic import SemanticMemory, seed_knowledge


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def chroma_client():
    return chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))


@pytest.fixture(params=["chroma", "qdrant"])
def memory(request, chroma_client):
    """Semantic memory in RAM with the offline hash embedder, on both vector stores: every memory test runs against
    ChromaDB (local development) and Qdrant (deployment). Fresh collections per test keep tests independent."""
    if request.param == "chroma":
        m = SemanticMemory.chroma(chroma_client, HashEmbedder(), namespace=f"t{uuid.uuid4().hex[:10]}_")
    else:
        from qdrant_client import QdrantClient

        m = SemanticMemory.qdrant(QdrantClient(":memory:"), HashEmbedder())
    seed_knowledge(m)
    return m


@pytest.fixture()
def make_client(session_factory, memory):
    """Build a TestClient around a given fake LLM. No network, no Postgres, no embedding model needed."""

    def _make(llm=None, mem=None):
        app = create_app(llm=llm or FakeLLM(), memory=mem or memory)

        def _session():
            with session_factory() as s:
                yield s

        app.dependency_overrides[get_session] = _session
        return TestClient(app)

    return _make


@pytest.fixture()
def client(make_client):
    with make_client() as c:
        yield c


AGENT = {"X-Agent-Name": "Alex Rivera", "X-Agent-Role": "agent"}
MANAGER = {"X-Agent-Name": "Jordan Lee", "X-Agent-Role": "manager"}


MAYA = {"name": "Maya Chen", "company": "Northwind", "plan": "Pro"}


def new_ticket(client, body: str, subject: str = "Help", analyze: bool = True, headers=AGENT, customer=MAYA):
    r = client.post(f"/api/tickets?analyze={str(analyze).lower()}", headers=headers,
                    json={"subject": subject, "body": body, "customer": customer})
    assert r.status_code == 201, r.text
    return r.json()
