# SEO Pipeline V2 Design
**Date:** 2026-06-24
**Status:** Approved (rev 2 — incorporates review feedback)

## Overview

A weekly content production pipeline that replaces SemRush for SuperDial's SEO strategy. Claude generates keyword ideas, DataForSEO validates them, Claude writes articles, a human reviews drafts, and the pipeline publishes approved content to Webflow CMS. Google Search Console tracks rank performance at both page and query level over time. A Streamlit dashboard provides an on-demand executive view.

**Goal:** Publish 3 SEO articles per week, track their rankings, and surface performance trends — for under $1/month in API costs.

---

## Architecture

Builds on the existing `superdial-seo/` codebase. `keyword_pull.py` is replaced by `keyword_research.py`. Four new modules are added. Existing `generate_article.py` and `publish_webflow.py` are largely unchanged.

```
pipeline.py  (weekly orchestrator — updated)
    │
    ├── keyword_research.py  (NEW — replaces keyword_pull.py)
    │       ├── claude_ideation()      → 30 keyword candidates via Claude
    │       ├── dataforseo_validate()  → volume, difficulty, intent, CPC per keyword
    │       └── score_and_rank()       → top 3 by composite score
    │
    ├── generate_article.py  (existing — minor prompt update)
    │
    ├── publish_webflow.py   (existing — unchanged)
    │
    ├── rank_tracker.py      (NEW — Google Search Console API)
    │       ├── page-level metrics per slug (position, impressions, clicks)
    │       └── query-level metrics per article (unexpected ranking queries)
    │
    ├── state.py             (NEW — keyword lifecycle + run history)
    │       └── SQLite — keyword states, published items, rank history
    │
    └── dashboard.py         (NEW — Streamlit executive view)
```

**File structure additions:**
```
data/
└── pipeline.db           ← SQLite (replaces JSON files)
docs/superpowers/specs/   ← design docs
tests/
├── test_scorer.py
├── test_state.py
└── test_pipeline.py
```

---

## State Lifecycle

Every keyword moves through four explicit states. State transitions only happen on confirmed success — a failure at any step leaves the keyword in its prior state so it remains retryable.

```
selected → drafted → published → tracked
```

| State | Set when | Retryable if stuck |
|---|---|---|
| `selected` | Keyword chosen by scorer | Always — re-runs research |
| `drafted` | Article saved to `drafts/` | `--step generate` reruns generation only |
| `published` | Webflow item created (item ID saved) | `--step publish` retries all `drafted` |
| `tracked` | First GSC data received for slug | Auto on next run |

A keyword is never suppressed by a downstream failure. A generation failure leaves it `selected`. A publish failure leaves it `drafted`. Both remain eligible for retry.

**Idempotency:** Every step checks state before acting. Re-running any step is safe — it skips work already done and only processes items in the correct prior state. Running `--all` twice produces no duplicates.

---

## Components

### `keyword_research.py` (new)

Replaces `keyword_pull.py`. Three-phase approach:

**Phase 1 — Claude ideation**
Claude is primed with SuperDial's positioning (voice AI for healthcare RCM) and asked to generate 30 keyword ideas that healthcare revenue cycle professionals would search. No API dependency — pure Claude generation.

**Phase 2 — DataForSEO validation**
All 30 keywords sent to DataForSEO in a single task (~$0.05):
- `Keyword Data → Google Ads API`: volume, CPC, competition
- `Labs → Google API`: keyword difficulty, search intent

Malformed or incomplete DataForSEO responses are handled per-keyword: any keyword missing required fields (`volume`, `difficulty`) is dropped with a warning logged to `run_log.jsonl`. The run continues with remaining valid keywords.

**Phase 3 — Composite scoring**

```
score = volume
      × (1 - difficulty / 100)       # lower difficulty = higher score
      × relevance_modifier            # 0.5–1.5, set by Claude per keyword
      × intent_modifier               # commercial/transactional=1.3, informational=1.0, navigational=0
      × serp_fit_modifier             # 1.2 if SERP shows articles (not tools/directories)
      × (1 - cannibalization_penalty) # 0–0.8 if similar slug already exists in state
      × log(1 + cpc)                  # CPC as commercial value proxy, log-scaled
```

- `relevance_modifier` and `serp_fit_modifier` are set by Claude during ideation — Claude evaluates each keyword against SuperDial's product positioning
- `cannibalization_penalty` is computed by `state.py` — compares candidate keyword against all `drafted`/`published` slugs using token overlap
- Keywords with `intent: navigational` score 0 and are excluded
- A 200-volume keyword with high commercial intent and low difficulty can and should outrank a 1,200-volume broad explainer

If fewer than 3 unprocessed keywords remain after filtering, Claude generates 30 more (one retry before the step fails).

---

### `state.py` (new)

SQLite-backed. Single `pipeline.db` file in `data/`. Handles keyword lifecycle, slug tracking, and rank history. SQLite is chosen over JSON because it makes deduplication queries, retry logic, dashboard reads, and history queries clean without adding ops burden. It will remain performant for years of weekly runs.

**Tables:**
```sql
keywords    (keyword, state, slug, webflow_item_id, score, created_at, updated_at)
rank_history (slug, date, position, impressions, clicks, source)
             -- source: 'page' or 'query', query rows also store the query string
run_log      (run_id, started_at, finished_at, summary_json)
```

**Key operations:**
```python
state.select_keyword(keyword, slug, score)         # state = 'selected'
state.mark_drafted(keyword)                        # state = 'drafted'
state.mark_published(keyword, webflow_item_id)     # state = 'published'
state.mark_tracked(keyword)                        # state = 'tracked'
state.get_retryable(step)                          # keywords in prior state for a step
state.has_slug_collision(slug)                     # → True/False before saving draft
state.get_all_published_slugs()                    # for rank tracking
```

---

### `rank_tracker.py` (new)

Connects to Google Search Console API via OAuth (site already verified — no new approval needed). Each weekly run records two types of metrics:

**Page-level** (one row per slug per week):
```
slug, date, position, impressions, clicks
```

**Query-level** (one row per query per article per week):
```
slug, date, query, position, impressions, clicks
```
This surfaces unexpected ranking queries — articles ranking for terms not in the original keyword target. Over time this feeds back into ideation: if an article on "prior auth automation" is ranking for "insurance approval delays", that's a content gap signal.

GSC failures are non-blocking but not silent. On failure, a `WARN` entry is appended to `run_log.jsonl` with the error and timestamp. Tracking picks up automatically the following run.

---

### `dashboard.py` (new)

Streamlit app. Run with `streamlit run dashboard.py`. Reads from `pipeline.db` via `state.py`.

Shows:
- Summary stats: total articles published, drafts pending review, current avg position
- **Review queue:** articles in `drafted` state waiting for human approval before publish
- This week's keyword picks (keyword, volume, score breakdown)
- Rank tracker table: top 10 articles by clicks, with week-over-week position delta
- Query-level view: unexpected queries per article
- Line chart: average position over time across all tracked articles

---

### `generate_article.py` (minor update)

One change to the existing prompt: pass `intent`, `difficulty`, and `relevance_modifier` from the scorer so Claude calibrates article depth and positioning.

- `intent: informational` + low difficulty → definitional explainer, 800 words
- `intent: commercial` + high difficulty → deep competitive take, 1,200 words

---

### `pipeline.py` (updated)

**Manual review gate between generate and publish:**

After generation, the pipeline pauses. Drafts in `drafted` state appear in the dashboard review queue. Kelly reviews each article for accuracy, tone, and healthcare/operational precision before approving. Publishing only proceeds for approved drafts — either via `python pipeline.py --step publish` after review, or (in V2) via a Slack approve button.

This gate exists because SEO content in healthcare RCM can accidentally sound overconfident, generic, or legally/operationally imprecise. Claude drafts are starting points, not finished copy.

**Flags:**
- `--dry-run`: shows keyword selections and score breakdowns without writing or publishing
- `--step [keywords|generate|publish|track]`: run a single step, respecting state
- `--all`: research → generate → (pause for review) → must manually trigger publish

**Structured logging** — each run appends to `run_log` table in SQLite and prints to stdout:
```
[2026-06-24] Run complete: 3 articles drafted, awaiting review
  → "prior authorization automation software" (vol: 1,200 | diff: 34 | score: 847)
  → "benefits verification AI" (vol: 880 | diff: 28 | score: 792)
  → "claim status automation" (vol: 720 | diff: 41 | score: 521)
GSC WARN: rate limit hit, rank tracking skipped — will retry next run
```

---

## Data Flow

```
pipeline.py --all
    │
    ├─ 1. RESEARCH (idempotent)
    │       Claude → 30 keyword candidates with relevance + SERP fit scores
    │       DataForSEO → validate all 30 (1 task, ~$0.05)
    │       ⚠ malformed response per keyword → drop + warn, continue
    │       state.py → filter already-selected/drafted/published keywords
    │       scorer → composite score, filter navigational, pick top 3
    │       state.mark_selected() for each
    │       ⚠ if < 3 remain → Claude generates 30 more (one retry)
    │
    ├─ 2. GENERATE (idempotent — skips keywords already in drafted+ state)
    │       For each keyword in 'selected' state:
    │         state.has_slug_collision(slug) → fail fast if collision
    │         Claude → article → drafts/<slug>.md
    │         state.mark_drafted()
    │       ⚠ per-keyword failure: leave in 'selected', log, continue
    │
    │   ⏸ REVIEW GATE — pipeline pauses here
    │       Drafts visible in dashboard review queue
    │       Kelly reviews + approves each article
    │       Publish triggered manually: python pipeline.py --step publish
    │
    ├─ 3. PUBLISH (idempotent — only processes 'drafted' keywords)
    │       For each keyword in 'drafted' state:
    │         Webflow API → create unpublished item → item ID
    │         state.mark_published(webflow_item_id)
    │       ⚠ Webflow failure: leave in 'drafted', log for manual retry
    │
    └─ 4. TRACK (non-blocking, idempotent)
            For all slugs in 'published' state:
              GSC API → page-level metrics (7 days)
              GSC API → query-level metrics (7 days)
              state.append_rank_history()
              state.mark_tracked()
            ⚠ GSC failure → WARN in run_log, skip, retry next run
```

---

## Error Handling

- Steps 1–2 are sequential — keyword research failure stops the run
- Step 3 (publish) only runs on manually approved drafts — review gate prevents accidental publish
- Step 4 is non-blocking — GSC failure logs a warning but does not affect draft delivery
- Nothing is deleted — every failure leaves the keyword in a retryable state
- `--dry-run` writes nothing to disk or database on any step
- Malformed DataForSEO responses are handled per-keyword, not per-run

---

## Testing

**Unit tests** — `tests/test_scorer.py`
1. Navigational intent scores 0 and is excluded
2. Already-drafted/published keywords are excluded from selection
3. Composite score correctly weights commercial intent over raw volume
4. Cannibalization penalty reduces score for near-duplicate slugs
5. CPC modifier log-scales correctly at 0, 1, 10

**State tests** — `tests/test_state.py`
1. Slug collision detected before draft is saved
2. Retry does not duplicate keywords already in target state
3. Publish failure leaves keyword in `drafted` (retryable)
4. State transitions are sequential — cannot skip from `selected` to `published`
5. Rank tracker appends rows without overwriting history

**Pipeline tests** — `tests/test_pipeline.py`
1. Malformed DataForSEO response is handled, run continues
2. `--dry-run` writes nothing to db or disk
3. `--all` run is idempotent — re-running produces no duplicates
4. Publish step only processes `drafted` keywords, skips all others

**Integration tests** (manual, run once before first real run)
```bash
python pipeline.py --step keywords --dry-run    # confirm DataForSEO auth
python pipeline.py --step generate --top 1      # generate 1 article, inspect output
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
| Claude (3 articles ~1,000 words) | Sonnet 4.6 | ~$0.08 | ~$0.32 |
| **Total** | | **~$0.15** | **~$0.59** |

GSC and Webflow API are free.

---

## V2 (n8n — after core pipeline is proven)

- Weekly scheduled trigger replaces manual `python pipeline.py --all`
- Slack digest sent after generation step: 3 drafts ready for review with links
- Approve/reject buttons in Slack trigger `--step publish` per article
- Summary digest after publish: articles live, top rank mover, current avg position
- Manual trigger button in Slack for on-demand runs
- No pipeline logic changes — n8n wraps the existing CLI

---

## Module Summary

| Module | Status | Purpose |
|---|---|---|
| `keyword_research.py` | New | Claude ideation + DataForSEO validation + composite scoring |
| `state.py` | New | Keyword lifecycle (selected→drafted→published→tracked), SQLite |
| `rank_tracker.py` | New | GSC page-level + query-level tracking |
| `dashboard.py` | New | Streamlit executive view + review queue |
| `generate_article.py` | Minor update | Pass intent/difficulty/relevance to prompt |
| `publish_webflow.py` | Unchanged | Publish drafts to Webflow CMS |
| `pipeline.py` | Updated | Orchestrate steps, review gate, idempotent, structured logging |
