import unittest
from pathlib import Path

from sifter.grader import RuleGrader
from sifter.gv_ingest import parse_gv_email
from sifter.store import LeadStore
from sifter.__main__ import load_samples, process

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class ParseTest(unittest.TestCase):
    def test_gv_email(self):
        t = parse_gv_email((SAMPLES / "gv_notification.eml").read_bytes())
        self.assertEqual(t.phone, "+15552013344")
        self.assertTrue(t.body.startswith("Yes I'm thinking about selling"))
        self.assertNotIn("To respond", t.body)

    def test_non_gv_email_ignored(self):
        raw = b"From: bob@example.com\nSubject: hi\n\nhello"
        self.assertIsNone(parse_gv_email(raw))


class GradeTest(unittest.TestCase):
    g = RuleGrader()
    cases = {
        "Yes please call me, I want to sell": "HOT",
        "I'd like to learn more": "HOT",
        "Sure, make me an offer": "HOT",
        "How much would you pay?": "HOT",
        "Maybe, depends on the price": "WARM",
        "Not right now but maybe next year": "WARM",
        "Who is this?": "COLD",
        "Not interested": "DEAD",
        "no": "DEAD",
        "STOP": "DNC",
        "wrong number": "DNC",
        "stop texting me": "DNC",
    }

    def test_tiers(self):
        for text, tier in self.cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.g.grade(text).tier, tier)


class RankTest(unittest.TestCase):
    def test_ranking(self):
        store = LeadStore(":memory:")
        process(load_samples(), store)
        leads = store.ranked_leads()
        scores = [l["score"] for l in leads if l["tier"] != "DNC"]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(leads[0]["tier"], "HOT")
        self.assertTrue(all(l["tier"] == "DNC" for l in leads[-3:]))
        # Latest reply wins: "maybe" then "yes, can we talk" should be HOT.
        p3 = next(l for l in leads if l["phone"] == "+15550000003")
        self.assertEqual(p3["tier"], "HOT")


if __name__ == "__main__":
    unittest.main()


class FakeGHL:
    """Stands in for the GoHighLevel API: records calls, returns canned data."""
    def __init__(self, stages=("Hot", "Warm", "Cold", "Dead")):
        self.calls, self.stages, self.opps = [], stages, {}

    def __call__(self, method, path, body=None, query=None):
        self.calls.append((method, path, body, query))
        if path.endswith("/customFields") and method == "GET":
            return {"customFields": [{"id": "f-score", "name": "SMS Lead Score"}]}
        if path.endswith("/customFields") and method == "POST":
            return {"customField": {"id": "f-reply"}}
        if path == "/opportunities/pipelines":
            return {"pipelines": [{"id": "p1", "name": "SMS Leads",
                                   "stages": [{"id": f"s-{n.lower()}", "name": n} for n in self.stages]}]}
        if path == "/contacts/upsert":
            return {"contact": {"id": "c-" + body["phone"][-4:]}}
        if path == "/opportunities/search":
            cid = query["contact_id"]
            return {"opportunities": [{"id": self.opps[cid]}] if cid in self.opps else []}
        if path == "/opportunities/" and method == "POST":
            self.opps[body["contactId"]] = "o-" + body["contactId"]
            return {"opportunity": {"id": self.opps[body["contactId"]]}}
        return {}


class GoHighLevelTest(unittest.TestCase):
    def _sync(self, fake, leads):
        from sifter.crm import GoHighLevelSync
        ghl = GoHighLevelSync("tok", "loc1")
        ghl._call = fake
        return ghl.sync(leads)

    def test_sync(self):
        fake = FakeGHL()
        hot = {"phone": "+15550000005", "tier": "HOT", "score": 100, "last_reply": "call me"}
        dnc = {"phone": "+15550000002", "tier": "DNC", "score": 0, "last_reply": "STOP"}
        count, warnings = self._sync(fake, [hot, dnc])
        self.assertEqual((count, warnings), (2, []))
        upserts = [c[2] for c in fake.calls if c[1] == "/contacts/upsert"]
        self.assertEqual(upserts[0]["customFields"][0], {"id": "f-score", "field_value": 100})
        self.assertNotIn("dnd", upserts[0])
        self.assertTrue(upserts[1]["dnd"])
        opps = [c[2] for c in fake.calls if c[1] == "/opportunities/"]
        self.assertEqual([(o["pipelineStageId"], o["status"]) for o in opps],
                         [("s-hot", "open"), ("s-dead", "lost")])
        tags = [c[2]["tags"] for c in fake.calls if c[0] == "POST" and c[1].endswith("/tags")]
        self.assertEqual(tags, [["sms-hot"], ["sms-dnc"]])

        # Second run: lead cooled off, so the existing opportunity moves stage instead of duplicating.
        cooled = {**hot, "tier": "WARM", "score": 60}
        fake.calls.clear()
        self._sync(fake, [cooled])
        self.assertIn(("PUT", "/opportunities/o-c-0005", {"pipelineStageId": "s-warm", "status": "open"}, None),
                      fake.calls)
        self.assertFalse(any(c[1] == "/opportunities/" for c in fake.calls))

    def test_missing_pipeline_stage_warns(self):
        _, warnings = self._sync(FakeGHL(stages=("Hot", "Warm")),
                                 [{"phone": "+15550000001", "tier": "COLD", "score": 40, "last_reply": "who?"}])
        self.assertEqual(warnings, ["Pipeline is missing stages: Cold, Dead."])
