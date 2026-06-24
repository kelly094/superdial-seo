# SEO Pipeline V2 Design
**Date:** 2026-06-24
**Status:** Approved

## Overview

A weekly content production pipeline that replaces SemRush for SuperDial's SEO strategy. Claude generates keyword ideas, DataForSEO validates them, Claude writes articles, and the pipeline publishes drafts to Webflow CMS. Google Search Console tracks rank performance over time. A Streamlit dashboard provides an on-demand executive view.

**Goal:** Publish 3 SEO articles per week, track their rankings, and surface performance trends — for under $1/month in API costs.

---

## Architecture

Builds on the existing `superdial-seo/` codebase. `keyword_pull.py` is replaced by `keyword_research.py`. Three new modules are added. Existing `generate_article.py` and `publish_webflow.py` are largely unchanged.

```
pipeline.py  (weekly orchestrator — updated)
    │
    ├── keyword_research.py  (NEW — replaces keyword_pull.py)
    │       ├── claude_ideation()      → 30 keyword candidates via Claude
    │       ├── dataforseo_validate()  → volume, difficulty, search intent per keyword
    │       └── score_and_rank()       → top 3 by volume/difficulty ratio
    │
    ├── generate_article.py  (existing — minor prompt update)
    │
    ├── publish_webflow.py   (existing — unchanged)
    │
    ├── rank_tracker.py      (NEW — Google Search Console API)
    │       └── weekly snapshot of position/impressions/clicks per published article
    │
    ├── state.py             (NEW — deduplication + run history)
    │       └── tracks processed keywords + published Webflow item IDs
    │
    └── dashboard.py         (NEW — Streamlit executive view)
```

**File structure additions:**
```
data/
├── processed_keywords.json   ← prevents duplicate article generation
└── rank_history.json         ← weekly GSC snapshots per article
docs/superpowers/specs/       ← design docs
tests/
└── test_scorer.py
```

---

## Components

### `keyword_research.py` (new)

Replaces `keyword_pull.py`. Two-phase approach:

**Phase 1 — Claude ideation**
Claude is primed with SuperDial's positioning (voice AI for healthcare RCM) and asked to generate 30 keyword ideas that healthcare revenue cycle professionals would search. No API dependency — pure Claude generation.

**Phase 2 — DataForSEO validation**
All 30 keywords sent to DataForSEO in a single task (~$0.05):
- `Keyword Data → Google Ads API`: volume, CPC, competition
- `Labs → Google API`: keyword difficulty, search intent

**Phase 3 — Scoring and selection**
```
score = volume × (1 - difficulty / 100)
```
Keywords with `intent: navigational` are filtered out. Keywords already in `state.py` are skipped. Top 3 by score are returned.

If fewer than 3 unprocessed keywords remain after filtering, Claude generates 30 more (one retry before failing).

---

### `state.py` (new)

Thin wrapper around two JSON files in `data/`. Prevents duplicate articles across runs and records Webflow item IDs for rank tracking.

```python
state.is_processed("prior authorization automation software")  # → True/False
state.mark_processed("prior authorization automation software")
state.save_published("prior-auth-automation", webflow_item_id="abc123")
state.get_all_slugs()  # → list of slugs for rank tracking
```

---

### `rank_tracker.py` (new)

Connects to Google Search Console API via OAuth (site already verified — no new approval needed). Each weekly run appends a snapshot to `rank_history.json`:

```json
{
  "date": "2026-06-24",
  "slug": "prior-auth-automation",
  "position": 14.2,
  "impressions": 43,
  "clicks": 2
}
```

Runs after publish step. Failure is non-blocking — if GSC is unavailable, the run still succeeds and tracking picks up the following week.

---

### `dashboard.py` (new)

Streamlit app. Run with `streamlit run dashboard.py`. Reads from `state.py` and `rank_history.json` — no extra data storage.

Shows:
- Summary stats: total articles published, drafts pending review, current avg position
- This week's keyword picks (keyword, volume, difficulty)
- Rank tracker table: top 10 articles by clicks, with week-over-week position delta
- Line chart: average position over time across all tracked articles

---

### `generate_article.py` (minor update)

One change to the existing prompt: pass `intent` and `difficulty` from DataForSEO so Claude calibrates article depth.

- `intent: informational` + low difficulty → definitional explainer, 800 words
- `intent: commercial` + high difficulty → deep competitive take, 1,200 words

---

### `pipeline.py` (updated)

Adds:
- `--dry-run` flag: shows keyword selections and article plan without writing or publishing
- Structured per-run summary log (stdout + appended to `data/run_log.jsonl`)
- Step 4 (rank tracking) runs after publish, non-blocking

```
[2026-06-24] Run complete: 3 articles generated, 3 published to Webflow (drafts)
  → "prior authorization automation software" (vol: 1,200 | diff: 34)
  → "benefits verification AI" (vol: 880 | diff: 28)
  → "claim status automation" (vol: 720 | diff: 41)
Rank check: 12 published articles tracked via GSC
```

---

## Data Flow

```
pipeline.py --all
    │
    ├─ 1. RESEARCH
    │       Claude → 30 keyword candidates
    │       DataForSEO → validate all 30 (1 task, ~$0.05)
    │       state.py → filter already-processed keywords
    │       scorer → pick top 3
    │       ⚠ if < 3 remain → Claude generates 30 more (one retry)
    │
    ├─ 2. GENERATE
    │       For each of 3 keywords:
    │         Claude → article → drafts/<slug>.md
    │         state.py → mark keyword processed
    │       ⚠ per-keyword failure: skip + log, continue with remaining
    │
    ├─ 3. PUBLISH
    │       For each draft:
    │         Webflow API → create unpublished item → item ID
    │         state.py → save slug + item ID
    │       ⚠ Webflow failure: keep draft on disk, log for manual retry
    │
    └─ 4. TRACK (non-blocking)
            GSC API → last 7 days per tracked slug
            → append to rank_history.json
            ⚠ GSC failure → skip silently, picks up next run
```

---

## Error Handling

- Steps 1–3 are sequential and fail hard — no point generating articles if keyword research failed
- Step 4 is fire-and-forget — a GSC outage does not block draft delivery
- Article generation failures are per-keyword — one bad Claude response does not kill the other two
- Nothing is deleted — failed publishes remain in `drafts/` and can be retried with `python pipeline.py --step publish`
- `--dry-run` on any step shows what would happen without writing anything

---

## Testing

**Unit tests** — `tests/test_scorer.py`

Three cases:
1. Navigational intent keywords are filtered out (e.g. "webflow login")
2. Already-processed keywords are excluded from selection
3. Score formula correctly favors low difficulty over raw volume

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
- Slack digest sent after each run: 3 new drafts ready, top rank mover, current avg position
- Manual trigger button in Slack for on-demand runs
- No pipeline logic changes — n8n wraps the existing CLI

---

## Module Summary

| Module | Status | Purpose |
|---|---|---|
| `keyword_research.py` | New | Claude ideation + DataForSEO validation |
| `state.py` | New | Deduplication + run history |
| `rank_tracker.py` | New | GSC weekly position tracking |
| `dashboard.py` | New | Streamlit executive view |
| `generate_article.py` | Minor update | Pass intent/difficulty to prompt |
| `publish_webflow.py` | Unchanged | Publish drafts to Webflow CMS |
| `pipeline.py` | Updated | Orchestrate all steps + structured logging |
