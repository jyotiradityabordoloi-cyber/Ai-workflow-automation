from app.ai.llm import FakeLLM

from .conftest import AGENT, MANAGER, new_ticket

GOOD = {"language": "en", "category": "billing", "priority": "P2", "sentiment": "neutral", "confidence": 0.9, "summary": "Needs a VAT invoice."}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] is True


def test_create_and_classify_returns_camelcase_contract(make_client):
    with make_client(FakeLLM([GOOD])) as c:
        t = new_ticket(c, "Please resend the October invoice with our VAT number on it.")
    assert t["id"].startswith("SF-") and t["status"] == "needs_review"
    assert t["analysis"]["category"] == "billing" and t["analysis"]["latencyMs"] >= 0
    assert t["decision"] == {"status": "pending", "category": None, "priority": None, "decidedBy": None, "decidedAt": None}
    assert {"createdAt", "managerApproval", "customer"} <= t.keys()


def test_classification_is_never_auto_applied_and_accept_works(make_client):
    with make_client(FakeLLM([GOOD])) as c:
        t = new_ticket(c, "Please resend the October invoice with our VAT number on it.")
        assert t["decision"]["status"] == "pending"
        r = c.post(f"/api/tickets/{t['id']}/decision", json={"accept": True}, headers=AGENT)
        assert r.status_code == 200
        d = r.json()["decision"]
        assert d["status"] == "accepted" and d["category"] == "billing" and d["decidedBy"] == "Alex Rivera"
        assert r.json()["status"] == "in_progress"


def test_manual_review_ticket_cannot_be_accepted(client):
    t = new_ticket(client, "help", subject="")
    assert t["analysis"]["flags"][0]["type"] == "manual_review"
    r = client.post(f"/api/tickets/{t['id']}/decision", json={"accept": True}, headers=AGENT)
    assert r.status_code == 409 and "manually" in r.json()["error"]
    r = client.post(f"/api/tickets/{t['id']}/decision", json={"category": "account", "priority": "P2"}, headers=AGENT)
    assert r.status_code == 200 and r.json()["decision"]["status"] == "overridden"


def test_override_requires_both_fields(make_client):
    with make_client(FakeLLM([GOOD])) as c:
        t = new_ticket(c, "Please resend the October invoice with our VAT number on it.")
        r = c.post(f"/api/tickets/{t['id']}/decision", json={"category": "bug"}, headers=AGENT)
    assert r.status_code == 422


def test_manager_approval_requires_manager_role_and_flag(make_client):
    with make_client(FakeLLM([GOOD, GOOD])) as c:
        t = new_ticket(c, "Refund the duplicate charge or I will file a chargeback.")
        assert any(f["type"] == "manager_review" for f in t["analysis"]["flags"])
        r = c.post(f"/api/tickets/{t['id']}/manager-approval", headers=AGENT)
        assert r.status_code == 403
        r = c.post(f"/api/tickets/{t['id']}/manager-approval", headers=MANAGER)
        assert r.status_code == 200 and r.json()["managerApproval"]["by"] == "Jordan Lee"
        other = new_ticket(c, "Please resend the October invoice with our VAT number on it.")
        r = c.post(f"/api/tickets/{other['id']}/manager-approval", headers=MANAGER)
        assert r.status_code == 409


def test_reanalysis_resets_decision_for_review(make_client):
    with make_client(FakeLLM([GOOD, GOOD])) as c:
        t = new_ticket(c, "Please resend the October invoice with our VAT number on it.")
        c.post(f"/api/tickets/{t['id']}/decision", json={"accept": True}, headers=AGENT)
        r = c.post(f"/api/tickets/{t['id']}/analyze")
        assert r.json()["decision"]["status"] == "pending"
        actions = [e["action"] for e in c.get(f"/api/audit?ticketId={t['id']}").json()]
    assert "Classification reset for agent review" in actions and actions.count("Classified ticket") == 2


def test_llm_outage_still_returns_ticket_for_manual_review(make_client):
    with make_client(FakeLLM(fail=True)) as c:
        t = new_ticket(c, "The export button does nothing when I click it.")
    assert t["analysis"]["error"].startswith("LLM unavailable")
    assert t["analysis"]["flags"][0]["reason"] == "AI classification unavailable"


def test_errors_have_consistent_shape(client):
    r = client.get("/api/tickets/SF-9999")
    assert r.status_code == 404 and r.json() == {"error": "Ticket SF-9999 not found"}
    r = client.post("/api/tickets", json={"body": "", "customer": {"name": "x"}})
    assert r.status_code == 422 and r.json()["error"] == "Invalid request" and r.json()["details"]


def test_assign_senior_and_list(client):
    t = new_ticket(client, "This is UNACCEPTABLE, the dashboard is down NOW for everyone.")
    r = client.post(f"/api/tickets/{t['id']}/assign-senior", headers=AGENT)
    assert r.json()["assignee"] == "Sam Patel (Senior)"
    assert [x["id"] for x in client.get("/api/tickets").json()] == [t["id"]]
