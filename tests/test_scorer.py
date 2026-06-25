import math
from unittest.mock import patch
from utils import slugify
from keyword_research import filter_by_relevance, _initial_score, serp_fit_modifier


def _kw(keyword="prior auth software", volume=500, difficulty=30, cpc=10.0, intent="commercial"):
    return {"keyword": keyword, "volume": volume, "difficulty": difficulty, "cpc": cpc, "intent": intent}


def test_navigational_scores_zero():
    assert _initial_score(_kw(intent="navigational")) == 0.0


def test_commercial_beats_informational_same_volume(db):
    commercial = _initial_score(_kw(intent="commercial"))
    informational = _initial_score(_kw(intent="informational"))
    assert commercial > informational


def test_lower_difficulty_scores_higher(db):
    easy = _initial_score(_kw(difficulty=20))
    hard = _initial_score(_kw(difficulty=80))
    assert easy > hard


def test_cpc_zero_still_scores(db):
    score = _initial_score(_kw(cpc=0))
    # (1 + log1p(0)) = 1.0 — zero CPC still contributes a floor multiplier
    assert score > 0.0


def test_cpc_log_scaled(db):
    low_cpc = _initial_score(_kw(cpc=1))
    high_cpc = _initial_score(_kw(cpc=100))
    # log scaling: high_cpc should be higher but not 100x
    assert high_cpc > low_cpc
    assert high_cpc < low_cpc * 10

def test_slugify_basic():
    assert slugify("Prior Authorization Automation") == "prior-authorization-automation"

def test_slugify_strips_punctuation():
    assert slugify("What is RCM? A Guide") == "what-is-rcm-a-guide"

def test_slugify_collapses_spaces():
    assert slugify("revenue  cycle   AI") == "revenue-cycle-ai"

def test_low_relevance_discarded():
    keywords = [
        {"keyword": "prior auth automation", "relevance": "HIGH"},
        {"keyword": "general health tips", "relevance": "LOW"},
        {"keyword": "revenue cycle trends", "relevance": "MEDIUM"},
    ]
    result = filter_by_relevance(keywords)
    assert len(result) == 2
    assert all(k["relevance"] != "LOW" for k in result)

def test_high_and_medium_both_pass():
    keywords = [
        {"keyword": "benefits verification AI", "relevance": "HIGH"},
        {"keyword": "payer relations strategy", "relevance": "MEDIUM"},
    ]
    result = filter_by_relevance(keywords)
    assert len(result) == 2


def test_cannibalization_reduces_score(db):
    # Publish a keyword whose slug overlaps with the candidate's tokens
    db.select_keyword("prior auth automation", "prior-auth-automation", 100.0, 500, 30, 5.0, "commercial")
    db.mark_drafted("prior auth automation")
    db.mark_approved("prior auth automation")
    db.mark_published("prior auth automation", "webflow-id-test")

    # Candidate shares "prior" and "auth" with published slug tokens
    overlapping = _initial_score(_kw(keyword="prior auth software"))
    # Candidate shares no tokens
    non_overlapping = _initial_score(_kw(keyword="denial management workflow"))

    assert overlapping < non_overlapping


def test_serp_fit_directory_heavy_returns_penalty():
    mock_resp = {"tasks": [{"result": [{"items": [
        {"type": "organic", "domain": "g2.com"},
        {"type": "organic", "domain": "g2.com"},
        {"type": "organic", "domain": "g2.com"},
        {"type": "organic", "domain": "g2.com"},
        {"type": "organic", "domain": "superdial.com"},
    ]}]}]}
    with patch("keyword_research.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_resp
        mock_post.return_value.raise_for_status = lambda: None
        result = serp_fit_modifier("prior auth automation")
    assert result == 0.7  # 4/5 = 80% directory domains >= 0.4 threshold


def test_serp_fit_neutral_returns_boost():
    mock_resp = {"tasks": [{"result": [{"items": [
        {"type": "organic", "domain": "superdial.com"},
        {"type": "organic", "domain": "healthcareit.com"},
        {"type": "organic", "domain": "rcmadvisor.com"},
    ]}]}]}
    with patch("keyword_research.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_resp
        mock_post.return_value.raise_for_status = lambda: None
        result = serp_fit_modifier("prior auth automation")
    assert result == 1.2  # No directory/forum domains -> boost
