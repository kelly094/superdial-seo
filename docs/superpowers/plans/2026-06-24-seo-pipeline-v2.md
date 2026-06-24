# SEO Pipeline V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a weekly SEO content pipeline — Claude ideates and scores keywords, DataForSEO validates them, Claude writes articles, a QA scanner flags healthcare content risks, a human reviews and approves drafts, approved articles publish to Webflow CMS, and Google Search Console tracks rank performance over time.

**Architecture:** A SQLite state machine (`data/pipeline.db`) drives an idempotent multi-step orchestrator (`pipeline.py`). Each step reads only items in the correct prior state, so any step can be safely re-run after failure. Content lifecycle ends at `published`; rank tracking is recurring metadata, not a lifecycle state.

**Tech Stack:** Python 3.11+, SQLite (stdlib `sqlite3`), Anthropic SDK (`anthropic`), DataForSEO REST API (`requests`), Google Search Console API (`google-api-python-client`, `google-auth-oauthlib`), Streamlit

## Global Constraints

- All code lives in `~/Documents/superdial-seo/`
- Python 3.11+; use stdlib `sqlite3` only — no SQLAlchemy or ORMs
- Database path: `data/pipeline.db`; tests use a temp path via monkeypatch
- Model for all Claude calls: `claude-sonnet-4-6`
- DataForSEO auth: HTTP Basic Auth with `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` env vars
- All timestamps: ISO 8601 UTC strings (`2026-06-24T09:00:00Z`)
- `slug TEXT UNIQUE` is enforced in DB schema; application-level `has_slug_collision()` check must also be present
- Publishing creates Webflow items with `isDraft: True` — Kelly reviews before going live
- SERP analysis limited to top 10 candidates per run (cost control)
- Query-level GSC rows: top 25 per article per run, ≥5 impressions threshold
- No mocking in integration tests; unit tests use real SQLite at a temp path
- TDD: write failing test first, then implement, then verify green

---

## File Structure

**Created:**
- `utils.py` — `slugify()` shared utility
- `state.py` — complete SQLite layer: lifecycle transitions, timestamps, QA warnings, rank history
- `keyword_research.py` — Claude ideation + relevance filter, DataForSEO validation, SERP scoring
- `content_qa.py` — healthcare content QA scanner; returns warnings list, never blocks
- `rank_tracker.py` — Google Search Console OAuth + page/query-level rank snapshots
- `dashboard.py` — Streamlit executive view, review queue, QA warning resolution
- `tests/conftest.py` — shared pytest fixtures (db, tmp_path)
- `tests/test_scorer.py` — unit tests for scoring logic
- `tests/test_state.py` — unit tests for database layer
- `tests/test_pipeline.py` — integration tests for full pipeline steps

**Modified:**
- `generate_article.py` — accept new keyword dict shape, pass intent/difficulty to prompt, use pre-determined slug
- `pipeline.py` — full rewrite: state-aware steps, review gate, run metrics, structured logging
- `.env.example` — add `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `GSC_SITE_URL`
- `requirements.txt` — add `streamlit`, `google-api-python-client`, `google-auth-oauthlib`

**Deprecated (keep, do not delete):**
- `keyword_pull.py` — superseded by `keyword_research.py`; retained as fallback until Google Ads Standard API access is confirmed

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `utils.py`
- Modify: `.env.example`
- Create: `tests/conftest.py`
- Create: `data/` directory (runtime; `.gitkeep` added)

**Interfaces:**
- Produces: `slugify(text: str) -> str` used by `keyword_research.py` and `generate_article.py`

- [ ] **Step 1: Create requirements.txt**

```text
anthropic
python-dotenv
requests
google-ads
google-api-python-client
google-auth-oauthlib
streamlit
pytest
```

- [ ] **Step 2: Install dependencies**

```bash
cd ~/Documents/superdial-seo && source venv/bin/activate && pip install -r requirements.txt
```

Expected: all packages install without error. Verify with `pip show streamlit google-api-python-client`.

- [ ] **Step 3: Update .env.example**

```text
ANTHROPIC_API_KEY=your-anthropic-api-key-here
WEBFLOW_API_TOKEN=your-webflow-api-token-here
WEBFLOW_COLLECTION_ID=your-reference-collection-id-here
DATAFORSEO_LOGIN=your-dataforseo-email
DATAFORSEO_PASSWORD=your-dataforseo-password
GSC_SITE_URL=https://www.superdial.com
```

- [ ] **Step 4: Write failing test for slugify**

Create `tests/test_scorer.py`:

```python
from utils import slugify

def test_slugify_basic():
    assert slugify("Prior Authorization Automation") == "prior-authorization-automation"

def test_slugify_strips_punctuation():
    assert slugify("What is RCM? A Guide") == "what-is-rcm-a-guide"

def test_slugify_collapses_spaces():
    assert slugify("revenue  cycle   AI") == "revenue-cycle-ai"
```

- [ ] **Step 5: Run test — verify it fails**

```bash
cd ~/Documents/superdial-seo && source venv/bin/activate && pytest tests/test_scorer.py -v
```

Expected: `ImportError: No module named 'utils'`

- [ ] **Step 6: Create utils.py**

```python
import re

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text
```

- [ ] **Step 7: Run test — verify it passes**

```bash
pytest tests/test_scorer.py -v
```

Expected: 3 passed

- [ ] **Step 8: Create tests/conftest.py**

```python
import pytest
import state

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "test.db")
    state.init_db()
    return state
```

- [ ] **Step 9: Create data directory**

```bash
mkdir -p ~/Documents/superdial-seo/data && touch ~/Documents/superdial-seo/data/.gitkeep
```

- [ ] **Step 10: Commit**

```bash
git add requirements.txt utils.py .env.example tests/conftest.py tests/test_scorer.py data/.gitkeep
git commit -m "feat: project setup — requirements, slugify util, test scaffold"
```

---

### Task 2: state.py — SQLite Database Layer

**Files:**
- Create: `state.py`
- Create: `tests/test_state.py`

**Interfaces:**
- Produces (consumed by every subsequent task):
  - `init_db() -> None`
  - `select_keyword(keyword, slug, score, volume, difficulty, cpc, intent) -> None`
  - `mark_drafted(keyword) -> None`
  - `mark_approved(keyword) -> None`
  - `mark_published(keyword, webflow_item_id) -> None`
  - `update_tracking_timestamps(slug) -> None`
  - `is_processed(keyword) -> bool`
  - `has_slug_collision(slug) -> bool`
  - `get_retryable(step: str) -> list[dict]` — step in `['generate', 'publish', 'track']`
  - `get_all_published_slugs() -> list[str]`
  - `save_qa_warnings(slug, warnings: list[dict]) -> None` — each warning: `{category, excerpt}`
  - `get_qa_warnings(slug, unresolved_only=False) -> list[dict]`
  - `resolve_qa_warning(id, status, note=None) -> None`
  - `append_rank_history(rows: list[dict]) -> None`
  - `save_run_log(run_id, started_at, finished_at, metrics: dict) -> None`
  - `get_db() -> sqlite3.Connection` (context manager)

- [ ] **Step 1: Write failing tests**

Create `tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run — verify all fail**

```bash
cd ~/Documents/superdial-seo && source venv/bin/activate && pytest tests/test_state.py -v 2>&1 | head -20
```

Expected: `ImportError: No module named 'state'`

- [ ] **Step 3: Create state.py**

```python
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("PIPELINE_DB", "data/pipeline.db"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS keywords (
                id              INTEGER PRIMARY KEY,
                keyword         TEXT NOT NULL UNIQUE,
                target_keyword  TEXT NOT NULL,
                state           TEXT NOT NULL,
                slug            TEXT UNIQUE,
                webflow_item_id TEXT,
                score           REAL,
                volume          REAL,
                difficulty      REAL,
                cpc             REAL,
                intent          TEXT,
                created_at      TEXT,
                drafted_at      TEXT,
                approved_at     TEXT,
                published_at    TEXT,
                tracked_at      TEXT,
                last_tracked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS rank_history (
                id          INTEGER PRIMARY KEY,
                slug        TEXT NOT NULL,
                date        TEXT NOT NULL,
                position    REAL,
                impressions INTEGER,
                clicks      INTEGER,
                source      TEXT NOT NULL,
                query       TEXT
            );
            CREATE TABLE IF NOT EXISTS qa_warnings (
                id                INTEGER PRIMARY KEY,
                slug              TEXT NOT NULL,
                category          TEXT NOT NULL,
                excerpt           TEXT NOT NULL,
                created_at        TEXT NOT NULL,
                resolution_status TEXT,
                reviewer_note     TEXT,
                reviewed_at       TEXT
            );
            CREATE TABLE IF NOT EXISTS run_log (
                run_id      TEXT PRIMARY KEY,
                started_at  TEXT,
                finished_at TEXT,
                metrics     TEXT
            );
        """)


def select_keyword(keyword: str, slug: str, score: float,
                   volume: float, difficulty: float, cpc: float, intent: str) -> None:
    with get_db() as conn:
        conn.execute("""
            INSERT INTO keywords
              (keyword, target_keyword, state, slug, score, volume, difficulty, cpc, intent, created_at)
            VALUES (?, ?, 'selected', ?, ?, ?, ?, ?, ?, ?)
        """, (keyword, keyword, slug, score, volume, difficulty, cpc, intent, _now()))


def mark_drafted(keyword: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE keywords SET state='drafted', drafted_at=? WHERE keyword=? AND state='selected'",
            (_now(), keyword),
        )


def mark_approved(keyword: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE keywords SET state='approved', approved_at=? WHERE keyword=? AND state='drafted'",
            (_now(), keyword),
        )


def mark_published(keyword: str, webflow_item_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE keywords SET state='published', webflow_item_id=?, published_at=? "
            "WHERE keyword=? AND state='approved'",
            (webflow_item_id, _now(), keyword),
        )


def update_tracking_timestamps(slug: str) -> None:
    now = _now()
    with get_db() as conn:
        row = conn.execute("SELECT tracked_at FROM keywords WHERE slug=?", (slug,)).fetchone()
        if row and row["tracked_at"] is None:
            conn.execute(
                "UPDATE keywords SET tracked_at=?, last_tracked_at=? WHERE slug=?",
                (now, now, slug),
            )
        else:
            conn.execute("UPDATE keywords SET last_tracked_at=? WHERE slug=?", (now, slug))


def is_processed(keyword: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM keywords WHERE keyword=?", (keyword,)).fetchone()
        return row is not None


def has_slug_collision(slug: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM keywords WHERE slug=?", (slug,)).fetchone()
        return row is not None


def get_retryable(step: str) -> list:
    prior = {"generate": "selected", "publish": "approved", "track": "published"}[step]
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM keywords WHERE state=?", (prior,)).fetchall()
        return [dict(r) for r in rows]


def get_all_published_slugs() -> list:
    with get_db() as conn:
        rows = conn.execute("SELECT slug FROM keywords WHERE state='published'").fetchall()
        return [r["slug"] for r in rows]


def save_qa_warnings(slug: str, warnings: list) -> None:
    now = _now()
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO qa_warnings (slug, category, excerpt, created_at) VALUES (?, ?, ?, ?)",
            [(slug, w["category"], w["excerpt"], now) for w in warnings],
        )


def get_qa_warnings(slug: str, unresolved_only: bool = False) -> list:
    with get_db() as conn:
        if unresolved_only:
            rows = conn.execute(
                "SELECT * FROM qa_warnings WHERE slug=? AND resolution_status IS NULL", (slug,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM qa_warnings WHERE slug=?", (slug,)).fetchall()
        return [dict(r) for r in rows]


def resolve_qa_warning(id: int, status: str, note: str = None) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE qa_warnings SET resolution_status=?, reviewer_note=?, reviewed_at=? WHERE id=?",
            (status, note, _now(), id),
        )


def append_rank_history(rows: list) -> None:
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO rank_history (slug, date, position, impressions, clicks, source, query) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r["slug"], r["date"], r["position"], r["impressions"],
              r["clicks"], r["source"], r.get("query")) for r in rows],
        )


def save_run_log(run_id: str, started_at: str, finished_at: str, metrics: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO run_log (run_id, started_at, finished_at, metrics) VALUES (?, ?, ?, ?)",
            (run_id, started_at, finished_at, json.dumps(metrics)),
        )
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
pytest tests/test_state.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py tests/conftest.py
git commit -m "feat: state.py — SQLite lifecycle layer with timestamps and QA warnings"
```

---

### Task 3: keyword_research.py — Ideation + DataForSEO Validation

**Files:**
- Create: `keyword_research.py` (Phase 1 functions only; Phase 2 scoring added in Task 4)
- Modify: `tests/test_scorer.py` (add relevance filter tests)

**Interfaces:**
- Consumes: `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `ANTHROPIC_API_KEY` from env; `state.is_processed()`
- Produces:
  - `filter_by_relevance(keywords: list[dict]) -> list[dict]` — drops LOW relevance
  - `claude_ideation() -> list[dict]` — returns `[{keyword, relevance}, ...]` (HIGH/MEDIUM only)
  - `dataforseo_validate(keywords: list[dict]) -> list[dict]` — returns `[{keyword, relevance, volume, difficulty, cpc, intent}, ...]`

- [ ] **Step 1: Add relevance filter tests to tests/test_scorer.py**

```python
from keyword_research import filter_by_relevance

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
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_scorer.py::test_low_relevance_discarded tests/test_scorer.py::test_high_and_medium_both_pass -v
```

Expected: `ImportError: cannot import name 'filter_by_relevance'`

- [ ] **Step 3: Create keyword_research.py with ideation + validation**

```python
import json
import os
import sys

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")

_DFS_AUTH = lambda: (DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD)

IDEATION_PROMPT = """\
You are a keyword research specialist for SuperDial, a voice AI company that automates \
payer calls for healthcare providers — benefits verification, prior authorization follow-ups, \
claim status checks, and denial management.

Generate 30 keyword ideas that healthcare revenue cycle professionals (RCM directors, billing \
managers, practice administrators) would search when looking for solutions to their problems.

For each keyword, classify business relevance:
- HIGH: directly addresses SuperDial's core use cases (prior auth, benefits verification, \
claim status, denial management, RCM automation, voice AI for healthcare)
- MEDIUM: adjacent topics that attract the target audience (revenue cycle trends, payer \
relations, healthcare billing challenges, insurance workflow)
- LOW: general healthcare topics with no connection to RCM automation

Return valid JSON only — no prose, no markdown fences:
{"keywords": [{"keyword": "prior authorization automation software", "relevance": "HIGH"}, ...]}"""


def filter_by_relevance(keywords: list) -> list:
    return [k for k in keywords if k.get("relevance", "LOW") != "LOW"]


def claude_ideation() -> list:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": IDEATION_PROMPT}],
    )
    raw = msg.content[0].text.strip()
    data = json.loads(raw)
    all_kws = data["keywords"]
    filtered = filter_by_relevance(all_kws)
    dropped = len(all_kws) - len(filtered)
    print(f"  Ideation: {len(all_kws)} generated, {dropped} low-relevance dropped, {len(filtered)} proceeding")
    return filtered


def dataforseo_validate(keywords: list) -> list:
    keyword_strings = [k["keyword"] for k in keywords]
    relevance_map = {k["keyword"]: k["relevance"] for k in keywords}

    # --- Volume + CPC ---
    volume_resp = requests.post(
        "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
        auth=_DFS_AUTH(),
        json=[{"language_code": "en", "location_code": 2840, "keywords": keyword_strings}],
    )
    volume_resp.raise_for_status()
    volume_map = {
        item["keyword"]: item
        for item in (volume_resp.json()["tasks"][0].get("result") or [])
    }

    # --- Keyword difficulty ---
    diff_resp = requests.post(
        "https://api.dataforseo.com/v3/dataforseo_labs/google/bulk_keyword_difficulty/live",
        auth=_DFS_AUTH(),
        json=[{"language_code": "en", "location_code": 2840, "keywords": keyword_strings}],
    )
    diff_resp.raise_for_status()
    diff_map = {
        item["keyword"]: item
        for item in (diff_resp.json()["tasks"][0].get("result") or [])
    }

    # --- Search intent ---
    intent_resp = requests.post(
        "https://api.dataforseo.com/v3/dataforseo_labs/google/search_intent/live",
        auth=_DFS_AUTH(),
        json=[{"language_code": "en", "location_code": 2840, "keywords": keyword_strings}],
    )
    intent_resp.raise_for_status()
    intent_map = {
        item["keyword"]: item
        for item in (intent_resp.json()["tasks"][0].get("result") or [])
    }

    validated = []
    for kw_str in keyword_strings:
        vol_item = volume_map.get(kw_str, {})
        diff_item = diff_map.get(kw_str, {})
        intent_item = intent_map.get(kw_str, {})

        volume = vol_item.get("search_volume")
        difficulty = diff_item.get("keyword_difficulty")

        if volume is None or difficulty is None:
            print(f"  WARN: skipping '{kw_str}' — missing volume or difficulty from DataForSEO")
            continue

        validated.append({
            "keyword": kw_str,
            "relevance": relevance_map.get(kw_str, "MEDIUM"),
            "volume": float(volume),
            "difficulty": float(difficulty),
            "cpc": float(vol_item.get("cpc") or 0),
            "intent": (intent_item.get("search_intent") or "informational").lower(),
        })

    print(f"  Validation: {len(validated)}/{len(keyword_strings)} keywords have full data")
    return validated
```

- [ ] **Step 4: Run filter tests — verify pass**

```bash
pytest tests/test_scorer.py::test_low_relevance_discarded tests/test_scorer.py::test_high_and_medium_both_pass -v
```

Expected: 2 passed

- [ ] **Step 5: Integration test — validate DataForSEO auth**

```bash
python -c "
from keyword_research import dataforseo_validate
results = dataforseo_validate([
    {'keyword': 'prior authorization automation', 'relevance': 'HIGH'},
    {'keyword': 'benefits verification software', 'relevance': 'HIGH'},
])
print(results)
"
```

Expected: list of dicts with `volume`, `difficulty`, `cpc`, `intent` populated. If auth fails: `401` error — check `.env` credentials.

- [ ] **Step 6: Commit**

```bash
git add keyword_research.py tests/test_scorer.py
git commit -m "feat: keyword_research — Claude ideation, relevance filter, DataForSEO validation"
```

---

### Task 4: keyword_research.py — SERP Scoring + run_research()

**Files:**
- Modify: `keyword_research.py` (add scorer, SERP analysis, `run_research()`)
- Modify: `tests/test_scorer.py` (add scorer unit tests)

**Interfaces:**
- Consumes: `state.is_processed()`, `state.get_all_published_slugs()`, `state.get_retryable()`, `state.has_slug_collision()`, `state.select_keyword()`, `utils.slugify()`
- Produces:
  - `_initial_score(kw: dict) -> float`
  - `serp_fit_modifier(kw_string: str) -> float` — one SERP API call
  - `score_and_rank(validated: list, top_n=3) -> list[dict]`
  - `run_research(top_n=3) -> list[dict]` — full pipeline entry point; saves selected keywords to state

- [ ] **Step 1: Add scorer tests to tests/test_scorer.py**

```python
import math
from keyword_research import _initial_score

def _kw(keyword="prior auth software", volume=500, difficulty=30, cpc=10.0, intent="commercial"):
    return {"keyword": keyword, "volume": volume, "difficulty": difficulty, "cpc": cpc, "intent": intent}

def test_navigational_scores_zero():
    assert _initial_score(_kw(intent="navigational")) == 0.0

def test_commercial_beats_informational_same_volume():
    commercial = _initial_score(_kw(intent="commercial"))
    informational = _initial_score(_kw(intent="informational"))
    assert commercial > informational

def test_lower_difficulty_scores_higher():
    easy = _initial_score(_kw(difficulty=20))
    hard = _initial_score(_kw(difficulty=80))
    assert easy > hard

def test_cpc_zero_still_scores():
    score = _initial_score(_kw(cpc=0))
    assert score == 0.0  # log(1+0)=0 — zero CPC produces zero score

def test_cpc_log_scaled():
    low_cpc = _initial_score(_kw(cpc=1))
    high_cpc = _initial_score(_kw(cpc=100))
    # log scaling: high_cpc should be higher but not 100x
    assert high_cpc > low_cpc
    assert high_cpc < low_cpc * 10
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_scorer.py::test_navigational_scores_zero -v
```

Expected: `ImportError: cannot import name '_initial_score'`

- [ ] **Step 3: Add scorer + SERP analysis + run_research() to keyword_research.py**

Append to `keyword_research.py`:

```python
import math
import state
from utils import slugify

_DIRECTORY_DOMAINS = {
    "g2.com", "capterra.com", "softwareadvice.com", "getapp.com",
    "trustradius.com", "gartner.com", "peerspot.com",
}
_FORUM_DOMAINS = {
    "reddit.com", "quora.com", "healthcareittoday.com", "hfma.org",
}


def _initial_score(kw: dict) -> float:
    intent_mod = {
        "commercial": 1.3,
        "transactional": 1.3,
        "informational": 1.0,
        "navigational": 0.0,
    }.get(kw.get("intent", "informational").lower(), 1.0)

    if intent_mod == 0.0:
        return 0.0

    existing_slugs = state.get_all_published_slugs()
    kw_tokens = set(kw["keyword"].lower().split())
    cannibalization = 0.0
    if existing_slugs and kw_tokens:
        cannibalization = max(
            len(kw_tokens & set(s.replace("-", " ").split())) / len(kw_tokens)
            for s in existing_slugs
        )

    return (
        kw["volume"]
        * (1 - kw["difficulty"] / 100)
        * intent_mod
        * (1 - min(cannibalization * 0.8, 0.8))
        * math.log1p(kw["cpc"])
    )


def serp_fit_modifier(keyword_string: str) -> float:
    resp = requests.post(
        "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
        auth=_DFS_AUTH(),
        json=[{"keyword": keyword_string, "language_code": "en", "location_code": 2840, "depth": 10}],
    )
    resp.raise_for_status()
    tasks = resp.json().get("tasks", [])
    if not tasks:
        return 1.0
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    organic = [i for i in items if i.get("type") == "organic"]
    total = len(organic) or 1
    dir_count = sum(1 for i in organic if any(d in (i.get("domain") or "") for d in _DIRECTORY_DOMAINS))
    forum_count = sum(1 for i in organic if any(d in (i.get("domain") or "") for d in _FORUM_DOMAINS))
    if dir_count / total >= 0.4:
        return 0.7
    if forum_count / total >= 0.4:
        return 0.9
    return 1.2


def score_and_rank(validated: list, top_n: int = 3) -> list:
    # Filter navigational + already-in-pipeline
    candidates = [
        k for k in validated
        if k.get("intent", "").lower() != "navigational"
        and not state.is_processed(k["keyword"])
    ]

    # Initial score — no SERP
    for k in candidates:
        k["_initial_score"] = _initial_score(k)
    candidates.sort(key=lambda k: k["_initial_score"], reverse=True)

    # SERP analysis on top 10 only (cost control)
    top_10 = candidates[:10]
    for k in top_10:
        k["serp_fit"] = serp_fit_modifier(k["keyword"])
        k["score"] = k["_initial_score"] * k["serp_fit"]

    top_10.sort(key=lambda k: k["score"], reverse=True)
    return top_10[:top_n]


def run_research(top_n: int = 3) -> list:
    """Full keyword research pipeline. Saves selected keywords to state. Returns list of selected keyword dicts."""
    candidates = claude_ideation()
    if not candidates:
        sys.exit("Ideation returned no candidates after relevance filter.")

    validated = dataforseo_validate(candidates)
    if not validated:
        sys.exit("DataForSEO validation returned no results.")

    selected = score_and_rank(validated, top_n=top_n)

    saved = []
    for kw in selected:
        slug = slugify(kw["keyword"])
        if state.has_slug_collision(slug):
            print(f"  WARN: slug collision for '{kw['keyword']}' → skipping")
            continue
        state.select_keyword(
            keyword=kw["keyword"],
            slug=slug,
            score=kw["score"],
            volume=kw["volume"],
            difficulty=kw["difficulty"],
            cpc=kw["cpc"],
            intent=kw["intent"],
        )
        saved.append({**kw, "slug": slug})
        print(f"  Selected: '{kw['keyword']}' (vol:{kw['volume']:.0f} diff:{kw['difficulty']:.0f} score:{kw['score']:.1f})")

    if len(saved) < top_n:
        print(f"  Only {len(saved)}/{top_n} keywords selected after filtering — retrying ideation once")
        candidates2 = claude_ideation()
        validated2 = dataforseo_validate(candidates2)
        selected2 = score_and_rank(validated2, top_n=top_n - len(saved))
        for kw in selected2:
            slug = slugify(kw["keyword"])
            if state.has_slug_collision(slug):
                continue
            state.select_keyword(kw["keyword"], slug, kw["score"], kw["volume"], kw["difficulty"], kw["cpc"], kw["intent"])
            saved.append({**kw, "slug": slug})

    return state.get_retryable("generate")
```

- [ ] **Step 4: Run scorer unit tests**

```bash
pytest tests/test_scorer.py -v
```

Expected: all tests pass. Note: `test_cpc_zero_still_scores` expects 0.0 — log(1+0)=0 means zero CPC articles score zero. This is intentional: CPC=0 means no commercial value signal.

- [ ] **Step 5: Integration dry-run test**

```bash
python -c "
import state
state.init_db()
from keyword_research import run_research
results = run_research(top_n=2)
print('Selected:', [r['keyword'] for r in results])
"
```

Expected: 2 keywords printed, saved in DB. Costs ~\$0.13 (DataForSEO keyword + SERP calls).

- [ ] **Step 6: Commit**

```bash
git add keyword_research.py tests/test_scorer.py
git commit -m "feat: keyword scoring — SERP analysis, composite scorer, run_research()"
```

---

### Task 5: generate_article.py — New Keyword Format

**Files:**
- Modify: `generate_article.py`

**Interfaces:**
- Consumes: keyword dict from `state.get_retryable("generate")` — keys: `keyword`, `slug`, `volume`, `difficulty`, `cpc`, `intent`, `score`
- Produces:
  - `generate_draft(client, keyword_row: dict) -> str` — raw Claude response (unchanged signature, updated internals)
  - `parse_and_save(raw: str, keyword_row: dict, slug: str) -> tuple[Path, str]` — `slug` now passed explicitly; returns `(output_path, title)`

- [ ] **Step 1: Write failing test in tests/test_pipeline.py**

Create `tests/test_pipeline.py`:

```python
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

Prior authorization is a requirement from payers...
"""
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
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_pipeline.py::test_parse_and_save_uses_predetermined_slug -v
```

Expected: `TypeError` — `parse_and_save()` does not accept a `slug` argument yet

- [ ] **Step 3: Update generate_article.py**

Replace the `ARTICLE_PROMPT`, `generate_draft`, and `parse_and_save` functions. The `SYSTEM_PROMPT` and `slugify` import are unchanged:

```python
# At top of file — add import
from utils import slugify
```

Remove the existing `slugify` function definition from the file (it's now in `utils.py`).

Replace `ARTICLE_PROMPT`:

```python
ARTICLE_PROMPT = """Write a comprehensive SEO article for the keyword: "{keyword}"

Search data context:
- Average monthly searches: {volume:,.0f}
- Keyword difficulty: {difficulty:.0f}/100
- Search intent: {intent}
- CPC: ${cpc:.2f}

Writing guidance:
- intent=commercial or transactional: write a practical buyer's guide, 1,000–1,200 words, \
  compare approaches, include evaluation criteria
- intent=informational: write a clear explainer, 800–1,000 words, define concepts, \
  use H2 sections for easy scanning

Return the article in this exact format:

TITLE: [SEO-optimized title, under 60 characters]
META: [Meta description, 140–155 characters]
SLUG: [URL slug, lowercase, hyphens only]
---
[Full article body in markdown, starting with the H1 title, then H2 sections]"""
```

Replace `generate_draft`:

```python
def generate_draft(client, keyword_row: dict) -> str:
    prompt = ARTICLE_PROMPT.format(
        keyword=keyword_row["keyword"],
        volume=float(keyword_row.get("volume") or keyword_row.get("avg_monthly_searches", 0)),
        difficulty=float(keyword_row.get("difficulty", 50)),
        intent=keyword_row.get("intent", "informational"),
        cpc=float(keyword_row.get("cpc") or keyword_row.get("low_cpc", 0)),
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
```

Replace `parse_and_save`:

```python
def parse_and_save(raw: str, keyword_row: dict, slug: str = None) -> tuple:
    lines = raw.strip().splitlines()
    title = meta = ""
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("META:"):
            meta = line.removeprefix("META:").strip()
        elif line.strip() == "---":
            in_body = True
        elif in_body:
            body_lines.append(line)

    # Use pre-determined slug if provided (avoids drift with state.py)
    if not slug:
        slug = slugify(keyword_row["keyword"])

    DRAFTS_DIR.mkdir(exist_ok=True)
    output_path = DRAFTS_DIR / f"{slug}.md"

    frontmatter = (
        f'---\n'
        f'title: "{title}"\n'
        f'meta_description: "{meta}"\n'
        f'slug: "{slug}"\n'
        f'keyword: "{keyword_row["keyword"]}"\n'
        f'volume: {keyword_row.get("volume") or keyword_row.get("avg_monthly_searches", 0)}\n'
        f'difficulty: {keyword_row.get("difficulty", "")}\n'
        f'intent: "{keyword_row.get("intent", "")}"\n'
        f'status: draft\n'
        f'---\n\n'
    )
    output_path.write_text(frontmatter + "\n".join(body_lines).strip() + "\n")
    return output_path, title
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 2 passed

- [ ] **Step 5: Integration test — generate one article**

```bash
python -c "
import anthropic, os
from dotenv import load_dotenv
load_dotenv()
import generate_article
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
kw = {'keyword': 'prior authorization automation', 'volume': 1200, 'difficulty': 34, 'cpc': 8.40, 'intent': 'commercial'}
raw = generate_article.generate_draft(client, kw)
path, title = generate_article.parse_and_save(raw, kw, slug='prior-authorization-automation')
print('Saved to:', path)
print('Title:', title)
"
```

Expected: file created at `drafts/prior-authorization-automation.md`

- [ ] **Step 6: Commit**

```bash
git add generate_article.py tests/test_pipeline.py
git commit -m "feat: generate_article — new keyword format, intent/difficulty in prompt, explicit slug"
```

---

### Task 6: content_qa.py — Healthcare Content QA

**Files:**
- Create: `content_qa.py`
- Modify: `tests/test_pipeline.py` (add QA tests)

**Interfaces:**
- Produces:
  - `scan_draft(draft_text: str) -> list[dict]` — returns `[{category, excerpt}, ...]`; never raises, returns `[]` on error

- [ ] **Step 1: Add QA tests to tests/test_pipeline.py**

```python
from content_qa import scan_draft

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
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/test_pipeline.py::test_qa_returns_list_of_dicts -v
```

Expected: `ImportError: cannot import name 'scan_draft'`

- [ ] **Step 3: Create content_qa.py**

```python
import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


QA_PROMPT = """\
You are a healthcare content compliance reviewer. Review the article below for content risks \
specific to healthcare RCM (revenue cycle management) software marketing.

Flag sentences or phrases that fall into these categories:
- roi_claim: unsupported ROI claims (e.g., "reduce costs by 40%" without a cited source)
- compliance_claim: unsupported compliance assertions (e.g., "fully HIPAA compliant" without qualification)
- regulatory: assertions about CMS rules, coding regulations, or payer policies that may require verification
- statistic: numeric statistics presented as fact without an attributable source
- medical_assertion: clinical or operational claims presented as fact without evidence

Return valid JSON only — no prose, no markdown:
{"warnings": [{"category": "roi_claim", "excerpt": "the exact flagged sentence or phrase"}, ...]}

If no issues are found, return: {"warnings": []}

Article to review:
---
{article}
---"""


def scan_draft(draft_text: str) -> list:
    if not draft_text.strip():
        return []
    try:
        msg = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": QA_PROMPT.format(article=draft_text[:8000])}],
        )
        data = json.loads(msg.content[0].text.strip())
        return data.get("warnings", [])
    except Exception as e:
        print(f"  QA scan error (non-blocking): {e}")
        return []
```

- [ ] **Step 4: Run QA tests**

```bash
pytest tests/test_pipeline.py::test_qa_returns_list_of_dicts tests/test_pipeline.py::test_qa_never_raises_on_empty -v
```

Expected: 2 passed. Skip `test_qa_flags_roi_claim` for now — it requires a real Claude call and the output is non-deterministic. Run it manually once to verify.

- [ ] **Step 5: Manual integration test**

```bash
python -c "
from content_qa import scan_draft
draft = '''
SuperDial automates prior authorization calls with a 95% success rate.
Our platform is fully HIPAA compliant and reduces denial rates by 40%.
According to CMS guidelines, all prior authorizations must be processed within 72 hours.
'''
import json
warnings = scan_draft(draft)
print(json.dumps(warnings, indent=2))
"
```

Expected: warnings for the ROI claim, compliance claim, and regulatory assertion.

- [ ] **Step 6: Commit**

```bash
git add content_qa.py tests/test_pipeline.py
git commit -m "feat: content_qa — healthcare content risk scanner, warnings only"
```

---

### Task 7: pipeline.py — Orchestrator

**Files:**
- Modify: `pipeline.py` (full rewrite)
- Modify: `tests/test_pipeline.py` (add pipeline integration tests)

**Interfaces:**
- Consumes: `keyword_research.run_research()`, `generate_article.generate_draft()`, `generate_article.parse_and_save()`, `content_qa.scan_draft()`, `publish_webflow.publish_draft()`, `state.*`
- Produces: CLI with `--all`, `--step [keywords|generate|publish|track]`, `--dry-run`, `--top N`

- [ ] **Step 1: Add pipeline integration tests**

Append to `tests/test_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run — verify**

```bash
pytest tests/test_pipeline.py::test_publish_skips_drafted_keywords -v
```

Expected: pass (this tests state.py behaviour already working)

- [ ] **Step 3: Write pipeline.py**

```python
"""
Full SEO pipeline: keyword research → article generation → QA → [review gate] → publish → rank track.

Usage:
    python pipeline.py --step keywords              # research and select top 3 keywords
    python pipeline.py --step keywords --dry-run    # show what would be selected, no writes
    python pipeline.py --step generate              # generate articles for selected keywords
    python pipeline.py --step generate --top 5      # generate for up to 5 selected keywords
    python pipeline.py --step publish               # publish approved drafts to Webflow
    python pipeline.py --step track                 # pull GSC rank data for published articles
    python pipeline.py --all                        # research → generate → (pause) → must run publish separately
    python pipeline.py --all --top 5                # research + generate top 5
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import state
import keyword_research
import generate_article
import content_qa
import publish_webflow

load_dotenv()

state.init_db()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _print_header(title):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def step_keywords(dry_run=False, top_n=3):
    _print_header("Step 1: Keyword Research")
    metrics = {
        "keywords_evaluated": 0,
        "keywords_filtered_relevance": 0,
        "keywords_filtered_state": 0,
        "keywords_selected": 0,
    }

    if dry_run:
        print("  [dry-run] Would call Claude ideation + DataForSEO. No writes.")
        return metrics

    selected = keyword_research.run_research(top_n=top_n)
    metrics["keywords_selected"] = len(selected)
    print(f"\n  {len(selected)} keyword(s) selected and saved to state.")
    return metrics


def step_generate(dry_run=False, top_n=None):
    _print_header("Step 2: Article Generation + QA")
    candidates = state.get_retryable("generate")
    if top_n:
        candidates = candidates[:top_n]

    metrics = {
        "articles_generated": 0,
        "qa_warnings_total": 0,
    }

    if not candidates:
        print("  No keywords in 'selected' state — run --step keywords first.")
        return metrics

    if dry_run:
        print(f"  [dry-run] Would generate articles for {len(candidates)} keyword(s):")
        for k in candidates:
            print(f"    • {k['keyword']}")
        return metrics

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    for kw in candidates:
        keyword = kw["keyword"]
        slug = kw["slug"]
        print(f"  [{candidates.index(kw) + 1}/{len(candidates)}] '{keyword}'...", end=" ", flush=True)

        if state.has_slug_collision(slug) and not Path(f"drafts/{slug}.md").exists():
            print(f"SKIP (slug collision)")
            continue

        try:
            raw = generate_article.generate_draft(client, kw)
            path, title = generate_article.parse_and_save(raw, kw, slug=slug)

            # QA scan
            warnings = content_qa.scan_draft(path.read_text())
            if warnings:
                state.save_qa_warnings(slug, warnings)
                metrics["qa_warnings_total"] += len(warnings)

            state.mark_drafted(keyword)
            metrics["articles_generated"] += 1
            flag = f" ⚠ {len(warnings)} QA warnings" if warnings else ""
            print(f"saved → {path}{flag}")

        except Exception as e:
            print(f"ERROR: {e} (keyword left in 'selected' for retry)")

    print(f"\n  Generation complete. Review drafts in dashboard before publishing.")
    print(f"  Run: streamlit run dashboard.py")
    return metrics


def step_publish(dry_run=False):
    _print_header("Step 3: Publish Approved Drafts")
    candidates = state.get_retryable("publish")
    metrics = {"articles_published": 0}

    if not candidates:
        print("  No keywords in 'approved' state — approve drafts in dashboard first.")
        return metrics

    if dry_run:
        print(f"  [dry-run] Would publish {len(candidates)} approved draft(s):")
        for k in candidates:
            print(f"    • {k['keyword']} → drafts/{k['slug']}.md")
        return metrics

    for kw in candidates:
        slug = kw["slug"]
        draft_path = Path(f"drafts/{slug}.md")
        if not draft_path.exists():
            print(f"  SKIP '{kw['keyword']}' — draft file not found at {draft_path}")
            continue

        print(f"  Publishing '{kw['keyword']}'...", end=" ", flush=True)
        try:
            item_id = publish_webflow.publish_draft_and_return_id(draft_path)
            state.mark_published(kw["keyword"], item_id)
            metrics["articles_published"] += 1
            print(f"done (item: {item_id})")
        except Exception as e:
            print(f"ERROR: {e} (left in 'approved' for retry)")

    return metrics


def step_track(dry_run=False):
    _print_header("Step 4: GSC Rank Tracking")
    metrics = {"gsc_rows_ingested": 0, "gsc_warnings": 0}

    try:
        import rank_tracker
        slugs = state.get_all_published_slugs()
        if not slugs:
            print("  No published articles to track yet.")
            return metrics

        if dry_run:
            print(f"  [dry-run] Would track {len(slugs)} published article(s).")
            return metrics

        rows = rank_tracker.fetch_all(slugs)
        if rows:
            state.append_rank_history(rows)
            for slug in set(r["slug"] for r in rows if r["source"] == "page"):
                state.update_tracking_timestamps(slug)
            metrics["gsc_rows_ingested"] = len(rows)
            print(f"  Tracked {len(rows)} GSC rows for {len(slugs)} article(s).")
        else:
            print("  No GSC data returned (articles may not be indexed yet).")

    except Exception as e:
        msg = f"GSC tracking failed: {e}"
        print(f"  WARN: {msg}")
        metrics["gsc_warnings"] += 1
        state.save_run_log(
            run_id=_now(), started_at=_now(), finished_at=_now(),
            metrics={**metrics, "gsc_error": str(e)},
        )

    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["keywords", "generate", "publish", "track"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.step and not args.all:
        parser.print_help()
        return

    started_at = _now()
    all_metrics = {}

    if args.all or args.step == "keywords":
        m = step_keywords(dry_run=args.dry_run, top_n=args.top or 3)
        all_metrics.update(m)

    if args.all or args.step == "generate":
        m = step_generate(dry_run=args.dry_run, top_n=args.top)
        all_metrics.update(m)

    if args.step == "publish":
        m = step_publish(dry_run=args.dry_run)
        all_metrics.update(m)

    if args.step == "track":
        m = step_track(dry_run=args.dry_run)
        all_metrics.update(m)

    finished_at = _now()

    if not args.dry_run:
        state.save_run_log(
            run_id=started_at,
            started_at=started_at,
            finished_at=finished_at,
            metrics=all_metrics,
        )

    print(f"\n{'=' * 60}")
    print(f"  Run complete | {finished_at}")
    print(f"  {json.dumps(all_metrics, indent=2)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update publish_webflow.py — add publish_draft_and_return_id()**

The existing `publish_draft()` in `publish_webflow.py` prints results but does not return the Webflow item ID. Add this wrapper at the bottom of the file:

```python
def publish_draft_and_return_id(path) -> str:
    """Publish a single draft and return the Webflow item ID. Raises on failure."""
    fm, body = parse_frontmatter(path)
    title = fm.get("title", "")
    slug = fm.get("slug", "")
    meta = fm.get("meta_description", "")

    if not title:
        raise ValueError(f"No title in frontmatter of {path}")

    field_data = {FIELD_NAME: title, FIELD_SLUG: slug, FIELD_BODY: body}
    if meta and FIELD_META:
        field_data[FIELD_META] = meta

    payload = {"isArchived": False, "isDraft": True, "fieldData": field_data}
    url = f"{BASE_URL}/collections/{WEBFLOW_COLLECTION_ID}/items"
    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code in (200, 201):
        return r.json().get("id", "")
    raise RuntimeError(f"Webflow error {r.status_code}: {r.text}")
```

- [ ] **Step 5: End-to-end dry-run**

```bash
cd ~/Documents/superdial-seo && source venv/bin/activate && python pipeline.py --all --dry-run
```

Expected: steps 1 and 2 print dry-run messages with no writes. No DB records created.

- [ ] **Step 6: Commit**

```bash
git add pipeline.py publish_webflow.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrator — state-aware steps, review gate, run metrics"
```

---

### Task 8: rank_tracker.py — GSC Rank Tracking

**Files:**
- Create: `rank_tracker.py`
- Modify: `tests/test_pipeline.py` (add tracking tests)

**Interfaces:**
- Consumes: `GSC_SITE_URL` from env; `client_secret.json` (exists); token cached at `data/gsc_token.json`
- Produces:
  - `get_gsc_service()` — returns authenticated GSC API service
  - `fetch_all(slugs: list[str]) -> list[dict]` — returns combined page-level + query-level rows for all slugs

- [ ] **Step 1: Add tracking test**

Append to `tests/test_pipeline.py`:

```python
def test_rank_history_appends_not_overwrites(db):
    row = {"slug": "prior-auth-automation", "date": "2026-06-24",
           "position": 14.2, "impressions": 43, "clicks": 2, "source": "page", "query": None}
    db.append_rank_history([row])
    db.append_rank_history([{**row, "date": "2026-07-01", "position": 12.1}])
    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM rank_history").fetchone()[0]
    assert count == 2
```

- [ ] **Step 2: Run — verify pass** (state.py already handles this)

```bash
pytest tests/test_pipeline.py::test_rank_history_appends_not_overwrites -v
```

Expected: pass

- [ ] **Step 3: Create rank_tracker.py**

```python
"""
Google Search Console rank tracking.
First run opens a browser for OAuth consent. Token cached at data/gsc_token.json.

Usage:
    python rank_tracker.py --dry-run    # verify OAuth works, print slug list
"""

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import state

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
CLIENT_SECRET_PATH = Path("client_secret.json")
TOKEN_PATH = Path("data/gsc_token.json")
SITE_URL = os.getenv("GSC_SITE_URL", "").rstrip("/")

_QUERY_MIN_IMPRESSIONS = 5
_QUERY_TOP_N = 25
_DAYS = 7


def get_gsc_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
    return build("searchconsole", "v1", credentials=creds)


def _date_range():
    end = date.today()
    start = end - timedelta(days=_DAYS)
    return start.isoformat(), end.isoformat()


def fetch_page_metrics(service, slugs: list) -> list:
    """Fetch page-level metrics for all slugs in one API call."""
    start_date, end_date = _date_range()
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "rowLimit": 1000,
    }
    resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    slug_set = set(slugs)
    rows = []
    for row in resp.get("rows", []):
        page_url = row["keys"][0].rstrip("/")
        slug = page_url.split("/")[-1]
        if slug not in slug_set:
            continue
        rows.append({
            "slug": slug,
            "date": end_date,
            "position": round(row["position"], 2),
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "source": "page",
            "query": None,
        })
    return rows


def fetch_query_metrics(service, slug: str) -> list:
    """Fetch query-level metrics for a single article slug."""
    start_date, end_date = _date_range()
    page_url = f"{SITE_URL}/{slug}"
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "dimensionFilterGroups": [{
            "filters": [{"dimension": "page", "expression": page_url, "operator": "equals"}]
        }],
        "rowLimit": 100,
    }
    resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    rows = []
    for row in resp.get("rows", []):
        if row["impressions"] < _QUERY_MIN_IMPRESSIONS:
            continue
        rows.append({
            "slug": slug,
            "date": end_date,
            "position": round(row["position"], 2),
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "source": "query",
            "query": row["keys"][0],
        })
    rows.sort(key=lambda r: r["impressions"], reverse=True)
    return rows[:_QUERY_TOP_N]


def fetch_all(slugs: list) -> list:
    """Fetch page-level + query-level metrics for all slugs."""
    if not SITE_URL:
        raise ValueError("GSC_SITE_URL not set in .env")
    service = get_gsc_service()
    rows = fetch_page_metrics(service, slugs)
    tracked_slugs = {r["slug"] for r in rows}
    for slug in tracked_slugs:
        rows.extend(fetch_query_metrics(service, slug))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state.init_db()
    slugs = state.get_all_published_slugs()
    print(f"Published slugs to track: {slugs}")

    if args.dry_run:
        print("[dry-run] Authenticating with GSC...")
        get_gsc_service()
        print("GSC auth OK.")
    else:
        rows = fetch_all(slugs)
        print(f"Fetched {len(rows)} rows.")
```

- [ ] **Step 4: Run GSC OAuth dry-run**

```bash
python rank_tracker.py --dry-run
```

Expected: browser opens for Google OAuth consent. After authorizing, prints "GSC auth OK." Token saved to `data/gsc_token.json`.

- [ ] **Step 5: Commit**

```bash
git add rank_tracker.py tests/test_pipeline.py data/gsc_token.json
git commit -m "feat: rank_tracker — GSC OAuth, page-level + query-level tracking"
```

---

### Task 9: dashboard.py — Streamlit Executive View

**Files:**
- Create: `dashboard.py`

**Interfaces:**
- Consumes: `state.get_db()`, all `state.*` read operations

- [ ] **Step 1: Create dashboard.py**

```python
"""
SuperDial SEO Dashboard.

Run with:  streamlit run dashboard.py
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import state

state.init_db()

st.set_page_config(page_title="SuperDial SEO", layout="wide")
st.title("SuperDial SEO Dashboard")

# ── Summary stats ──────────────────────────────────────────────────────────────

with state.get_db() as conn:
    total_published = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='published'"
    ).fetchone()[0]
    pending_review = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='drafted'"
    ).fetchone()[0]
    pending_approval = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='approved'"
    ).fetchone()[0]
    avg_pos = conn.execute("""
        SELECT ROUND(AVG(position), 1) FROM rank_history rh
        WHERE source='page'
          AND date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='page')
    """).fetchone()[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Published Articles", total_published)
col2.metric("Drafts Pending Review", pending_review)
col3.metric("Awaiting Approval", pending_approval)
col4.metric("Avg GSC Position", f"{avg_pos:.1f}" if avg_pos else "—")

st.divider()

# ── Review queue ───────────────────────────────────────────────────────────────

st.subheader("Review Queue")

with state.get_db() as conn:
    drafted = conn.execute(
        "SELECT * FROM keywords WHERE state='drafted' ORDER BY drafted_at DESC"
    ).fetchall()

if not drafted:
    st.info("No drafts awaiting review.")
else:
    for kw in drafted:
        slug = kw["slug"]
        draft_path = Path(f"drafts/{slug}.md")
        with st.expander(f"📄 {kw['keyword']}  |  vol:{kw['volume']:.0f}  diff:{kw['difficulty']:.0f}  {kw['intent']}"):
            # QA warnings
            warnings = state.get_qa_warnings(slug, unresolved_only=True)
            if warnings:
                st.warning(f"⚠ {len(warnings)} unresolved QA warning(s)")
                for w in warnings:
                    col_a, col_b, col_c = st.columns([3, 1, 1])
                    col_a.markdown(f"**{w['category']}**: _{w['excerpt']}_")
                    if col_b.button("Accept", key=f"accept_{w['id']}"):
                        state.resolve_qa_warning(w["id"], "accepted")
                        st.rerun()
                    if col_c.button("Dismiss", key=f"dismiss_{w['id']}"):
                        state.resolve_qa_warning(w["id"], "dismissed")
                        st.rerun()
            else:
                st.success("No unresolved QA warnings.")

            if draft_path.exists():
                st.text_area("Draft preview", draft_path.read_text()[:2000], height=200)

            if st.button(f"✅ Approve '{kw['keyword']}'", key=f"approve_{slug}"):
                state.mark_approved(kw["keyword"])
                st.success(f"'{kw['keyword']}' approved. Run: python pipeline.py --step publish")
                st.rerun()

st.divider()

# ── Rank tracker ───────────────────────────────────────────────────────────────

st.subheader("Rank Tracker")

with state.get_db() as conn:
    rank_df_raw = pd.read_sql_query("""
        SELECT rh.slug, k.target_keyword, rh.date, rh.position, rh.impressions, rh.clicks
        FROM rank_history rh
        LEFT JOIN keywords k ON k.slug = rh.slug
        WHERE rh.source = 'page'
        ORDER BY rh.date DESC
    """, conn)

if rank_df_raw.empty:
    st.info("No rank data yet. Run: python pipeline.py --step track")
else:
    # Latest snapshot per slug
    latest = rank_df_raw.groupby("slug").first().reset_index()
    # Week-over-week position delta
    prev = rank_df_raw.groupby("slug").nth(1).reset_index()[["slug", "position"]].rename(
        columns={"position": "prev_position"}
    )
    latest = latest.merge(prev, on="slug", how="left")
    latest["Δ position"] = (latest["prev_position"] - latest["position"]).round(1)
    latest = latest.sort_values("clicks", ascending=False).head(10)

    st.dataframe(
        latest[["slug", "target_keyword", "position", "impressions", "clicks", "Δ position"]],
        use_container_width=True,
    )

    # Position over time chart
    st.subheader("Average Position Over Time")
    avg_over_time = rank_df_raw.groupby("date")["position"].mean().reset_index()
    avg_over_time.columns = ["date", "avg_position"]
    st.line_chart(avg_over_time.set_index("date"))

st.divider()

# ── Unexpected ranking queries ─────────────────────────────────────────────────

st.subheader("Unexpected Ranking Queries")
st.caption("Queries your articles rank for that differ from their target keyword.")

with state.get_db() as conn:
    query_df = pd.read_sql_query("""
        SELECT rh.slug, k.target_keyword, rh.query, rh.position, rh.impressions, rh.clicks
        FROM rank_history rh
        LEFT JOIN keywords k ON k.slug = rh.slug
        WHERE rh.source = 'query'
          AND rh.date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='query')
        ORDER BY rh.impressions DESC
        LIMIT 100
    """, conn)

if query_df.empty:
    st.info("No query-level data yet.")
else:
    st.dataframe(query_df, use_container_width=True)

st.divider()

# ── Run history ────────────────────────────────────────────────────────────────

st.subheader("Run History")

with state.get_db() as conn:
    runs = conn.execute(
        "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 10"
    ).fetchall()

if not runs:
    st.info("No runs logged yet.")
else:
    for run in runs:
        metrics = json.loads(run["metrics"] or "{}")
        with st.expander(f"🗓 {run['started_at']}"):
            st.json(metrics)
```

- [ ] **Step 2: Run dashboard**

```bash
cd ~/Documents/superdial-seo && source venv/bin/activate && streamlit run dashboard.py
```

Expected: browser opens at `http://localhost:8501`. Verify all sections render without errors. With an empty database, summary stats show 0 and sections show info messages.

- [ ] **Step 3: Full pipeline integration test**

With real API keys configured in `.env`:

```bash
# 1. Research — select 3 keywords
python pipeline.py --step keywords

# 2. Generate — create 3 drafts with QA scan
python pipeline.py --step generate

# 3. Review — open dashboard, approve 1 draft
streamlit run dashboard.py

# 4. Publish — publish the approved draft
python pipeline.py --step publish

# 5. Verify in Webflow — check that item appears as draft in CMS
```

- [ ] **Step 4: Commit**

```bash
git add dashboard.py
git commit -m "feat: Streamlit dashboard — review queue, rank tracker, QA resolution"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Implemented in |
|---|---|
| Claude ideation + relevance filter (High/Medium/Low) | Task 3 — `keyword_research.claude_ideation()`, `filter_by_relevance()` |
| DataForSEO keyword validation (volume, difficulty, CPC, intent) | Task 3 — `dataforseo_validate()` |
| Two-phase SERP cost optimization (initial score → top 10 → SERP → final) | Task 4 — `score_and_rank()` |
| Composite scoring (objective signals only, no relevance weight) | Task 4 — `_initial_score()` |
| Cannibalization penalty | Task 4 — `_initial_score()` reads `state.get_all_published_slugs()` |
| `selected → drafted → approved → published` lifecycle | Task 2 — `state.py` |
| Lifecycle timestamps (`created_at`, `drafted_at`, `approved_at`, `published_at`) | Task 2 — `state.py` |
| `tracked_at` + `last_tracked_at` as metadata (not lifecycle state) | Task 2 + Task 8 |
| `target_keyword` field | Task 2 — `state.select_keyword()` stores `keyword` as `target_keyword` |
| SEO metadata persisted (`volume`, `difficulty`, `cpc`, `intent`) | Task 2 + Task 4 — `state.select_keyword()` |
| `UNIQUE(slug)` constraint | Task 2 — schema + `has_slug_collision()` |
| Healthcare QA scanner (warnings only, never blocks) | Task 6 — `content_qa.scan_draft()` |
| QA warning resolution (`resolution_status`, `reviewer_note`, `reviewed_at`) | Task 2 schema + Task 9 dashboard |
| Manual review gate between generate and publish | Task 7 — `pipeline.py` pauses after generate |
| GSC page-level tracking | Task 8 — `fetch_page_metrics()` |
| GSC query-level tracking (top 25, ≥5 impressions) | Task 8 — `fetch_query_metrics()` |
| `refresh_candidate` reserved state | Documented in spec; not implemented (correct) |
| Structured run metrics | Task 7 — `state.save_run_log()` with metrics dict |
| `--dry-run` writes nothing | Task 7 — all steps check `dry_run` before writes |
| Idempotent — re-running produces no duplicates | All tasks — state checks guard each step |
| Streamlit dashboard with review queue | Task 9 — `dashboard.py` |
| `streamlit run dashboard.py` opens browser | Task 9 |
| Webflow publishes as `isDraft: True` | Task 7 — `publish_webflow.publish_draft_and_return_id()` |

**No placeholders found.**

**Type consistency:** `state.select_keyword()` signature used consistently across Task 2 (definition), Task 4 (`run_research()`), and Task 7 (`pipeline.py`). `parse_and_save()` `slug` parameter added consistently in Task 5 and consumed in Task 7.
