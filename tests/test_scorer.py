import math
from utils import slugify
from keyword_research import filter_by_relevance, _initial_score


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
    assert score == 0.0  # log(1+0)=0 — zero CPC produces zero score


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
