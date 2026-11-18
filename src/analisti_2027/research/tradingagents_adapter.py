"""Offline response validation; does not invoke TradingAgents or any model."""
from .contracts import ResearchResult

VALID_RATINGS = {"Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"}
REQUIRED_REPORTS = (
    "market_report", "fundamentals_report", "news_report", "final_trade_decision",
)


class ResearchResponseError(ValueError):
    """Invalid research response format."""


def normalize_research_response(*, ticker: str, analysis_date: str,
                               state: object, rating: object) -> ResearchResult:
    if not isinstance(state, dict):
        raise ResearchResponseError("INVALID_RESEARCH_STATE")
    reports = {}
    for key in (*REQUIRED_REPORTS, "sentiment_report"):
        value = state.get(key)
        if value is None:
            reports[key] = ""
        elif isinstance(value, str):
            reports[key] = value.strip()
        else:
            raise ResearchResponseError(f"INVALID_RESEARCH_REPORT_TYPE:{key}")
    missing = tuple(key for key in REQUIRED_REPORTS if not reports[key])
    normalized = rating.strip() if isinstance(rating, str) else "REVIEW"
    if normalized not in VALID_RATINGS or missing:
        normalized = "REVIEW"
    return ResearchResult(
        ticker=ticker, analysis_date=analysis_date, rating=normalized,
        market_report=reports["market_report"],
        fundamentals_report=reports["fundamentals_report"],
        news_report=reports["news_report"],
        sentiment_report=reports["sentiment_report"],
        final_analysis=reports["final_trade_decision"], missing_reports=missing,
    )
