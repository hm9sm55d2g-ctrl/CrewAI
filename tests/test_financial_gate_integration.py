"""Offline promotion-plan integration with the real quality gate and mirrored resource roots."""
import contextlib
import copy
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from analisti_2027 import financial_review as f, quality as q

class FinancialGateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.today=date.today(); self.day=self.today.isoformat()
        self.text="SYNTHETIC TEST ONLY: revenue 10 USD, not real financial evidence."
        self.record=dict(id="TEST_1", record_type="document", company="TEST", metric="revenue", period="test period", unit="units", currency="USD", value="10", source_url="https://example.org/test", publication_date=self.day, acquisition_date=self.day, snapshot_path="research/test.txt", sha256=hashlib.sha256(self.text.encode()).hexdigest(), excerpt=self.text, human_verified=False, reviewer=None, reviewed_on=None)
        self.approval=dict(decision="approve",human_reviewed=True,subject_sha256=f.digest(self.record),reviewer="TEST ONLY, NOT HUMAN APPROVAL",reviewed_on=self.day)
        self.mandate=dict(capital_eur=3000,information_start=self.day,temporal_policy=dict(mode="rolling",start_inclusive=True,end="execution_date",timezone="UTC",documents_date_field="publication_date",market_data_date_field="observation_date"),portfolios={p:dict(cash=3000) for p in "ABC"})
        self.raw="# ANALISI PRELIMINARE NON VALIDATA\n\n"+"\n\n".join("## "+s+"\nND: fixture di integrazione; revisione richiesta." for s in q.SECTIONS)+"\n\n"+q.END

    def materialize(self):
        files=f.promotion_plan([self.record],{"TEST_1":self.approval},{"research/test.txt":self.text},[],start=self.day,as_of=self.day)
        for name,content in files.items():
            target=self.root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content,encoding="utf-8")
        for root in (self.root,self.root/"src/analisti_2027"):
            (root/"knowledge/mandato.json").write_text(json.dumps(self.mandate),encoding="utf-8")
        return files

    def run_gate(self,root):
        output=SimpleNamespace(raw=self.raw)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with self.assertLogs("analisti_2027.audit",level="WARNING") as logs:
                actual=q.check_output(output,root,as_of=self.day)
        self.assertIs(actual,output)
        line=stdout.getvalue().strip()
        self.assertEqual(line,logs.records[0].getMessage())
        return json.loads(line.split(" ",1)[1])

    def test_promoted_fixture_passes_repository_and_package_roots(self):
        self.materialize()
        repo=self.run_gate(self.root)
        packaged=self.run_gate(self.root/"src/analisti_2027")
        self.assertEqual(repo,packaged)
        self.assertEqual(repo["evidence_count"],1)
        self.assertTrue(repo["checks_passed"])
        self.assertFalse(repo["financially_validated"])

    def test_registry_and_snapshot_bytes_are_mirrored(self):
        files=self.materialize()
        for name in files:
            if name.startswith("knowledge/"):
                self.assertEqual((self.root/name).read_bytes(),(self.root/"src/analisti_2027"/name).read_bytes())

    def test_tampered_packaged_snapshot_rejected(self):
        self.materialize()
        packaged=self.root/"src/analisti_2027"
        record=json.loads((packaged/"knowledge/evidence_registry.json").read_text())[0]
        (packaged/record["snapshot_path"]).write_text("TAMPERED")
        with contextlib.redirect_stdout(io.StringIO()),self.assertLogs("analisti_2027.audit",level="WARNING"):
            with self.assertRaisesRegex(ValueError,"INVALID_EVIDENCE_RECORD"):
                q.check_output(SimpleNamespace(raw=self.raw),packaged,as_of=self.day)

    def test_candidate_without_human_review_is_rejected_by_real_gate(self):
        p=self.root/"research/test.txt";p.parent.mkdir();p.write_text(self.text)
        outcome=q.audit(self.raw,self.mandate,[self.record],self.root,as_of=self.day)
        self.assertFalse(outcome["checks_passed"])
        self.assertIn("INVALID_EVIDENCE_RECORD",outcome["errors"])

    def test_missing_packaged_snapshot_rejected(self):
        self.materialize();packaged=self.root/"src/analisti_2027"
        record=json.loads((packaged/"knowledge/evidence_registry.json").read_text())[0]
        (packaged/record["snapshot_path"]).unlink()
        with contextlib.redirect_stdout(io.StringIO()),self.assertLogs("analisti_2027.audit",level="WARNING"):
            with self.assertRaisesRegex(ValueError,"INVALID_EVIDENCE_RECORD"):
                q.check_output(SimpleNamespace(raw=self.raw),packaged,as_of=self.day)

    def test_unknown_citation_rejected_after_promotion(self):
        self.materialize();self.raw=self.raw.replace("ND: fixture", "[E:UNKNOWN] ND: fixture",1)
        with contextlib.redirect_stdout(io.StringIO()),self.assertLogs("analisti_2027.audit",level="WARNING"):
            with self.assertRaisesRegex(ValueError,"UNKNOWN_EVIDENCE_CITATION:UNKNOWN"):
                q.check_output(SimpleNamespace(raw=self.raw),self.root,as_of=self.day)

    def test_review_hash_matches_quality_audit(self):
        self.materialize();outcome=self.run_gate(self.root)
        records=json.loads((self.root/"knowledge/evidence_registry.json").read_text())
        status=f.review_status(self.raw,records,{"data_kind":"synthetic","scenarios":{}},None,as_of=self.day)
        self.assertEqual(status["report_sha256"],outcome["report_sha256"])
        self.assertEqual(status["financial_review_status"],"pending")
        self.assertFalse(status["financially_validated"])

    def test_promotion_retains_existing_records(self):
        self.materialize();existing=json.loads((self.root/"knowledge/evidence_registry.json").read_text())
        snapshots={existing[0]["snapshot_path"]:self.text}
        files=f.promotion_plan([],{},snapshots,existing,start=self.day,as_of=self.day)
        self.assertEqual(json.loads(files["knowledge/evidence_registry.json"]),existing)

    def test_prior_day_review_remains_valid_for_unchanged_subject(self):
        previous=(self.today-timedelta(days=1)).isoformat()
        self.record.update(publication_date=previous,acquisition_date=previous,human_verified=True,reviewer="TEST ONLY",reviewed_on=previous)
        scenarios={"data_kind":"synthetic","scenarios":{}}
        subject=f.review_subject(self.raw,[self.record],scenarios)
        approval=dict(self.approval,subject_sha256=f.digest(subject),reviewed_on=self.record["reviewed_on"])
        status=f.review_status(self.raw,[self.record],scenarios,approval,as_of=self.day)
        self.assertEqual(status["financial_review_status"],"attested")

if __name__=="__main__":unittest.main()
