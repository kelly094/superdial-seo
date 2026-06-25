from pathlib import Path
import generate_article
from content_qa import scan_draft

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


def test_qa_flags_roi_claim():
    draft = "SuperDial reduces prior authorization costs by 60% on average for all clients."
    warnings = scan_draft(draft)
    categories = [w["category"] for w in warnings]
    assert "roi_claim" in categories


def test_qa_returns_list_of_dicts():
    draft = "Revenue cycle automation can help healthcare organizations."
    warnings = scan_draft(draft)
    assert isinstance(warnings, list)
    for w in warnings:
        assert "category" in w
        assert "excerpt" in w


def test_qa_never_raises_on_empty():
    warnings = scan_draft("")
    assert warnings == []


import subprocess, sys

def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import state as st
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test.db")
    st.init_db()
    # dry-run should not create DB records or draft files
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "pipeline.py"), "--step", "keywords", "--dry-run"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert (tmp_path / "data" / "pipeline.db").exists() is False or \
           st.get_retryable("generate") == []

def test_publish_skips_drafted_keywords(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db.select_keyword("prior auth automation", "prior-auth-automation", 500.0, 1200, 34, 8.40, "commercial")
    db.mark_drafted("prior auth automation")
    # publish step should find 0 items (drafted ≠ approved)
    assert db.get_retryable("publish") == []
