import datetime as dt
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from awa.llm import LLM, extract_json  # noqa: E402
from awa.metrics import compute_impact  # noqa: E402
from awa.orchestrator import CycleError, RunContext, Task, Workflow  # noqa: E402
from awa.workflows.approval_report import build_workflow  # noqa: E402
from generate_sample_data import FIELDS, make_rows  # noqa: E402


def ctx(tmp: str, llm=None, config=None) -> RunContext:
    return RunContext(run_id="t", out_dir=Path(tmp), config=config or {}, llm=llm)


class OrchestratorTests(unittest.TestCase):
    def test_parallel_independent_tasks(self):
        wf = Workflow("p")
        wf.add(Task("a", lambda c: time.sleep(0.3) or 1))
        wf.add(Task("b", lambda c: time.sleep(0.3) or 2))
        wf.add(Task("c", lambda c: c.result("a") + c.result("b"), deps=("a", "b")))
        with tempfile.TemporaryDirectory() as d:
            c = ctx(d)
            run = wf.run(c)
        self.assertEqual(run["status"], "success")
        self.assertEqual(c.results["c"], 3)
        self.assertLess(run["total_seconds"], 0.55, "a and b should overlap")

    def test_retry_then_success(self):
        calls = {"n": 0}

        def flaky(_):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("boom")
            return "ok"

        wf = Workflow("r")
        wf.add(Task("f", flaky, retries=2, retry_delay=0.01))
        with tempfile.TemporaryDirectory() as d:
            run = wf.run(ctx(d))
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["tasks"][0]["attempts"], 3)

    def test_failure_skips_downstream_only(self):
        wf = Workflow("s")
        wf.add(Task("bad", lambda c: 1 / 0))
        wf.add(Task("after_bad", lambda c: 1, deps=("bad",)))
        wf.add(Task("after_after", lambda c: 1, deps=("after_bad",)))
        wf.add(Task("independent", lambda c: 1))
        with tempfile.TemporaryDirectory() as d:
            run = wf.run(ctx(d))
        st = {t["name"]: t["status"] for t in run["tasks"]}
        self.assertEqual(st, {"bad": "failed", "after_bad": "skipped", "after_after": "skipped", "independent": "success"})

    def test_cycle_detected(self):
        wf = Workflow("c")
        wf.add(Task("x", lambda c: 1, deps=("y",)))
        wf.add(Task("y", lambda c: 1, deps=("x",)))
        with self.assertRaises(CycleError):
            wf.topological_order()


class GuardrailTests(unittest.TestCase):
    def test_summary_numbers_must_be_grounded(self):
        from awa.workflows.approval_report import _collect_numbers, is_grounded

        allowed = _collect_numbers({"pending_count": 31, "pending_value": 1671629.0, "pct": 64.6}, set())
        self.assertTrue(is_grounded("31 requests worth INR 1,671,629 are pending (64.6%).", allowed))
        self.assertTrue(is_grounded("Clear the 3 oldest items first.", allowed))
        self.assertFalse(is_grounded("Finance has INR 637,550 pending.", allowed))


class LLMTests(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 2}\n```'), {"a": 2})
        self.assertEqual(extract_json('Sure! Here it is: {"a": 3} hope that helps'), {"a": 3})


class ApprovalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import csv

        cls.tmp = tempfile.TemporaryDirectory()
        as_of = dt.date(2026, 11, 15)
        path = Path(cls.tmp.name) / "req.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(make_rows(as_of))
        policy = json.loads((ROOT / "config" / "policy.json").read_text(encoding="utf-8"))
        cls.ctx = ctx(cls.tmp.name, LLM("mock"), {"policy": policy, "batch_size": 4, "llm_concurrency": 2})
        cls.wf_run = build_workflow(path, dt.datetime.combine(as_of, dt.time(18))).run(cls.ctx)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def flags_for(self, predicate):
        return {f["code"] for d in self.ctx.results["route"] if predicate(d) for f in d["rule_flags"]}

    def test_run_succeeds_and_writes_outputs(self):
        self.assertEqual(self.wf_run["status"], "success", self.wf_run)
        for p in self.ctx.results["render_report"].values():
            self.assertTrue(Path(p).exists())
        self.assertTrue(self.ctx.results["notify"])

    def test_planted_problems_are_caught(self):
        self.assertIn("duplicate", self.flags_for(lambda d: d["vendor"] == "Olive Bistro"))
        self.assertIn("split_purchase", self.flags_for(lambda d: d["vendor"] == "Dell India" and d["amount"] == 24500))
        self.assertIn("missing_receipt", self.flags_for(lambda d: d["requester"] == "Kabir Malhotra" and d["amount"] == 5600))
        self.assertIn("blocked_keyword", self.flags_for(lambda d: d["vendor"] == "Netflix"))
        self.assertIn("blocked_keyword", self.flags_for(lambda d: "Family dinner" in d["description"]))
        self.assertIn("discount_over_limit", self.flags_for(lambda d: d["discount_pct"] == 18))
        self.assertIn("missing_field", self.flags_for(lambda d: d["department"] == "(missing)"))

    def test_split_purchase_routes_to_higher_level(self):
        split = [d for d in self.ctx.results["route"] if d["vendor"] == "Dell India" and d["amount"] == 24500]
        self.assertEqual({d["level"] for d in split}, {"Department Head"})
        self.assertEqual({d["approver"] for d in split}, {"Divya Menon"})

    def test_split_batches_are_not_duplicates(self):
        dell = [d for d in self.ctx.results["route"] if d["vendor"] == "Dell India" and d["amount"] == 24500]
        self.assertEqual(len(dell), 3)
        self.assertNotIn("duplicate", {f["code"] for d in dell for f in d["rule_flags"]})

    def test_large_vague_purchase_never_fast_tracked(self):
        d = next(d for d in self.ctx.results["route"] if d["description"] == "misc tools")
        self.assertEqual({f["code"] for f in d["rule_flags"]}, {"above_fast_track_limit"})
        self.assertEqual(d["ai"]["risk"], "high")
        self.assertEqual(d["suggestion"], "needs_review")
        self.assertEqual(d["approver"], "Anita Rao")

    def test_ai_never_overrides_hard_rule(self):
        for d in self.ctx.results["route"]:
            if {f["code"] for f in d["rule_flags"]} & {"duplicate", "blocked_keyword", "discount_over_limit"}:
                self.assertEqual(d["suggestion"], "return_or_reject")

    def test_impact_math(self):
        baseline = json.loads((ROOT / "config" / "baseline.json").read_text(encoding="utf-8"))
        run = dict(self.wf_run, metrics=self.ctx.metrics)
        imp = compute_impact(run, baseline, {})
        expected_manual = sum(s["minutes"] for s in imp["manual_steps"])
        self.assertAlmostEqual(imp["manual_minutes"], expected_manual, places=1)
        self.assertAlmostEqual(imp["human_minutes_saved"], imp["manual_minutes"] - imp["automated_human_minutes"], places=1)
        measured = compute_impact(run, baseline, {"policy_check": {"minutes_per_unit": 1.0, "samples": 3, "units": 9}})
        step = next(s for s in measured["manual_steps"] if s["id"] == "policy_check")
        self.assertEqual(step["source"], "measured (n=3)")
        self.assertEqual(step["minutes"], round(1.0 * imp["units"]["request"], 1))


if __name__ == "__main__":
    unittest.main()
