import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from awa.llm import LLM  # noqa: E402
from awa.orchestrator import RunContext  # noqa: E402
from awa.retrieval import BM25  # noqa: E402
from awa.workflows.ticket_triage import _conf, build_workflow  # noqa: E402

DATA = ROOT / "data" / "tickets"


class RetrievalTests(unittest.TestCase):
    def test_finds_matching_resolution(self):
        docs = [json.loads(x) for x in (DATA / "resolved.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        idx = BM25(docs)
        top = idx.search("I've been charged twice this month", k=3)
        self.assertEqual(top[0][1]["id"], "R-101")
        self.assertEqual(idx.search("android app crashes on launch")[0][1]["id"], "R-306")

    def test_confidence_parsing(self):
        self.assertEqual(_conf("low"), 0.3)
        self.assertEqual(_conf("0.92"), 0.92)
        self.assertEqual(_conf(None), 0.0)
        self.assertEqual(_conf(7), 1.0)


class TeamsDatasetTests(unittest.TestCase):
    def test_labels_are_valid_and_splits_are_disjoint(self):
        cfg = json.loads((ROOT / "config" / "tickets_teams.json").read_text(encoding="utf-8"))
        ids = {}
        for split in ("teams_dev", "teams_test"):
            rows = [json.loads(x) for x in (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
            ids[split] = {r["id"] for r in rows}
            for r in rows:
                self.assertIn(r["label"]["category"], cfg["categories"], r["id"])
                self.assertIn(r["label"]["priority"], ("P1", "P2", "P3"), r["id"])
            self.assertEqual(len({r["label"]["category"] for r in rows}), 5, f"{split} should cover all five teams")
        self.assertFalse(ids["teams_dev"] & ids["teams_test"])
        self.assertIn(cfg["fallback_category"], cfg["categories"])


class TriageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = json.loads((ROOT / "config" / "tickets.json").read_text(encoding="utf-8"))
        cls.ctx = RunContext("t", Path(cls.tmp.name), {"tickets": cfg, "batch_size": 6, "llm_concurrency": 2}, LLM("mock"))
        cls.wf_run = build_workflow(DATA / "incoming.jsonl", DATA / "resolved.jsonl").run(cls.ctx)
        cls.by_id = {d["id"]: d for d in cls.ctx.results["triage"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_run_succeeds(self):
        self.assertEqual(self.wf_run["status"], "success", self.wf_run)

    def test_short_and_non_english_go_to_manual_without_ai(self):
        for tid in ("T-5008", "T-5009", "T-5028"):
            d = self.by_id[tid]
            self.assertEqual(d["queue"], "manual_review", tid)
            self.assertIsNone(d["ai"], tid)
            self.assertNotIn(tid, self.ctx.results["draft_replies"])

    def test_keywords_trigger_manager_review(self):
        self.assertTrue(self.by_id["T-5007"]["manager_review"])   # refund, chargeback, lawyer
        self.assertTrue(self.by_id["T-5022"]["manager_review"])   # refund
        self.assertTrue(self.by_id["T-5030"]["manager_review"])   # legal
        self.assertFalse(self.by_id["T-5003"]["manager_review"])

    def test_angry_p1_goes_to_senior(self):
        self.assertEqual(self.by_id["T-5001"]["queue"], "senior")

    def test_escalations_written_but_not_posted(self):
        msgs = self.ctx.results["escalation_briefs"]
        self.assertEqual(set(msgs), {"T-5002", "T-5020", "T-5023", "T-5026"})
        for m in msgs.values():
            self.assertEqual(m["status"], "awaiting_agent_confirmation")
            self.assertIn("zendesk.com/agent/tickets/", m["text"])
        self.assertTrue((Path(self.tmp.name) / "outbox" / "slack" / "T-5020.json").exists())

    def test_manager_ticket_draft_never_promises_refund(self):
        # the mock drafts copy the nearest resolution ("Refunded the second charge..."), so the guard must fire
        d = self.ctx.results["draft_replies"]["T-5007"]
        self.assertNotRegex(d["draft"].lower(), r"refund|credit|approv")
        self.assertIn("blocked", d)

    def test_evaluation_present(self):
        ev = self.ctx.results["evaluate"]
        self.assertEqual(ev["labelled"], 30)
        self.assertIn("category_accuracy_pct", ev)


if __name__ == "__main__":
    unittest.main()
