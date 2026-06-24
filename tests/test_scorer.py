from utils import slugify

def test_slugify_basic():
    assert slugify("Prior Authorization Automation") == "prior-authorization-automation"

def test_slugify_strips_punctuation():
    assert slugify("What is RCM? A Guide") == "what-is-rcm-a-guide"

def test_slugify_collapses_spaces():
    assert slugify("revenue  cycle   AI") == "revenue-cycle-ai"
