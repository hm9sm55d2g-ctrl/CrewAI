import copy
from datetime import date
import hashlib
import json
import unittest
from analisti_2027.automated_evidence import SOURCE_URL, verify_candidate
from analisti_2027.acquisition_adapter import prepare_capture, verify_acquired_candidate

class AcquisitionNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.day = date.today().isoformat()
        self.plain = "Net sales increased 12% to $201.9 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        self.raw = self.plain.replace("Net sales", "**Net sales**")
        self.record = dict(id="TEST_AMZN", company="AMZN", record_type="document", metric="net_sales", period="Three months ended 2026-09-30", unit="billion", currency="USD", value="201.9", source_url=SOURCE_URL, publication_date="2026-10-29", acquisition_date=self.day, snapshot_path="fixture.txt", sha256=hashlib.sha256(self.plain.encode()).hexdigest(), excerpt=self.plain, human_verified=False, reviewer=None, reviewed_on=None)

    def capture(self, text=None):
        return prepare_capture(self.raw if text is None else text,source_url=SOURCE_URL,publication_date="2026-10-29",acquired_on=self.day)

    def verify(self,capture=None):
        return verify_acquired_candidate(self.record,self.plain,self.capture() if capture is None else capture,reviewed_on=self.day,as_of=self.day)

    def test_raw_and_normalized_are_preserved(self):
        c=self.capture();self.assertEqual(c["raw_text"],self.raw);self.assertEqual(c["normalized_text"],self.plain)
        self.assertNotEqual(c["raw_sha256"],c["normalized_sha256"])

    def test_plain_text_is_idempotent(self):
        c=self.capture(self.plain);self.assertEqual(c["raw_sha256"],c["normalized_sha256"])

    def test_direct_verifier_remains_strict(self):
        with self.assertRaisesRegex(ValueError,"EXCERPT_MISMATCH"):
            verify_candidate(self.record,self.plain,self.raw,publication_date="2026-10-29",reviewed_on=self.day,as_of=self.day)

    def test_adapter_verifies_and_receipt_binds_derived_text(self):
        r=self.verify();self.assertEqual(r["receipt"]["publisher_text_sha256"],r["capture"]["normalized_sha256"])
        self.assertFalse(r["receipt"]["human_verified"]);self.assertFalse(r["receipt"]["financially_validated"])

    def test_all_artifacts_mirrored_and_manifest_references_both(self):
        r=self.verify();files=r["artifacts"]
        for path,text in files.items():
            if path.startswith("knowledge/"):self.assertEqual(text,files["src/analisti_2027/"+path])
        manifest=json.loads(next(text for path,text in files.items() if path.startswith("knowledge/acquisitions/")))
        self.assertEqual(files[manifest["raw_snapshot_path"]],self.raw)
        self.assertEqual(files[manifest["normalized_snapshot_path"]],self.plain)

    def test_capture_mutation_rejected(self):
        for key in ("raw_text","normalized_text","raw_sha256","normalized_sha256","normalization_policy"):
            with self.subTest(key=key):
                c=self.capture();c[key]+="altered"
                with self.assertRaisesRegex(ValueError,"CAPTURE_INTEGRITY_MISMATCH"):self.verify(c)

    def test_unrecognized_bold_and_math_are_unchanged(self):
        text="**Other label** 2**3 201.9 USD **201.9**"
        self.assertEqual(self.capture(text)["normalized_text"],text)

    def test_invalid_source_rejected(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_CAPTURE_SOURCE"):
            prepare_capture(self.raw,source_url="https://example.org/",publication_date="2026-10-29",acquired_on=self.day)

    def test_changed_number_does_not_get_repaired(self):
        with self.assertRaisesRegex(ValueError,"EXCERPT_MISMATCH"):
            self.verify(self.capture(self.raw.replace("201.9","202.0")))

    def test_inputs_unchanged(self):
        c=self.capture();before=copy.deepcopy((c,self.record));self.verify(c);self.assertEqual((c,self.record),before)

    def test_three_metric_labels(self):
        raw="**Net sales**\n**Operating income**\n**Operating cash flow**"
        self.assertEqual(self.capture(raw)["normalized_text"],"Net sales\nOperating income\nOperating cash flow")

    def test_nested_markers_not_stripped(self):
        text="***Net sales***"
        self.assertEqual(self.capture(text)["normalized_text"],text)
