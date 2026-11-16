import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LLM_PROVIDER"] = "mock"  # never call a real API from tests

import server  # noqa: E402


class RateLimitTests(unittest.TestCase):
    def test_per_ip_minute_limit(self):
        lim = server.RateLimiter()
        for _ in range(server.PER_IP_PER_MIN):
            self.assertIsNone(lim.check("1.1.1.1"))
        self.assertIn("wait a minute", lim.check("1.1.1.1"))
        self.assertIsNone(lim.check("2.2.2.2"), "other visitors are unaffected")

    def test_global_daily_cap(self):
        lim = server.RateLimiter()
        lim.global_day = server.GLOBAL_PER_DAY
        self.assertIn("today's free-tier budget", lim.check("3.3.3.3"))


class TriageOneTests(unittest.TestCase):
    def test_single_ticket_round_trip(self):
        out = server.triage_one("Charged twice", "You billed us twice this month, refund it or we file a chargeback.", False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["result"]["manager_review"])
        self.assertIn("tasks", out["timings"])

    def test_vague_ticket_hides_ai(self):
        out = server.triage_one("", "help", False)
        self.assertEqual(out["result"]["queue"], "manual_review")
        self.assertIsNone(out["result"]["ai"])


if __name__ == "__main__":
    unittest.main()
