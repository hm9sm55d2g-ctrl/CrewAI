import json
import socket
import pytest
from analisti_2027.research.tradingagents_adapter import (
    REQUIRED_REPORTS, ResearchResponseError, normalize_research_response,
)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def complete_state():
    return {key: "Available report" for key in REQUIRED_REPORTS}


def normalize(state, rating="Buy"):
    return normalize_research_response(
        ticker="TEST", analysis_date="2020-01-02", state=state, rating=rating,
    )


def test_empty_state_requires_review():
    result = normalize({})
    assert result.rating == "REVIEW"
    assert result.missing_reports == REQUIRED_REPORTS
    assert result.executable is False


@pytest.mark.parametrize("state", [None, [], "text", 42])
def test_malformed_state_has_controlled_error(state):
    with pytest.raises(ResearchResponseError, match="^INVALID_RESEARCH_STATE$"):
        normalize(state)


@pytest.mark.parametrize("key", REQUIRED_REPORTS)
def test_missing_required_report_requires_review(key):
    state = complete_state()
    del state[key]
    result = normalize(state)
    assert result.rating == "REVIEW"
    assert result.missing_reports == (key,)


def test_whitespace_report_counts_as_missing():
    state = complete_state()
    state["news_report"] = " \n\t "
    result = normalize(state)
    assert result.rating == "REVIEW"
    assert result.missing_reports == ("news_report",)


def test_invalid_report_type_has_controlled_error():
    state = complete_state()
    state["news_report"] = {"unexpected": "object"}
    with pytest.raises(ResearchResponseError,
                       match="^INVALID_RESEARCH_REPORT_TYPE:news_report$"):
        normalize(state)


def test_complete_state_keeps_valid_rating():
    result = normalize(complete_state())
    assert result.rating == "Buy"
    assert result.missing_reports == ()
    assert result.verification_status == "unverified_analysis"
    assert result.executable is False


def test_disabled_sentiment_is_not_required():
    result = normalize(complete_state())
    assert result.sentiment_report == ""
    assert result.missing_reports == ()
    assert result.rating == "Buy"


@pytest.mark.parametrize("rating", ["invented", "", None, 42])
def test_invalid_rating_requires_review(rating):
    assert normalize(complete_state(), rating).rating == "REVIEW"


def test_input_is_not_mutated():
    state = complete_state()
    before = dict(state)
    normalize(state)
    assert state == before


def test_serializable_missing_reports():
    payload = json.loads(json.dumps(normalize({}).to_dict()))
    assert payload["missing_reports"] == list(REQUIRED_REPORTS)


@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"])
def test_all_valid_ratings(rating):
    assert normalize(complete_state(), rating).rating == rating
