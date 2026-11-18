import copy
from datetime import date
import hashlib
import unittest
from analisti_2027.acquisition_adapter import prepare_capture, verify_acquired_candidate
from analisti_2027.evidence_profiles import AMZN_URL, NVDA_URL

class MultiCompanyAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.day = date.today().isoformat()
        self.raw = "TEST FIXTURE ONLY\nNVIDIA Announces Financial Results for Second Quarter Fiscal 2027\nAugust 26, 2026\nsecond quarter ended July 26, 2026\n" + "\n".join([
            "|**GAAP**|**GAAP**|**GAAP**|", "|--|--|--|",
            "|*($ in millions, except earnings per share)*|**Q2 FY27**|**Q1 FY27**|",
            "|Revenue|$100|$90|", "|Operating income|$50|$40|", "|Net income|$30|$20|"])
        self.record = dict(id="TEST_NVDA_CAPTURE",company="NVDA",record_type="document",metric="revenue",period="Three months ended 2026-07-26",unit="million",currency="USD",basis="GAAP",value="100",source_url=NVDA_URL,publication_date="2026-08-26",acquisition_date=self.day,snapshot_path="fixture.txt",sha256=hashlib.sha256(self.raw.encode()).hexdigest(),excerpt="|Revenue|$100|$90|",human_verified=False,reviewer=None,reviewed_on=None)

    def capture(self):
        return prepare_capture(self.raw,source_url=NVDA_URL,publication_date="2026-08-26",acquired_on=self.day)

    def verify(self,capture=None):
        return verify_acquired_candidate(self.record,self.raw,self.capture() if capture is None else capture,reviewed_on=self.day,as_of=self.day)

    def test_nvidia_capture_to_three_metric_receipts(self):
        for metric,value,row in [("revenue","100","|Revenue|$100|$90|"),("operating_income","50","|Operating income|$50|$40|"),("net_income","30","|Net income|$30|$20|")]:
            with self.subTest(metric=metric):
                self.record.update(metric=metric,value=value,excerpt=row)
                r=self.verify();self.assertEqual(r["receipt"]["profile_id"],"nvda-2027q2-gaap-v1")
                self.assertFalse(r["receipt"]["financially_validated"])

    def test_tables_and_original_artifacts_are_preserved(self):
        c=self.capture();before=copy.deepcopy(c);r=self.verify(c)
        self.assertEqual(c,before)
        self.assertEqual(c["raw_text"],c["normalized_text"])
        self.assertEqual(c["normalization_policy"],"preserve-markdown-tables-v1")
        self.assertEqual(c["publication_date"],"2026-08-26")
        for path,text in r["artifacts"].items():
            if path.startswith("knowledge/"):self.assertEqual(text,r["artifacts"]["src/analisti_2027/"+path])

    def test_legacy_amazon_capture_replays(self):
        plain="Net sales increased 12% to $201.9 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        capture=prepare_capture(plain.replace("Net sales","**Net sales**"),source_url=AMZN_URL,publication_date="2026-10-29",acquired_on=self.day)
        capture={k:v for k,v in capture.items() if k not in ("company","profile_id","profile_sha256")};capture["schema_version"]=1
        record=dict(self.record,id="TEST_LEGACY_AMZN",company="AMZN",metric="net_sales",period="Three months ended 2026-09-30",unit="billion",value="201.9",source_url=AMZN_URL,publication_date="2026-10-29",sha256=hashlib.sha256(plain.encode()).hexdigest(),excerpt=plain)
        result=verify_acquired_candidate(record,plain,capture,reviewed_on=self.day,as_of=self.day)
        self.assertEqual(result["receipt"]["verifier"],"amazon_excerpt_verifier")

    def test_company_mismatch_rejected(self):
        self.record["company"]="AMZN"
        with self.assertRaisesRegex(ValueError,"CAPTURE_COMPANY_MISMATCH"):self.verify()

    def test_profile_publication_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,"PUBLICATION_MISMATCH"):
            prepare_capture(self.raw,source_url=NVDA_URL,publication_date="2026-08-27",acquired_on=self.day)

    def test_profile_hash_tampering_rejected(self):
        c=self.capture();c["profile_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"CAPTURE_INTEGRITY_MISMATCH"):self.verify(c)

    def test_non_gaap_candidate_rejected(self):
        self.record["basis"]="non-GAAP"
        with self.assertRaisesRegex(ValueError,"PERIOD_UNIT_CURRENCY_BASIS_MISMATCH"):self.verify()

    def test_boolean_schema_rejected(self):
        c=self.capture();c["schema_version"]=True
        with self.assertRaisesRegex(ValueError,"CAPTURE_INTEGRITY_MISMATCH"):self.verify(c)

    def test_unknown_release_still_rejected(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_CAPTURE_SOURCE"):
            prepare_capture(self.raw,source_url=NVDA_URL.replace("Second-Quarter","Third-Quarter"),publication_date="2026-08-26",acquired_on=self.day)
