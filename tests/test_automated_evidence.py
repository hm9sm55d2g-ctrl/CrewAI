import copy
from datetime import date
import hashlib
import unittest
from analisti_2027.automated_evidence import SOURCE_URL, verify_candidate, validate_receipt

class AutomatedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.day = date.today().isoformat()
        self.text = "Net sales increased 12% to $201.9 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        self.publisher = "Amazon.com Announces Third Quarter Results\n" + self.text
        self.record = dict(id="TEST_AMZN_SALES", record_type="document", company="AMZN", metric="net_sales", period="Three months ended 2026-09-30", unit="billion", currency="USD", value="201.9", source_url=SOURCE_URL, publication_date="2026-10-29", acquisition_date=self.day, snapshot_path="test.txt", sha256=hashlib.sha256(self.text.encode()).hexdigest(), excerpt=self.text, human_verified=False, reviewer=None, reviewed_on=None)

    def verify(self):
        return verify_candidate(self.record,self.text,self.publisher,publication_date="2026-10-29",reviewed_on=self.day,as_of=self.day)

    def test_valid_automated_receipt_not_human_or_financial_certification(self):
        r=self.verify()
        self.assertEqual(r["review_kind"],"automated")
        self.assertFalse(r["human_verified"])
        self.assertFalse(r["financially_validated"])
        self.assertEqual(validate_receipt(self.record,self.text,self.publisher,r,as_of=self.day),r)

    def test_inputs_unchanged(self):
        before=copy.deepcopy(self.record)
        self.verify()
        self.assertEqual(self.record,before)

    def test_changed_value(self):
        self.record["value"]="202"
        with self.assertRaisesRegex(ValueError,"VALUE_MISMATCH"): self.verify()

    def test_wrong_period_unit_currency(self):
        for key,value in [("period","Trailing twelve months ended 2026-09-30"),("unit","million"),("currency","EUR")]:
            with self.subTest(key=key):
                old=self.record[key]; self.record[key]=value
                with self.assertRaisesRegex(ValueError,"PERIOD_UNIT_CURRENCY_MISMATCH"): self.verify()
                self.record[key]=old

    def test_snapshot_tampering(self):
        self.text += " altered"
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_HASH_MISMATCH"): self.verify()

    def test_excerpt_missing_from_publisher(self):
        self.publisher="Different document"
        with self.assertRaisesRegex(ValueError,"EXCERPT_MISMATCH"): self.verify()

    def test_ambiguous_publisher(self):
        self.publisher += "\n"+self.text
        with self.assertRaisesRegex(ValueError,"AMBIGUOUS_OR_MISSING_VALUE"): self.verify()

    def test_disallowed_source(self):
        self.record["source_url"]="https://example.org/"
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_SOURCE_OR_TYPE"): self.verify()

    def test_no_fabricated_human_review(self):
        self.record["human_verified"]=True
        with self.assertRaisesRegex(ValueError,"CANDIDATE_REVIEW_STATE_REQUIRED"): self.verify()

    def test_changed_candidate_invalidates_receipt(self):
        receipt=self.verify(); self.record["id"]="DIFFERENT_ID"
        with self.assertRaisesRegex(ValueError,"STALE_OR_INVALID_RECEIPT"):
            validate_receipt(self.record,self.text,self.publisher,receipt,as_of=self.day)

    def test_changed_document_invalidates_receipt(self):
        receipt=self.verify(); self.publisher += "\nAdditional text"
        with self.assertRaisesRegex(ValueError,"STALE_OR_INVALID_RECEIPT"):
            validate_receipt(self.record,self.text,self.publisher,receipt,as_of=self.day)

    def test_changed_receipt_rejected(self):
        receipt=self.verify(); receipt["human_verified"]=True
        with self.assertRaisesRegex(ValueError,"STALE_OR_INVALID_RECEIPT"):
            validate_receipt(self.record,self.text,self.publisher,receipt,as_of=self.day)

    def test_publication_mismatch(self):
        self.record["publication_date"]="2026-10-30"
        with self.assertRaisesRegex(ValueError,"PUBLICATION_MISMATCH"): self.verify()

    def test_operating_income_and_ttm_cashflow(self):
        examples=[("operating_income","28.1","Three months ended 2026-09-30","Operating income increased to $28.1 billion in the third quarter, compared with $17.4 billion in third quarter 2025."),("operating_cash_flow","168.3","Trailing twelve months ended 2026-09-30","Operating cash flow increased 29% to $168.3 billion for the trailing twelve months, compared with $130.7 billion for the trailing twelve months ended September 30, 2025.")]
        for metric,value,period,text in examples:
            with self.subTest(metric=metric):
                self.text=text; self.publisher=text
                self.record.update(metric=metric,value=value,period=period,excerpt=text,sha256=hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(self.verify()["status"],"checks_passed")
