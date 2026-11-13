import copy
from datetime import date
import hashlib
import unittest
from analisti_2027.automated_evidence import verify_candidate, validate_receipt
from analisti_2027.evidence_profiles import NVDA_URL

class ProfileVerifierTests(unittest.TestCase):
    def setUp(self):
        self.day = date.today().isoformat()
        self.table = "\n".join(["|**GAAP**|**GAAP**|**GAAP**|", "|--|--|--|",
            "|*($ in millions, except earnings per share)*|**Q2 FY27**|**Q1 FY27**|",
            "|Revenue|$100|$90|", "|Operating income|$50|$40|", "|Net income|$30|$20|"])
        self.text = "TEST FIXTURE ONLY\nNVIDIA Announces Financial Results for Second Quarter Fiscal 2027\nAugust 26, 2026\nsecond quarter ended July 26, 2026\n" + self.table
        self.snapshot = self.text
        self.record = dict(id="TEST_NVDA", record_type="document", company="NVDA", metric="revenue", period="Three months ended 2026-07-26", unit="million", currency="USD", basis="GAAP", value="100", source_url=NVDA_URL, publication_date="2026-08-26", acquisition_date=self.day, snapshot_path="fixture.txt", sha256=hashlib.sha256(self.snapshot.encode()).hexdigest(), excerpt="|Revenue|$100|$90|", human_verified=False, reviewer=None, reviewed_on=None)

    def verify(self):
        return verify_candidate(self.record,self.snapshot,self.text,publication_date="2026-08-26",reviewed_on=self.day,as_of=self.day)

    def test_dispatch_and_receipt_revalidation(self):
        r=self.verify()
        self.assertEqual(r["profile_id"],"nvda-2027q2-gaap-v1")
        self.assertEqual(r["selector"]["column_label"],"Q2 FY27")
        self.assertFalse(r["human_verified"]);self.assertFalse(r["financially_validated"])
        self.assertEqual(validate_receipt(self.record,self.snapshot,self.text,r,as_of=self.day),r)

    def test_three_metrics(self):
        for metric,value,row in [("revenue","100","|Revenue|$100|$90|"),("operating_income","50","|Operating income|$50|$40|"),("net_income","30","|Net income|$30|$20|")]:
            with self.subTest(metric=metric):
                self.record.update(metric=metric,value=value,excerpt=row)
                self.assertEqual(self.verify()["status"],"checks_passed")

    def test_previous_column_not_current(self):
        self.record["value"]="90"
        with self.assertRaisesRegex(ValueError,"VALUE_MISMATCH"):self.verify()

    def test_gaap_and_non_gaap_not_interchangeable(self):
        self.record["basis"]="non-GAAP"
        with self.assertRaisesRegex(ValueError,"PERIOD_UNIT_CURRENCY_BASIS_MISMATCH"):self.verify()

    def test_non_gaap_table_not_accepted(self):
        self.text=self.text.replace("**GAAP**","**Non-GAAP**")
        with self.assertRaisesRegex(ValueError,"GAAP_TABLE_MISSING_OR_AMBIGUOUS"):self.verify()

    def test_duplicate_gaap_tables_rejected(self):
        self.text+="\n\n"+self.table
        with self.assertRaisesRegex(ValueError,"GAAP_TABLE_MISSING_OR_AMBIGUOUS"):self.verify()

    def test_duplicate_metric_rows_rejected(self):
        self.text+="\n|Revenue|$100|$90|"
        with self.assertRaisesRegex(ValueError,"METRIC_ROW_MISSING_OR_AMBIGUOUS"):self.verify()

    def test_ambiguous_current_column_rejected(self):
        self.text=self.text.replace("Q1 FY27","Q2 FY27")
        with self.assertRaisesRegex(ValueError,"CURRENT_COLUMN_MISSING_OR_AMBIGUOUS"):self.verify()

    def test_wrong_table_unit_rejected(self):
        self.text=self.text.replace("in millions","in billions")
        with self.assertRaisesRegex(ValueError,"GAAP_TABLE_UNITS_MISMATCH"):self.verify()

    def test_metadata_mismatches_rejected(self):
        for key,value in [("period","Trailing twelve months ended 2026-07-26"),("currency","EUR"),("unit","billion")]:
            with self.subTest(key=key):
                before=self.record[key];self.record[key]=value
                with self.assertRaisesRegex(ValueError,"PERIOD_UNIT_CURRENCY_BASIS_MISMATCH"):self.verify()
                self.record[key]=before

    def test_missing_document_period_rejected(self):
        self.text=self.text.replace("second quarter ended July 26, 2026","different period")
        with self.assertRaisesRegex(ValueError,"DOCUMENT_PERIOD_OR_IDENTITY_MISMATCH"):self.verify()

    def test_bad_snapshot_rejected(self):
        self.snapshot+=" altered"
        with self.assertRaisesRegex(ValueError,"SNAPSHOT_HASH_MISMATCH"):self.verify()

    def test_unknown_metric_rejected(self):
        self.record["metric"]="non_gaap_net_income"
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_PROFILE_METRIC"):self.verify()

    def test_company_source_mismatch_rejected(self):
        self.record["source_url"]="https://example.org/"
        with self.assertRaisesRegex(ValueError,"COMPANY_DOCUMENT_MISMATCH"):self.verify()

    def test_human_flag_cannot_be_fabricated(self):
        self.record["human_verified"]=True
        with self.assertRaisesRegex(ValueError,"CANDIDATE_REVIEW_STATE_REQUIRED"):self.verify()

    def test_changed_document_invalidates_receipt(self):
        r=self.verify();self.text+="\nMore text"
        with self.assertRaisesRegex(ValueError,"STALE_OR_INVALID_RECEIPT"):
            validate_receipt(self.record,self.snapshot,self.text,r,as_of=self.day)

    def test_selector_mutation_invalidates_receipt(self):
        r=self.verify();r["selector"]["column_index"]=2
        with self.assertRaisesRegex(ValueError,"STALE_OR_INVALID_RECEIPT"):
            validate_receipt(self.record,self.snapshot,self.text,r,as_of=self.day)

    def test_inputs_not_mutated(self):
        before=copy.deepcopy(self.record);self.verify();self.assertEqual(self.record,before)
