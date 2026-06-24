import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("PIPELINE_DB", "data/pipeline.db"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
        conn.execute(
            """UPDATE keywords
               SET tracked_at = CASE WHEN tracked_at IS NULL THEN ? ELSE tracked_at END,
                   last_tracked_at = ?
               WHERE slug = ?""",
            (now, now, slug),
        )


def is_processed(keyword: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM keywords WHERE keyword=?", (keyword,)).fetchone()
        return row is not None


def has_slug_collision(slug: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM keywords WHERE slug=?", (slug,)).fetchone()
        return row is not None


def get_retryable(step: str) -> list:
    step_to_prior = {"generate": "selected", "publish": "approved", "track": "published"}
    if step not in step_to_prior:
        raise ValueError(f"Invalid step '{step}'; must be one of {list(step_to_prior)}")
    prior = step_to_prior[step]
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


def resolve_qa_warning(warning_id: int, status: str, note: str = None) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE qa_warnings SET resolution_status=?, reviewer_note=?, reviewed_at=? WHERE id=?",
            (status, note, _now(), warning_id),
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
