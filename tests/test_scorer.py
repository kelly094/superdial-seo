from utils import slugify
from keyword_research import filter_by_relevance

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
