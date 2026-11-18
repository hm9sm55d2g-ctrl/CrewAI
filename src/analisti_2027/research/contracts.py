from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResearchResult:
    ticker: str
    analysis_date: str
    rating: str
    market_report: str
    fundamentals_report: str
    news_report: str
    sentiment_report: str
    final_analysis: str
    missing_reports: tuple[str, ...] = ()
    source: str = "tradingagents"
    verification_status: str = "unverified_analysis"
    executable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
