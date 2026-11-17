"""Agent memory: episodic (per customer, in time order) and semantic (knowledge and agent corrections, by meaning)."""
import json

from app.ai.llm import FakeLLM
from app.memory.embeddings import HashEmbedder
from app.memory.episodic import customer_key

from .conftest import AGENT, MANAGER, new_ticket

OTHER = {"name": "Tom Berg", "company": "Wingtip", "email": "tom@wingtip.example", "plan": "Business"}
BILLING_P1 = {"language": "en", "category": "billing", "priority": "P1", "sentiment": "angry", "confidence": 0.93, "summary": "Double charge."}
BUG_P2 = {"language": "en", "category": "bug", "priority": "P2", "sentiment": "neutral", "confidence": 0.81, "summary": "Export is broken."}
DOUBLE = "We were charged twice for the monthly subscription and need one charge reversed."


def last_payload(llm: FakeLLM) -> dict:
    return json.loads(llm.prompts[-1])


# ---------------------------------------------------------------- episodic
def test_earlier_tickets_of_the_same_customer_reach_the_classifier(make_client):
    llm = FakeLLM([BILLING_P1, BILLING_P1])
    with make_client(llm) as c:
        first = new_ticket(c, DOUBLE, subject="Charged twice")
        c.post(f"/api/tickets/{first['id']}/decision", json={"accept": True}, headers=AGENT)
        second = new_ticket(c, "Still waiting on the refund for the double charge, third email now.", subject="Refund?")
        mem = c.get(f"/api/tickets/{second['id']}/memory").json()

    history = last_payload(llm)["customer_history"]
    assert len(history) == 1 and history[0].startswith(f"{first['id']}, ") and "agent confirmed billing P1" in history[0]
    assert second["analysis"]["memory"]["history"] == [first["id"]]
    past = mem["earlierTickets"]
    assert [p["id"] for p in past] == [first["id"]]
    assert [e["kind"] for e in past[0]["episodes"]] == ["opened", "classified", "decision"]
    assert mem["usedByAi"]["history"] == [first["id"]]


def test_history_never_crosses_customers_or_looks_into_the_future(make_client):
    llm = FakeLLM()
    with make_client(llm) as c:
        a = new_ticket(c, DOUBLE)
        new_ticket(c, DOUBLE, customer=OTHER)
        assert "customer_history" not in last_payload(llm)        # different customer: nothing recalled
        new_ticket(c, "The export button does nothing when I click it.")
        assert len(last_payload(llm)["customer_history"]) == 1     # Maya's earlier ticket only
        c.post(f"/api/tickets/{a['id']}/analyze")
        assert "customer_history" not in last_payload(llm)        # re-classifying the oldest ticket sees no later ones


def test_no_memory_means_the_prompt_is_unchanged(make_client):
    llm = FakeLLM()
    with make_client(llm) as c:
        new_ticket(c, "The export button does nothing when I click it.", subject="Export")
    assert last_payload(llm) == {"subject": "Export", "message": "The export button does nothing when I click it."}


# ---------------------------------------------------------------- semantic: corrections
def test_agent_override_is_remembered_and_shown_on_a_near_identical_ticket(make_client, memory):
    llm = FakeLLM([BUG_P2, BUG_P2])
    with make_client(llm) as c:
        t = new_ticket(c, DOUBLE, subject="Charged twice")
        r = c.post(f"/api/tickets/{t['id']}/decision", json={"category": "billing", "priority": "P1"}, headers=AGENT)
        assert r.status_code == 200
        assert memory.stats()["corrections"] == 1
        nxt = new_ticket(c, DOUBLE, subject="Charged twice", customer=OTHER)

    corrections = last_payload(llm)["agent_corrections"]
    assert corrections == [{"message": f"Charged twice. {DOUBLE}", "ai_said": "bug P2", "agent_set": "billing P1"}]
    assert nxt["analysis"]["memory"]["corrections"] == [{"id": t["id"], "similarity": 1.0}]


def test_accepting_or_filling_in_a_fallback_teaches_nothing(make_client, memory):
    with make_client() as c:
        fallback = new_ticket(c, "help", subject="")           # precheck fallback, agent must classify by hand
        c.post(f"/api/tickets/{fallback['id']}/decision", json={"category": "account", "priority": "P2"}, headers=AGENT)
        ok = new_ticket(c, DOUBLE)
        c.post(f"/api/tickets/{ok['id']}/decision", json={"accept": True}, headers=AGENT)
    assert memory.stats()["corrections"] == 0


def test_a_ticket_is_not_shown_its_own_correction(make_client):
    llm = FakeLLM([BUG_P2, BUG_P2])
    with make_client(llm) as c:
        t = new_ticket(c, DOUBLE)
        c.post(f"/api/tickets/{t['id']}/decision", json={"category": "billing", "priority": "P1"}, headers=AGENT)
        c.post(f"/api/tickets/{t['id']}/analyze")
    assert "agent_corrections" not in last_payload(llm)


# ---------------------------------------------------------------- semantic: knowledge and consolidation
def test_curated_knowledge_is_seeded_and_retrieved_with_ids_and_similarity(client):
    kb = client.get("/api/knowledge").json()
    assert len(kb) == 21 and all(k["source"] == "kb" for k in kb)
    t = new_ticket(client, "We were charged twice for the monthly subscription.", subject="Double charge on card")
    hits = client.get(f"/api/tickets/{t['id']}/memory").json()["knowledge"]
    assert hits[0]["id"] == "KB-101" and hits[0]["similarity"] > 0.9 and len(hits) <= 3
    assert t["analysis"]["memory"]["knowledge"][0]["id"] == "KB-101"


def test_knowledge_search_returns_scored_hits(client):
    hits = client.get("/api/knowledge/search", params={"q": "Password reset emails never arrive", "k": 2}).json()
    assert len(hits) == 2 and hits[0]["id"] == "KB-201" and hits[0]["similarity"] >= hits[1]["similarity"]
    assert client.get("/api/knowledge/search", params={"q": ""}).status_code == 422


def test_resolving_consolidates_the_fix_into_knowledge(make_client):
    with make_client(FakeLLM([BILLING_P1, BILLING_P1])) as c:
        t = new_ticket(c, "Our seats invoice shows 40 seats but we only have 25 users.", subject="Seat invoice wrong")
        r = c.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "Removed 15 unused seats and credited the difference."}, headers=AGENT)
        assert r.status_code == 409 and "classification" in r.json()["error"]
        c.post(f"/api/tickets/{t['id']}/decision", json={"accept": True}, headers=AGENT)
        r = c.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "Removed 15 unused seats and credited the difference."}, headers=AGENT)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "resolved" and body["resolution"]["by"] == "Alex Rivera"
        assert c.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "Removed 15 unused seats again."}, headers=AGENT).status_code == 409

        learned = next(k for k in c.get("/api/knowledge").json() if k["id"] == t["id"])
        assert learned["source"] == "ticket" and learned["category"] == "billing" and "credited" in learned["resolution"]
        similar = new_ticket(c, "Our seats invoice shows 40 seats but we only have 25 users.", subject="Seat invoice wrong", customer=OTHER)
        hits = c.get(f"/api/tickets/{similar['id']}/memory").json()["knowledge"]
        assert hits[0]["id"] == t["id"]
        resolved_episode = c.get(f"/api/tickets/{similar['id']}/memory").json()
        assert resolved_episode["earlierTickets"] == []  # another customer: semantic memory yes, episodic memory no


def test_manager_review_tickets_need_approval_before_resolving(make_client):
    with make_client(FakeLLM([BILLING_P1])) as c:
        t = new_ticket(c, "Refund the duplicate charge or my lawyer gets involved.")
        c.post(f"/api/tickets/{t['id']}/decision", json={"accept": True}, headers=AGENT)
        r = c.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "Refunded the duplicate charge."}, headers=AGENT)
        assert r.status_code == 409 and "manager" in r.json()["error"]
        c.post(f"/api/tickets/{t['id']}/manager-approval", headers=MANAGER)
        r = c.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "Refunded the duplicate charge."}, headers=AGENT)
        assert r.status_code == 200


def test_resolution_must_say_something(client):
    t = new_ticket(client, DOUBLE)
    r = client.post(f"/api/tickets/{t['id']}/resolve", json={"resolution": "done"}, headers=AGENT)
    assert r.status_code == 422


# ---------------------------------------------------------------- robustness
class BrokenMemory:
    def search_corrections(self, *a, **k):
        raise RuntimeError("vector store down")

    search_knowledge = search_corrections

    def add_correction(self, *a, **k):
        raise RuntimeError("vector store down")

    def stats(self):
        return {"embedder": "broken", "knowledge": 0, "corrections": 0}


def test_a_broken_vector_store_never_blocks_the_workflow(make_client):
    with make_client(FakeLLM([BUG_P2]), mem=BrokenMemory()) as c:
        t = new_ticket(c, DOUBLE)
        assert t["analysis"]["category"] == "bug" and t["analysis"]["error"] is None
        r = c.post(f"/api/tickets/{t['id']}/decision", json={"category": "billing", "priority": "P1"}, headers=AGENT)
        assert r.status_code == 200
        assert c.get(f"/api/tickets/{t['id']}/memory").status_code == 200


def test_memory_stats(client):
    new_ticket(client, DOUBLE)
    s = client.get("/api/memory/stats").json()
    assert s == {"embedder": "hash384", "knowledge": 21, "corrections": 0, "episodes": 2}


# ---------------------------------------------------------------- units
def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder()
    a, b = e.embed(["Charged twice this month"]), e.embed(["Charged twice this month"])
    assert a == b and abs(sum(x * x for x in a[0]) - 1) < 1e-9


def test_customer_key_prefers_email_then_company_and_name():
    assert customer_key(" Maya@Northwind.example ", "Northwind", "Maya") == "maya@northwind.example"
    assert customer_key("", "Northwind ", "Maya Chen") == "northwind|maya chen"
