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
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import state
import keyword_research
import generate_article
import content_qa

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

    # Seed used_formats from existing drafts so new articles complement what's already there
    used_formats = [
        generate_article.detect_content_format(p.stem.replace("-", " "))
        for p in Path("drafts").glob("*.md")
    ]

    for i, kw in enumerate(candidates, 1):
        keyword = kw["keyword"]
        slug = kw["slug"]
        print(f"  [{i}/{len(candidates)}] '{keyword}'...", end=" ", flush=True)

        if Path(f"drafts/{slug}.md").exists():
            print(f"SKIP (draft already exists)")
            continue

        try:
            raw, fmt = generate_article.generate_draft(client, kw, avoid_formats=used_formats)
            used_formats.append(fmt)
            path, title = generate_article.parse_and_save(raw, kw, slug=slug)

            # QA scan — body compliance + SEO field checks
            draft_text = path.read_text()
            warnings = (
                content_qa.scan_draft(draft_text)
                + content_qa.scan_seo_fields(draft_text, keyword=keyword)
            )
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
    import publish_webflow
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
        print(f"  WARN: GSC tracking failed: {e}")
        metrics["gsc_warnings"] += 1
        metrics["gsc_error"] = str(e)

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
