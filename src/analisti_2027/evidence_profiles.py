"""Versioned document metadata, not proof of extraction or source authenticity.
Only exact registered documents resolve. Runtime verifier wiring is separate.
"""
from copy import deepcopy
from urllib.parse import urlsplit

COMPANIES = ("AMZN", "NVDA", "AVGO", "ShinEtsu")
AMZN_URL = "https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/default.aspx"
NVDA_URL = "https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx"
_PROFILES = {
    "AMZN": {"profile_id": "amzn-2026q3-text-v1", "source_url": AMZN_URL,
        "publication_date": "2026-10-29", "document_kind": "earnings_release",
        "extraction_kind": "narrative", "metrics": {
            "net_sales": {"unit": "billion", "currency": "USD", "basis": "company_reported", "period": "Three months ended 2026-09-30"},
            "operating_income": {"unit": "billion", "currency": "USD", "basis": "company_reported", "period": "Three months ended 2026-09-30"},
            "operating_cash_flow": {"unit": "billion", "currency": "USD", "basis": "company_reported", "period": "Trailing twelve months ended 2026-09-30"}}},
    "NVDA": {"profile_id": "nvda-2027q2-gaap-v1", "source_url": NVDA_URL,
        "publication_date": "2026-08-26", "document_kind": "earnings_release",
        "extraction_kind": "table", "column_label": "Q2 FY27", "basis": "GAAP", "metrics": {
            "revenue": {"row_label": "Revenue", "unit": "million", "currency": "USD", "basis": "GAAP", "period": "Three months ended 2026-07-26"},
            "operating_income": {"row_label": "Operating income", "unit": "million", "currency": "USD", "basis": "GAAP", "period": "Three months ended 2026-07-26"},
            "net_income": {"row_label": "Net income", "unit": "million", "currency": "USD", "basis": "GAAP", "period": "Three months ended 2026-07-26"}}},
}


def resolve_profile(company, source_url, *, metric=None):
    """Resolve metadata only; do not fetch, parse, approve, or expand date windows."""
    if not isinstance(company, str) or company not in COMPANIES:
        raise ValueError("UNSUPPORTED_COMPANY")
    if not isinstance(source_url, str):
        raise ValueError("INVALID_PROFILE_SOURCE")
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("INVALID_PROFILE_SOURCE")
    if company not in _PROFILES:
        raise ValueError("DOCUMENT_PROFILE_NOT_CONFIGURED")
    profile = _PROFILES[company]
    if source_url != profile["source_url"]:
        raise ValueError("COMPANY_DOCUMENT_MISMATCH")
    if metric is not None and (not isinstance(metric, str) or metric not in profile["metrics"]):
        raise ValueError("UNSUPPORTED_PROFILE_METRIC")
    return dict(deepcopy(profile), company=company, registry_schema_version=1)
