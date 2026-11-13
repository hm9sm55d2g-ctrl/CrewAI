import unittest
from analisti_2027.evidence_profiles import AMZN_URL, NVDA_URL, resolve_profile

class EvidenceProfileTests(unittest.TestCase):
    def test_amazon_profile(self):
        p=resolve_profile("AMZN",AMZN_URL)
        self.assertEqual(p["profile_id"],"amzn-2026q3-text-v1")
        self.assertEqual(p["metrics"]["net_sales"]["unit"],"billion")

    def test_nvidia_gaap_table_profile(self):
        p=resolve_profile("NVDA",NVDA_URL,metric="revenue")
        self.assertEqual(p["basis"],"GAAP")
        self.assertEqual(p["column_label"],"Q2 FY27")
        self.assertEqual(p["metrics"]["revenue"]["unit"],"million")

    def test_periods_are_not_interchangeable(self):
        p=resolve_profile("AMZN",AMZN_URL)
        self.assertNotEqual(p["metrics"]["net_sales"]["period"],p["metrics"]["operating_cash_flow"]["period"])

    def test_same_metric_has_company_specific_metadata(self):
        a=resolve_profile("AMZN",AMZN_URL)["metrics"]["operating_income"]
        n=resolve_profile("NVDA",NVDA_URL)["metrics"]["operating_income"]
        self.assertNotEqual(a["unit"],n["unit"])
        self.assertNotEqual(a["period"],n["period"])

    def test_cross_company_document_rejected(self):
        with self.assertRaisesRegex(ValueError,"COMPANY_DOCUMENT_MISMATCH"):
            resolve_profile("NVDA",AMZN_URL)

    def test_unconfigured_companies_not_claimed_supported(self):
        for company in ("AVGO","ShinEtsu"):
            with self.subTest(company=company):
                with self.assertRaisesRegex(ValueError,"DOCUMENT_PROFILE_NOT_CONFIGURED"):
                    resolve_profile(company,AMZN_URL)

    def test_unknown_company_rejected(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_COMPANY"):
            resolve_profile("UNKNOWN",AMZN_URL)

    def test_unknown_metric_rejected(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_PROFILE_METRIC"):
            resolve_profile("NVDA",NVDA_URL,metric="non_gaap_revenue")

    def test_unregistered_release_rejected(self):
        with self.assertRaisesRegex(ValueError,"COMPANY_DOCUMENT_MISMATCH"):
            resolve_profile("NVDA",NVDA_URL.replace("Second-Quarter","Third-Quarter"))

    def test_deceptive_host_rejected(self):
        with self.assertRaisesRegex(ValueError,"COMPANY_DOCUMENT_MISMATCH"):
            resolve_profile("NVDA",NVDA_URL.replace("investor.nvidia.com","investor.nvidia.com.example.org"))

    def test_unsafe_url_variants_rejected(self):
        for url in (NVDA_URL.replace("https:","http:"),NVDA_URL+"?x=1",NVDA_URL+"#x",NVDA_URL.replace("https://","https://user:pass@")):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError,"INVALID_PROFILE_SOURCE"):
                    resolve_profile("NVDA",url)

    def test_returned_profile_is_independent(self):
        p=resolve_profile("NVDA",NVDA_URL);p["metrics"]["revenue"]["unit"]="billion"
        self.assertEqual(resolve_profile("NVDA",NVDA_URL)["metrics"]["revenue"]["unit"],"million")

    def test_no_values_or_approvals_are_injected(self):
        p=resolve_profile("NVDA",NVDA_URL)
        self.assertNotIn("human_verified",p)
        self.assertNotIn("financially_validated",p)
        self.assertTrue(all("value" not in metric for metric in p["metrics"].values()))
