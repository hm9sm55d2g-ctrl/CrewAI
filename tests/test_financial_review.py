import copy
from datetime import date
import hashlib
import json
import unittest
from analisti_2027.financial_review import digest, promotion_plan, review_subject, review_status

class FinancialReviewTests(unittest.TestCase):
    def setUp(self):
        self.day = date.today().isoformat()
        self.text = "TEST FIXTURE ONLY: revenue 10 USD."
        self.record = dict(id="TEST_REVENUE", record_type="document", company="TEST", metric="revenue", period="test period", unit="units", currency="USD", value="10", source_url="https://example.org/test", publication_date=self.day, acquisition_date=self.day, snapshot_path="research/test.txt", sha256=hashlib.sha256(self.text.encode()).hexdigest(), excerpt=self.text, human_verified=False, reviewer=None, reviewed_on=None)
        self.approval = dict(decision="approve", human_reviewed=True, subject_sha256=digest(self.record), reviewer="TEST ATTESTATION ONLY", reviewed_on=self.day)
        self.scenarios = {"data_kind":"synthetic", "scenarios":{"H1":{"assumptions":"test only"}}}

    def plan(self, approval=None):
        return promotion_plan([self.record], {self.record["id"]: approval or self.approval}, {"research/test.txt":self.text}, [], start=self.day, as_of=self.day)

    def reviewed(self):
        return json.loads(self.plan()["knowledge/evidence_registry.json"])

    def test_mirrors_and_content_addressed_snapshot(self):
        files = self.plan()
        self.assertEqual(files["knowledge/evidence_registry.json"], files["src/analisti_2027/knowledge/evidence_registry.json"])
        record = json.loads(files["knowledge/evidence_registry.json"])[0]
        self.assertTrue(record["human_verified"])
        self.assertEqual(files[record["snapshot_path"]], self.text)
        self.assertEqual(files["src/analisti_2027/"+record["snapshot_path"]], self.text)

    def test_missing_review_rejected(self):
        with self.assertRaisesRegex(ValueError,"HUMAN_REVIEW_REQUIRED"):
            promotion_plan([self.record], {}, {"research/test.txt":self.text}, [], start=self.day, as_of=self.day)

    def test_changed_value_invalidates_review(self):
        self.record["value"]="11"
        with self.assertRaisesRegex(ValueError,"STALE_REVIEW"): self.plan()

    def test_tampered_snapshot_rejected(self):
        self.text += " altered"
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_HASH_MISMATCH"): self.plan()

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_INVALID_ID"):
            promotion_plan([self.record,self.record], {self.record["id"]:self.approval}, {"research/test.txt":self.text}, [], start=self.day, as_of=self.day)

    def test_inputs_not_mutated(self):
        before=copy.deepcopy(self.record)
        self.plan()
        self.assertEqual(self.record,before)

    def test_pending_review_never_certifies(self):
        status=review_status("report",self.reviewed(),self.scenarios,None,as_of=self.day)
        self.assertEqual(status["financial_review_status"],"pending")
        self.assertFalse(status["financially_validated"])

    def test_attestation_binds_report_evidence_and_scenarios(self):
        evidence=self.reviewed()
        subject=review_subject("report",evidence,self.scenarios)
        approval=dict(self.approval,subject_sha256=digest(subject))
        status=review_status("report",evidence,self.scenarios,approval,as_of=self.day)
        self.assertEqual(status["financial_review_status"],"attested")
        self.assertFalse(status["financially_validated"])
        for report,records,scenarios in [("changed",evidence,self.scenarios),("report",[dict(evidence[0],value="20")],self.scenarios),("report",evidence,dict(self.scenarios,scenarios={}))]:
            with self.subTest(report=report,records=records,scenarios=scenarios):
                with self.assertRaisesRegex(ValueError,"STALE_REVIEW"):
                    review_status(report,records,scenarios,approval,as_of=self.day)

    def test_synthetic_cannot_be_relabelled_real(self):
        with self.assertRaisesRegex(ValueError,"SCENARIOS_MUST_REMAIN_SYNTHETIC"):
            review_subject("report",self.reviewed(),{"data_kind":"real"})

    def test_unreviewed_evidence_not_admitted_to_review(self):
        with self.assertRaisesRegex(ValueError,"UNREVIEWED_EVIDENCE"):
            review_subject("report",[self.record],self.scenarios)

    def test_outside_window_rejected(self):
        self.record["publication_date"]="2000-01-01"
        with self.assertRaisesRegex(ValueError,"OUTSIDE_WINDOW"):
            self.plan()

    def test_missing_excerpt_rejected(self):
        self.record["excerpt"]="not in the document"
        with self.assertRaisesRegex(ValueError,"EXCERPT_MISMATCH"): self.plan()

if __name__ == "__main__": unittest.main()
