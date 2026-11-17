import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.ai.llm import FakeLLM
from app.db import Base, get_session
from app.main import create_app


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def make_client(session_factory):
    """Build a TestClient around a given fake LLM. No network, no Postgres needed."""

    def _make(llm=None):
        app = create_app(llm=llm or FakeLLM())

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


def new_ticket(client, body: str, subject: str = "Help", analyze: bool = True, headers=AGENT):
    r = client.post(f"/api/tickets?analyze={str(analyze).lower()}", headers=headers,
                    json={"subject": subject, "body": body, "customer": {"name": "Maya Chen", "company": "Northwind", "plan": "Pro"}})
    assert r.status_code == 201, r.text
    return r.json()
