import pytest
from datetime import datetime, timezone

# --- helpers ---

def _kw(db, keyword="prior auth automation", slug="prior-auth-automation"):
    db.select_keyword(keyword, slug, score=500.0, volume=1200, difficulty=34, cpc=8.40, intent="commercial")


# --- keyword lifecycle ---

def test_select_stores_metadata(db):
    _kw(db)
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM keywords WHERE keyword='prior auth automation'").fetchone()
    assert row["state"] == "selected"
    assert row["slug"] == "prior-auth-automation"
    assert row["target_keyword"] == "prior auth automation"
    assert row["volume"] == 1200
    assert row["difficulty"] == 34
    assert float(row["cpc"]) == pytest.approx(8.40)
    assert row["intent"] == "commercial"
    assert row["created_at"] is not None


def test_slug_unique_constraint_raises(db):
    _kw(db)
    with pytest.raises(Exception):
        db.select_keyword("other keyword", "prior-auth-automation", 300.0, 500, 20, 2.0, "informational")


def test_has_slug_collision(db):
    _kw(db)
    assert db.has_slug_collision("prior-auth-automation") is True
    assert db.has_slug_collision("benefits-verification-ai") is False


def test_is_processed(db):
    assert db.is_processed("prior auth automation") is False
    _kw(db)
    assert db.is_processed("prior auth automation") is True


def test_mark_drafted(db):
    _kw(db)
    db.mark_drafted("prior auth automation")
    with db.get_db() as conn:
        row = conn.execute("SELECT state, drafted_at FROM keywords WHERE keyword='prior auth automation'").fetchone()
    assert row["state"] == "drafted"
    assert row["drafted_at"] is not None


def test_publish_requires_approved_not_drafted(db):
    _kw(db)
    db.mark_drafted("prior auth automation")
    db.mark_published("prior auth automation", "webflow-123")
    with db.get_db() as conn:
        row = conn.execute("SELECT state FROM keywords WHERE keyword='prior auth automation'").fetchone()
    assert row["state"] == "drafted"  # unchanged — wrong prior state


def test_full_lifecycle(db):
    _kw(db)
    db.mark_drafted("prior auth automation")
    db.mark_approved("prior auth automation")
    db.mark_published("prior auth automation", "wf-abc")
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM keywords WHERE keyword='prior auth automation'").fetchone()
    assert row["state"] == "published"
    assert row["webflow_item_id"] == "wf-abc"
    assert row["published_at"] is not None


def test_tracking_timestamps(db):
    _kw(db)
    db.mark_drafted("prior auth automation")
    db.mark_approved("prior auth automation")
    db.mark_published("prior auth automation", "wf-abc")
    db.update_tracking_timestamps("prior-auth-automation")
    with db.get_db() as conn:
        row = conn.execute("SELECT tracked_at, last_tracked_at FROM keywords WHERE slug='prior-auth-automation'").fetchone()
    first_tracked = row["tracked_at"]
    assert first_tracked is not None
    assert row["last_tracked_at"] is not None
    # second run: tracked_at unchanged, last_tracked_at updated
    db.update_tracking_timestamps("prior-auth-automation")
    with db.get_db() as conn:
        row2 = conn.execute("SELECT tracked_at, last_tracked_at FROM keywords WHERE slug='prior-auth-automation'").fetchone()
    assert row2["tracked_at"] == first_tracked
    assert row2["last_tracked_at"] >= first_tracked


def test_get_retryable_generate(db):
    _kw(db)
    result = db.get_retryable("generate")
    assert len(result) == 1
    assert result[0]["keyword"] == "prior auth automation"


def test_get_retryable_publish_requires_approved(db):
    _kw(db)
    db.mark_drafted("prior auth automation")
    assert db.get_retryable("publish") == []
    db.mark_approved("prior auth automation")
    assert len(db.get_retryable("publish")) == 1


# --- QA warnings ---

def test_save_and_get_qa_warnings(db):
    _kw(db)
    db.save_qa_warnings("prior-auth-automation", [
        {"category": "roi_claim", "excerpt": "reduces costs by 60%"},
        {"category": "statistic", "excerpt": "98% of claims approved"},
    ])
    warnings = db.get_qa_warnings("prior-auth-automation")
    assert len(warnings) == 2
    assert warnings[0]["category"] == "roi_claim"


def test_get_unresolved_only(db):
    _kw(db)
    db.save_qa_warnings("prior-auth-automation", [
        {"category": "roi_claim", "excerpt": "reduces costs by 60%"},
    ])
    warnings = db.get_qa_warnings("prior-auth-automation")
    db.resolve_qa_warning(warnings[0]["id"], "accepted", "verified with customer data")
    unresolved = db.get_qa_warnings("prior-auth-automation", unresolved_only=True)
    assert unresolved == []


def test_resolve_qa_warning(db):
    _kw(db)
    db.save_qa_warnings("prior-auth-automation", [{"category": "compliance_claim", "excerpt": "HIPAA compliant"}])
    warnings = db.get_qa_warnings("prior-auth-automation")
    db.resolve_qa_warning(warnings[0]["id"], "edited", "added qualification")
    with db.get_db() as conn:
        row = conn.execute("SELECT resolution_status, reviewer_note, reviewed_at FROM qa_warnings WHERE id=?",
                           (warnings[0]["id"],)).fetchone()
    assert row["resolution_status"] == "edited"
    assert row["reviewer_note"] == "added qualification"
    assert row["reviewed_at"] is not None


# --- rank history ---

def test_append_rank_history(db):
    db.append_rank_history([
        {"slug": "prior-auth-automation", "date": "2026-06-24", "position": 14.2,
         "impressions": 43, "clicks": 2, "source": "page", "query": None},
    ])
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM rank_history").fetchall()
    assert len(rows) == 1
    assert rows[0]["position"] == pytest.approx(14.2)


def test_rank_history_appends_not_overwrites(db):
    row = {"slug": "prior-auth-automation", "date": "2026-06-24", "position": 14.2,
            "impressions": 43, "clicks": 2, "source": "page", "query": None}
    db.append_rank_history([row])
    db.append_rank_history([{**row, "date": "2026-07-01", "position": 12.1}])
    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM rank_history").fetchone()[0]
    assert count == 2
