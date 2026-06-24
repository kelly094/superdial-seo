from pathlib import Path
import generate_article

def test_parse_and_save_uses_predetermined_slug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "drafts").mkdir()

    raw = """TITLE: Prior Auth Automation Guide
META: Learn how to automate prior authorization in healthcare RCM workflows.
SLUG: claude-generated-slug
---
# Prior Auth Automation Guide

## What Is Prior Authorization?

Prior authorization is a requirement from payers..."""
    keyword_row = {
        "keyword": "prior authorization automation",
        "volume": 1200,
        "difficulty": 34,
        "cpc": 8.40,
        "intent": "commercial",
    }
    path, title = generate_article.parse_and_save(raw, keyword_row, slug="prior-authorization-automation")
    assert path.name == "prior-authorization-automation.md"
    assert "prior-authorization-automation" in path.read_text()
    assert title == "Prior Auth Automation Guide"


def test_draft_frontmatter_has_intent_and_difficulty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "drafts").mkdir()

    raw = "TITLE: Test\nMETA: desc\nSLUG: test\n---\n# Test\n\nBody."
    keyword_row = {"keyword": "test", "volume": 100, "difficulty": 50, "cpc": 1.0, "intent": "informational"}
    path, _ = generate_article.parse_and_save(raw, keyword_row, slug="test")
    content = path.read_text()
    assert 'intent: "informational"' in content
    assert "difficulty: 50" in content
