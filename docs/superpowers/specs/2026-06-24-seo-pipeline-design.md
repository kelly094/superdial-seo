# SEO Pipeline V2 Design
**Date:** 2026-06-24
**Status:** Approved (rev 4 — tracking separated from lifecycle, QA resolution, simplified scoring)

## Overview

A weekly content production pipeline that replaces SemRush for SuperDial's SEO strategy. Claude generates keyword ideas and classifies business relevance as a filter; DataForSEO provides objective search signals; Claude writes articles; a lightweight QA validator flags healthcare content risks; a human reviews and approves drafts; the pipeline publishes approved content to Webflow CMS. Google Search Console tracks rank performance at both page and query level over time. A Streamlit dashboard provides an on-demand executive view.

**Goal:** Publish 3 SEO articles per week, track their rankings, and surface performance trends — for under $1/month in API costs.

---

## Architecture

Builds on the existing `superdial-seo/` codebase. `keyword_pull.py` is replaced by `keyword_research.py`. Five new modules are added. Existing `generate_article.py` and `publish_webflow.py` are largely unchanged.

```
pipeline.py  (weekly orchestrator — updated)
    │
    ├── keyword_research.py  (NEW — replaces keyword_pull.py)
    │       ├── claude_ideation()      → 30 keyword candidates + relevance classification
    │       ├── dataforseo_validate()  → volume, difficulty, intent, CPC per keyword
    │       ├── dataforseo_serp()      → SERP composition for top 10 candidates only
    │       └── score_and_rank()       → composite score, objective signals only
    │
    ├── generate_article.py  (existing — minor prompt update)
    │
    ├── content_qa.py        (NEW — healthcare content validation)
    │       └── flags unsupported claims, statistics, regulatory assertions
    │
    ├── publish_webflow.py   (existing — unchanged)
    │
    ├── rank_tracker.py      (NEW — Google Search Console API)
    │       ├── page-level metrics per slug (position, impressions, clicks)
    │       └── query-level metrics per article (top 25 per run, ≥5 impressions)
    │
    ├── state.py             (NEW — keyword lifecycle + run history)
    │       └── SQLite — keyword states, timestamps, metadata, rank history
    │
    └── dashboard.py         (NEW — Streamlit executive view + review queue)
```

**File structure additions:**
```
data/
└── pipeline.db           ← SQLite (single source of truth)
docs/superpowers/specs/   ← design docs
tests/
├── test_scorer.py
├── test_state.py
└── test_pipeline.py
```

---

## State Lifecycle

Content lifecycle ends at `published`. Tracking is a recurring monitoring activity, not a terminal state — it continues indefinitely after publication and is recorded via timestamps rather than a state transition.

```
selected → drafted → approved → published
```

| State | Set when | Retryable if stuck |
|---|---|---|
| `selected` | Keyword chosen by scorer | Always — re-runs research |
| `drafted` | Article saved to `drafts/` + QA warnings stored | `--step generate` reruns generation only |
| `approved` | Human marks draft approved in dashboard or CLI | Manual — reviewer action required |
| `published` | Webflow item created (item ID saved) | `--step publish` retries all `approved` |

Tracking timestamps (`tracked_at`, `last_tracked_at`) are updated on each GSC run as metadata on the `published` record. They record when monitoring began and when it last ran — they do not represent a content state change.

**`refresh_candidate` (reserved, not yet implemented)**
A future state for `published` articles that meet criteria for a content refresh (e.g., declining position, outdated statistics, new competitive content). Mature SEO programs derive significant gains from refreshing existing content. The schema intentionally reserves room for this workflow; no logic is implemented in V2.

**Idempotency:** Every step checks state before acting. Re-running any step is safe — it skips work already done and only processes items in the correct prior state. Running `--all` twice produces no duplicates.

---

## Database Schema

Single `pipeline.db` SQLite file in `data/`.

```sql
-- Keyword and article lifecycle
keywords (
    id              INTEGER PRIMARY KEY,
    keyword         TEXT NOT NULL UNIQUE,
    target_keyword  TEXT NOT NULL,          -- canonical keyword this article targets (for GSC comparison)
    state           TEXT NOT NULL,          -- selected|drafted|approved|published|refresh_candidate
    slug            TEXT,
    webflow_item_id TEXT,
    score           REAL,
    -- SEO metadata captured at selection time
    volume          REAL,
    difficulty      REAL,
    cpc             REAL,
    intent          TEXT,
    -- Content lifecycle timestamps
    created_at      TEXT,                   -- when selected by scorer
    drafted_at      TEXT,                   -- when article saved to drafts/
    approved_at     TEXT,                   -- when human approves
    published_at    TEXT,                   -- when Webflow item created
    -- Tracking metadata (not lifecycle states)
    tracked_at      TEXT,                   -- when first GSC data was received
    last_tracked_at TEXT                    -- when GSC data was last received
)

-- GSC rank snapshots (append-only, retained indefinitely)
rank_history (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL,
    date        TEXT NOT NULL,
    position    REAL,
    impressions INTEGER,
    clicks      INTEGER,
    source      TEXT NOT NULL,  -- 'page' or 'query'
    query       TEXT            -- populated for source='query' rows
)

-- QA warnings per article
qa_warnings (
    id                INTEGER PRIMARY KEY,
    slug              TEXT NOT NULL,
    category          TEXT NOT NULL,   -- 'roi_claim'|'compliance_claim'|'regulatory'|'statistic'|'medical_assertion'
    excerpt           TEXT NOT NULL,   -- the flagged sentence or phrase
    created_at        TEXT NOT NULL,
    -- Reviewer decision fields
    resolution_status TEXT,            -- 'accepted'|'edited'|'dismissed'|NULL (unreviewed)
    reviewer_note     TEXT,            -- optional note explaining reviewer decision
    reviewed_at       TEXT             -- when reviewer acted on this warning
)

-- Per-run operational metrics
run_log (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    metrics     TEXT  -- JSON blob (see Run Metrics section)
)
```

Timestamps are stored as ISO 8601 strings (`2026-06-24T14:32:00Z`). All rows are retained indefinitely unless future retention rules are added.

---

## Components

### `keyword_research.py` (new)

Replaces `keyword_pull.py`. Four-phase approach with deliberate cost optimization in the SERP analysis step.

**Phase 1 — Claude ideation + relevance filter**

Claude is primed with SuperDial's positioning (voice AI for healthcare RCM) and generates 30 keyword ideas that healthcare revenue cycle professionals would search. For each keyword, Claude classifies business relevance as a binary filter:

- **High or Medium relevance** — pass through to DataForSEO validation
- **Low relevance** — discarded (e.g., general healthcare topics with no connection to RCM automation)

Relevance classification is a gate only. It does not influence ranking. Once a keyword passes the filter, its final position in the ranking is determined entirely by objective signals.

**Phase 2 — DataForSEO validation**

All remaining keywords sent to DataForSEO in a single task (~$0.05):
- `Keyword Data → Google Ads API`: volume, CPC, competition
- `Labs → Google API`: keyword difficulty, search intent

Malformed or incomplete DataForSEO responses are handled per-keyword: keywords missing required fields (`volume`, `difficulty`) are dropped with a warning logged to `run_log`. The run continues with remaining valid keywords.

**Phase 3 — Cost-optimized SERP analysis**

SERP API calls are intentionally limited to control cost. The process:

```
Claude ideation (30 candidates)
        ↓
DataForSEO keyword metrics (all remaining after relevance filter)
        ↓
Initial scoring (no SERP modifier)
        ↓
Top 10 candidates only
        ↓
DataForSEO SERP analysis (10 calls)
        ↓
Final scoring with serp_fit_modifier
        ↓
Top 3 selected
```

DataForSEO SERP API returns the top 10 organic results for each of the 10 candidates. Result types are classified by domain category:

| SERP composition | `serp_fit_modifier` |
|---|---|
| Majority blog articles / editorial content | 1.2 |
| Mixed content | 1.0 |
| Majority forums or Q&A | 0.9 |
| Majority software directories or review sites | 0.7 |

This classification is rule-based, not Claude-driven. The modifier reflects whether editorial content can realistically compete in the SERP.

**Phase 4 — Composite scoring and selection**

Relevance is not a scoring weight. Final ranking relies entirely on objective signals:

```
score = volume
      × (1 - difficulty / 100)         # lower difficulty = higher score
      × intent_modifier                 # commercial/transactional=1.3, informational=1.0, navigational=0
      × serp_fit_modifier               # 0.7–1.2, derived from SERP composition
      × (1 - cannibalization_penalty)   # 0.0–0.8 based on slug overlap with existing articles
      × log(1 + cpc)                    # CPC as commercial value proxy, log-scaled
```

- Keywords with `intent: navigational` score 0 and are excluded
- `cannibalization_penalty` computed by `state.py` — token overlap between candidate keyword and all existing `drafted`/`published` slugs
- A 200-volume keyword with high commercial intent, low difficulty, and a blog-friendly SERP can and should outrank a 1,200-volume broad explainer

Top 3 by final score are returned. If fewer than 3 unprocessed keywords remain, Claude generates 30 more (one retry before the step fails).

SEO metadata (`volume`, `difficulty`, `cpc`, `intent`) is persisted to the `keywords` table at selection time to enable future analysis: performance by difficulty band, commercial vs. informational outcomes, ranking results by search volume tier.

---

### `state.py` (new)

SQLite-backed. Single `pipeline.db` file in `data/`. Handles keyword lifecycle, timestamps, SEO metadata, QA warnings, and rank history.

**Key operations:**
```python
state.select_keyword(keyword, slug, score, volume, difficulty, cpc, intent)
                                             # state='selected', sets created_at, persists SEO metadata
state.mark_drafted(keyword)                  # state='drafted', sets drafted_at
state.mark_approved(keyword)                 # state='approved', sets approved_at
state.mark_published(keyword, webflow_item_id) # state='published', sets published_at
state.update_tracking_timestamps(slug)       # sets tracked_at (first run) and last_tracked_at (every run)
state.get_retryable(step)                    # keywords in prior state for a step
state.has_slug_collision(slug)               # → True/False before saving draft
state.get_all_published_slugs()              # for rank tracking
state.save_qa_warnings(slug, warnings)       # stores QA flags for review queue
state.get_qa_warnings(slug)                  # → list of warnings for dashboard
state.resolve_qa_warning(id, status, note)   # sets resolution_status, reviewer_note, reviewed_at
```

---

### `content_qa.py` (new)

Runs after article generation and before the approval step. Uses Claude to scan each draft for content risks specific to healthcare RCM. Produces warnings only — does not block publication.

**Flagged categories:**
- Unsupported ROI claims (e.g., "reduce costs by 40%" without cited source)
- Unsupported compliance claims (e.g., "fully HIPAA compliant" without qualification)
- Unsupported regulatory claims (e.g., assertions about CMS rules that may require verification)
- Hallucinated statistics (numeric claims without attributable sources)
- Medical or operational assertions presented as fact without evidence

Warnings are stored in the `qa_warnings` table and surfaced in the dashboard review queue alongside the draft. The reviewer sees each flagged excerpt and resolves it:

| `resolution_status` | Meaning |
|---|---|
| `accepted` | Reviewer reviewed and kept the content as-is |
| `edited` | Reviewer revised the flagged section |
| `dismissed` | Reviewer judged the flag as a false positive |
| `NULL` | Not yet reviewed |

The dashboard surfaces only unresolved warnings (`resolution_status IS NULL`) in the active review queue. Resolved warnings remain in the database for audit purposes. QA warnings do not change keyword state — a draft with warnings is still `drafted` and eligible for approval once the reviewer has addressed them.

---

### `rank_tracker.py` (new)

Connects to Google Search Console API via OAuth (site already verified — no new approval needed). Each weekly run records two types of metrics and updates tracking timestamps on each article.

**Page-level** (one row per slug per run):
```
slug, date, position, impressions, clicks, source='page'
```

**Query-level** (top 25 queries per article per run):
```
slug, date, query, position, impressions, clicks, source='query'
```

Filtering rules for query-level rows:
- Store only the top 25 queries per article per tracking run, ranked by impressions
- Ignore queries with fewer than 5 impressions
- Retain all stored rows indefinitely

After each successful tracking run for a slug, `state.update_tracking_timestamps(slug)` sets `tracked_at` on the first run and updates `last_tracked_at` on every run. These timestamps enable future reporting: time to first ranking data, article age vs. performance, and identifying articles that have gone untracked.

Query-level tracking surfaces unexpected ranking queries — articles ranking for terms not in the original `target_keyword`. This feeds back into ideation over time.

GSC failures are non-blocking but not silent. On failure, a `WARN` entry is written to `run_log` with the error message and timestamp. Tracking resumes automatically the following run.

---

### `dashboard.py` (new)

Streamlit app. Run with `streamlit run dashboard.py`. Reads from `pipeline.db` via `state.py`.

Shows:
- **Summary stats:** total articles published, drafts pending review, articles pending approval, current avg GSC position
- **Review queue:** articles in `drafted` state; per article shows QA warnings with resolution controls (accept / edited / dismiss + optional note); reviewer marks article `approved` once satisfied
- **This week's keyword picks:** target keyword, volume, difficulty, intent, score breakdown
- **Rank tracker table:** top 10 articles by clicks, with week-over-week position delta; `target_keyword` shown alongside slug for comparison with actual ranking queries
- **Query-level view:** unexpected ranking queries per article vs. target keyword
- **Line chart:** average GSC position over time across all published articles
- **Run history:** recent runs with structured metrics (see Run Metrics section)

---

### `generate_article.py` (minor update)

One change to the existing prompt: pass `intent` and `difficulty` from the scorer so Claude calibrates article depth.

- `intent: informational` + low difficulty → definitional explainer, 800 words
- `intent: commercial` + high difficulty → deep competitive take, 1,200 words

---

### `pipeline.py` (updated)

**Steps in order:**
1. Research — keyword ideation, relevance filter, validation, SERP analysis, scoring
2. Generate — article drafts saved to `drafts/`, QA warnings stored
3. ⏸ Review gate — pipeline pauses; reviewer resolves QA warnings and approves drafts in dashboard
4. Publish — runs only on `approved` keywords
5. Track — GSC data for all `published` slugs; updates tracking timestamps

**Manual review gate:** After generation, drafts appear in the dashboard review queue with QA warnings. Kelly reviews each article for accuracy, tone, and healthcare/operational precision, resolving each QA warning. `approved` state is set manually. Publishing only processes `approved` keywords. This gate exists because SEO content in healthcare RCM can accidentally sound overconfident, generic, or legally imprecise.

**Flags:**
- `--dry-run`: shows keyword selections, score breakdowns, and QA flag counts without writing or publishing
- `--step [keywords|generate|publish|track]`: run a single step, respecting state
- `--all`: research → generate → QA → (pause for review) → must manually trigger publish

---

## Data Flow

```
pipeline.py --all
    │
    ├─ 1. RESEARCH (idempotent)
    │       Claude → 30 keyword candidates with High/Medium/Low relevance classification
    │       Drop Low relevance keywords
    │       DataForSEO → validate remaining (1 task, ~$0.05); persist volume/difficulty/cpc/intent
    │       ⚠ malformed response per keyword → drop + warn, continue
    │       state.py → filter already-selected/drafted/approved/published keywords
    │       Initial score (no SERP modifier) → top 10 candidates
    │       DataForSEO SERP API → SERP composition for top 10 only (~$0.075)
    │       Final composite score → top 3 selected
    │       state.select_keyword(..., volume, difficulty, cpc, intent) → sets created_at
    │       ⚠ if < 3 remain → Claude generates 30 more (one retry)
    │
    ├─ 2. GENERATE (idempotent — skips keywords not in 'selected' state)
    │       For each keyword in 'selected':
    │         state.has_slug_collision(slug) → fail fast if collision
    │         Claude → article → drafts/<slug>.md
    │         content_qa.py → scan for healthcare content risks → warnings stored
    │         state.mark_drafted(), sets drafted_at
    │       ⚠ per-keyword failure: leave in 'selected', log, continue
    │
    │   ⏸ REVIEW GATE — pipeline pauses here
    │       Drafts + QA warnings visible in dashboard review queue
    │       Kelly resolves each QA warning (accept/edit/dismiss)
    │       Kelly marks each article approved
    │       state.mark_approved(), sets approved_at
    │       Publish triggered manually: python pipeline.py --step publish
    │
    ├─ 3. PUBLISH (idempotent — only processes 'approved' keywords)
    │       For each keyword in 'approved':
    │         Webflow API → create unpublished item → item ID
    │         state.mark_published(webflow_item_id), sets published_at
    │       ⚠ Webflow failure: leave in 'approved', log for manual retry
    │
    └─ 4. TRACK (non-blocking, idempotent, recurring)
            For all slugs in 'published' state:
              GSC API → page-level metrics (7 days)
              GSC API → query-level metrics (7 days, top 25, ≥5 impressions)
              state.append_rank_history()
              state.update_tracking_timestamps(slug)  → sets tracked_at / updates last_tracked_at
            ⚠ GSC failure → WARN in run_log with error + timestamp, skip, retry next run
```

---

## Run Metrics

Each run appends a structured metrics object to `run_log`:

```json
{
  "run_id": "2026-06-24T09:00:00Z",
  "started_at": "2026-06-24T09:00:00Z",
  "finished_at": "2026-06-24T09:04:12Z",
  "metrics": {
    "keywords_evaluated": 30,
    "keywords_filtered_relevance": 8,
    "keywords_filtered_state": 6,
    "keywords_selected": 3,
    "articles_generated": 3,
    "qa_warnings_total": 5,
    "articles_approved": 2,
    "articles_published": 2,
    "gsc_rows_ingested": 142,
    "gsc_warnings": 0
  }
}
```

These metrics feed the dashboard run history view and will support future reporting on publishing cadence, QA signal rates, and pipeline health.

---

## Error Handling

- Steps 1–2 are sequential — keyword research failure stops the run
- Step 3 (publish) only runs on `approved` keywords — the review gate prevents accidental publish
- Step 4 is non-blocking — GSC failure logs a `WARN` but does not affect draft delivery
- Nothing is deleted — every failure leaves the keyword in a retryable prior state
- `--dry-run` writes nothing to disk or database on any step
- Malformed DataForSEO responses are handled per-keyword, not per-run
- QA warnings are informational — they do not change state or block any step

---

## Testing

**Unit tests** — `tests/test_scorer.py`
1. Navigational intent scores 0 and is excluded
2. Low-relevance keywords are discarded before DataForSEO validation
3. High and medium relevance keywords receive identical treatment in scoring
4. Composite score correctly weights commercial intent over raw volume
5. Cannibalization penalty reduces score for near-duplicate slugs
6. CPC modifier log-scales correctly at 0, 1, 10
7. SERP fit modifier correctly applied from directory vs. blog composition

**State tests** — `tests/test_state.py`
1. Slug collision detected before draft is saved
2. Retry does not duplicate keywords already in target state
3. Publish failure leaves keyword in `approved` (retryable)
4. Publish step skips `drafted` keywords (requires `approved` state)
5. State transitions are sequential — cannot skip from `selected` to `published`
6. Rank tracker appends rows without overwriting history
7. Lifecycle timestamps set correctly at each transition
8. `tracked_at` set on first GSC run; `last_tracked_at` updated on subsequent runs
9. QA warning resolution updates `resolution_status`, `reviewer_note`, `reviewed_at`
10. SEO metadata (`volume`, `difficulty`, `cpc`, `intent`) persisted at selection time

**Pipeline tests** — `tests/test_pipeline.py`
1. Malformed DataForSEO response is handled, run continues
2. `--dry-run` writes nothing to db or disk
3. `--all` run is idempotent — re-running produces no duplicates
4. Publish step only processes `approved` keywords, skips all others
5. QA warnings stored for draft; draft state unchanged
6. GSC failure logs WARN and does not abort run
7. Dashboard review queue shows only unresolved QA warnings

**Integration tests** (manual, run once before first real run)
```bash
python pipeline.py --step keywords --dry-run    # confirm DataForSEO auth
python pipeline.py --step generate --top 1      # generate 1 article + QA scan, inspect output
python publish_webflow.py --list-fields          # confirm Webflow field slugs
python rank_tracker.py --dry-run                # confirm GSC OAuth
```

No mocking — API calls are cheap enough for real calls in dev. A full dry-run costs ~$0.05.

---

## API Costs

| API | Usage | Cost/run | Monthly (4 runs) |
|---|---|---|---|
| DataForSEO Google Ads | 1 task / 30 keywords | $0.05 | $0.20 |
| DataForSEO Labs Google | 1 task / 30 keywords | ~$0.013 | ~$0.05 |
| DataForSEO Labs Search Intent | 1 task / 30 keywords | ~$0.004 | ~$0.02 |
| DataForSEO SERP API | 10 keywords × live mode | ~$0.075 | ~$0.30 |
| Claude (3 articles + QA scans) | Sonnet 4.6 | ~$0.10 | ~$0.40 |
| **Total** | | **~$0.24** | **~$0.97** |

GSC and Webflow API are free. Total remains under $1/month.

---

## V2 (n8n — after core pipeline is proven)

- Weekly scheduled trigger replaces manual `python pipeline.py --all`
- Slack digest sent after generation step: drafts ready for review with links and QA warning counts
- Approve/reject buttons in Slack call `state.mark_approved()` — the `approved` state maps directly to this workflow
- Summary digest after publish: articles live, top rank mover, current avg position
- Manual trigger button in Slack for on-demand runs
- No pipeline logic changes — n8n wraps the existing CLI

---

## Module Summary

| Module | Status | Purpose |
|---|---|---|
| `keyword_research.py` | New | Claude relevance filter + DataForSEO validation + cost-optimized SERP scoring |
| `content_qa.py` | New | Healthcare content risk flagging with reviewer resolution (warnings only) |
| `state.py` | New | Keyword lifecycle, SEO metadata, timestamps, QA tracking, SQLite |
| `rank_tracker.py` | New | GSC page-level + query-level tracking, tracking timestamp updates |
| `dashboard.py` | New | Streamlit executive view + review queue + QA warning resolution |
| `generate_article.py` | Minor update | Pass intent/difficulty to prompt |
| `publish_webflow.py` | Unchanged | Publish drafts to Webflow CMS |
| `pipeline.py` | Updated | Orchestrate steps, review gate, idempotent, structured run metrics |
