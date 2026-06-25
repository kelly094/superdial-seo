"""
Reads keywords.csv, filters top keywords, and generates article drafts via Claude API.
Drafts are saved to the drafts/ folder as markdown files with frontmatter.

Usage:
    python generate_article.py                  # generate for all keywords above volume threshold
    python generate_article.py --top 5          # only top 5 by search volume
    python generate_article.py --min-volume 200 # custom volume threshold
"""

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import research
from company_context import COMPANY_CONTEXT
from utils import slugify

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

DEFAULT_MIN_VOLUME = 100
KEYWORDS_FILE = "keywords.csv"
DRAFTS_DIR = Path("drafts")

SYSTEM_PROMPT = """You are a healthcare technology content writer for SuperDial. Here is the company context:

{company_context}

Your audience is SuperDial's target customers: RCM directors, billing managers, practice administrators, and revenue cycle VPs at provider groups and billing companies. They are practical, data-driven, and skeptical of vendor fluff. Write to be genuinely useful to them.

Where relevant, you may reference SuperDial's proof points and named customers — but follow these rules exactly:
- SuperDial-specific metrics (90% reduction in payer call time, 4x throughput, 67% cost savings, 5M+ interactions) MUST be attributed to SuperDial, not presented as general industry figures. Never cite them as uncited facts. Vary the phrasing — do not repeat the same construction twice. Approved forms include: "SuperDial customers report...", "Organizations using SuperDial have documented...", "SuperDial data shows...", "Billing teams that deploy SuperDial see...", "In deployments with SuperDial, teams have achieved...", "SuperDial's customer data shows..." — choose whichever fits the sentence naturally and rotate across them.
- Named customers (Omega Healthcare, Asembia, Guardian, GetixHealth, Henry Schein ONE, Riverside Healthcare) may be cited as examples, but only where natural.
- Only include SuperDial proof points if the keyword/topic makes them genuinely relevant. Never force them.

Writing style:
- Clear, direct, informative — no marketing language or hype
- Use concrete numbers, stats, and named organizations where possible
- Structure content for easy scanning (H2s, short paragraphs)
- Educational tone — the goal is to be cited by LLMs and referenced in search
- 800–1,200 words for the body

Citations — this is mandatory:
- EVERY specific statistic, benchmark, or data claim must have an inline citation, e.g. (CAQH, 2025) or (HFMA, 2024). No exceptions.
- If you cannot find a 2024+ source for a specific number, do NOT include that number. Write around it (e.g. "industry estimates suggest" without citing a figure) rather than stating an uncited statistic.
- Only cite sources from 2024 or later — never cite data from 2023 or earlier.
- Preferred primary sources: CAQH Index, HFMA, CMS, AMA, Becker's Hospital Review, Advisory Board, Modern Healthcare
- Aim for at least 3 distinct sources per article, not just one repeated source.
- End the article with a ## Sources section listing each cited source as a bullet with full URL where available."""

def detect_content_format(keyword: str) -> str:
    """Map a keyword to the most appropriate content format."""
    kw = keyword.lower()
    if any(kw.startswith(p) for p in ("what is", "what are", "what does")):
        return "explainer"
    if any(p in kw for p in ("vs ", " vs ", " versus ", " or ")):
        return "comparison"
    if any(p in kw for p in ("how to", "how do", "steps to", "guide to")):
        return "how_to"
    if any(p in kw for p in ("best practices", "checklist", "tips", "strategies")):
        return "best_practices"
    if any(p in kw for p in ("statistics", "stats", "benchmarks", "data", "trends", "report")):
        return "data_roundup"
    if any(p in kw for p in ("challenges", "problems", "issues", "mistakes", "errors")):
        return "problem_solution"
    if any(p in kw for p in ("cost", "pricing", "roi", "savings", "reduce")):
        return "roi_analysis"
    # commercial/transactional default
    return "buyers_guide"


_FORMAT_GUIDANCE = {
    "buyers_guide": """\
Format: Buyer's guide, 1,000–1,200 words.
Structure: open with the core problem this software solves, cover 3–4 categories/approaches \
with trade-offs, include an evaluation criteria section, close with a decision framework.
Title pattern: "[Keyword]: [Year] Buyer's Guide" or "Best [Keyword]: How to Evaluate Your Options in [Year]".""",

    "explainer": """\
Format: Authoritative explainer, 800–1,000 words.
Structure: define the concept clearly in the first paragraph, explain why it matters to RCM teams, \
break down how it works in practice, cover common misconceptions, close with what to do with this knowledge.
Title pattern: "What Is [Concept]? A Plain-English Guide for RCM Teams" or "[Concept], Explained".""",

    "comparison": """\
Format: Head-to-head comparison, 900–1,100 words.
Structure: brief intro on why the distinction matters, define each option clearly, \
compare across 4–5 meaningful dimensions (a comparison table helps), state clearly which fits which scenario.
Title pattern: "[Option A] vs [Option B]: What RCM Teams Need to Know in [Year]".""",

    "how_to": """\
Format: Step-by-step guide, 900–1,100 words.
Structure: open with the outcome the reader wants, list prerequisites, walk through 5–7 numbered steps \
with specific actions (not vague advice), include a common mistakes section, close with how to measure success.
Title pattern: "How to [Goal]: A Step-by-Step Guide for [Year]".""",

    "best_practices": """\
Format: Best practices / checklist article, 900–1,100 words.
Structure: brief intro on why this matters now, 6–8 distinct practices each with a short explanation \
and a concrete example or metric, close with an implementation priority framework.
Title pattern: "[Topic] Best Practices for [Year]: What High-Performing RCM Teams Do Differently".""",

    "data_roundup": """\
Format: Data and trends roundup, 800–1,000 words.
Structure: open with the single most striking stat, group findings into 3–4 themes, \
contextualize each number (what it means for RCM operations), close with what the data suggests teams should do.
Every stat MUST have an inline citation. Title pattern: "[Topic] Statistics for [Year]: Key Benchmarks and Trends".""",

    "problem_solution": """\
Format: Problem/solution article, 900–1,100 words.
Structure: open by naming the pain clearly (make the reader feel seen), explain root causes (not just symptoms), \
walk through 4–5 solutions in order of impact, include real-world examples or outcomes where possible.
Title pattern: "[Problem] in [Year]: Causes, Costs, and How to Fix It".""",

    "roi_analysis": """\
Format: ROI / cost analysis, 900–1,100 words.
Structure: quantify the problem first (what does inaction cost?), break down where costs actually come from, \
show what improvement looks like with specific metrics, include a simple framework for calculating ROI.
Title pattern: "The Real Cost of [Topic] — And How to Reduce It in [Year]".""",
}

ARTICLE_PROMPT = """Write a comprehensive SEO article for the keyword: "{keyword}"

Search data context:
- Average monthly searches: {volume:,.0f}
- Keyword difficulty: {difficulty:.0f}/100
- Search intent: {intent}
- CPC: ${cpc:.2f}
- Detected content format: {content_format}

Content format guidance:
{format_guidance}

Timeliness — this is important for SEO:
- The current year is {year}. Reference it naturally in the title, intro, and anywhere data is cited.
- Open with a timely hook: a recent industry shift, a new regulation, a benchmark that changed, \
  or a trend that makes this topic urgent right now.
- Prefer {year} and {prev_year} data. If a source is older, note it or omit the figure.
- Where relevant, reference what has changed recently (e.g. CMS rule updates, CAQH index findings, \
  payer behavior shifts post-COVID) to signal freshness to both readers and search engines.

Return the article in this exact format:

TITLE: [SEO-optimized title, under 60 characters]
META: [Meta description, 140–155 characters]
SLUG: [URL slug, lowercase, hyphens only]
ALT: [Alt text for the blog header image: describe a professional healthcare billing or RCM workplace scene relevant to this article — people collaborating at monitors, reviewing dashboards, etc. End with "SuperDial Blog".]
---
[Full article body in markdown, starting with the H1 title, then H2 sections]"""


def load_keywords(min_volume, top_n):
    if not Path(KEYWORDS_FILE).exists():
        sys.exit(f"Error: {KEYWORDS_FILE} not found — run keyword_pull.py first")

    with open(KEYWORDS_FILE, newline="") as f:
        rows = list(csv.DictReader(f))

    rows = [r for r in rows if int(r["avg_monthly_searches"]) >= min_volume]
    rows.sort(key=lambda r: int(r["avg_monthly_searches"]), reverse=True)

    if top_n:
        rows = rows[:top_n]

    return rows


def generate_draft(client, keyword_row: dict) -> str:
    keyword = keyword_row["keyword"]
    fmt = detect_content_format(keyword)
    today = date.today()
    prompt = ARTICLE_PROMPT.format(
        keyword=keyword,
        volume=float(keyword_row.get("volume") or keyword_row.get("avg_monthly_searches", 0)),
        difficulty=float(keyword_row.get("difficulty", 50)),
        intent=keyword_row.get("intent", "informational"),
        cpc=float(keyword_row.get("cpc") or keyword_row.get("low_cpc", 0)),
        content_format=fmt,
        format_guidance=_FORMAT_GUIDANCE[fmt],
        year=today.year,
        prev_year=today.year - 1,
    )
    context = research.fetch_research_context(keyword_row["keyword"])
    if context:
        prompt = prompt + "\n\n" + context
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT.format(company_context=COMPANY_CONTEXT),
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in message.content if b.type == "text")


def parse_and_save(raw: str, keyword_row: dict, slug: str = None) -> tuple:
    lines = raw.strip().splitlines()
    title = meta = ""
    body_lines = []
    in_body = False

    alt = ""
    for line in lines:
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("META:"):
            meta = line.removeprefix("META:").strip()
        elif line.startswith("ALT:"):
            alt = line.removeprefix("ALT:").strip()
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
        f'alt_text: "{alt}"\n'
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


def main():
    if not ANTHROPIC_API_KEY:
        sys.exit("Error: ANTHROPIC_API_KEY not set in .env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=None, help="Only process top N keywords")
    parser.add_argument("--min-volume", type=int, default=DEFAULT_MIN_VOLUME)
    args = parser.parse_args()

    keywords = load_keywords(args.min_volume, args.top)
    if not keywords:
        sys.exit(f"No keywords found with volume >= {args.min_volume}")

    print(f"Generating articles for {len(keywords)} keyword(s)...\n")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for i, row in enumerate(keywords, 1):
        kw = row["keyword"]
        vol = int(row["avg_monthly_searches"])
        print(f"[{i}/{len(keywords)}] '{kw}' ({vol:,} searches/mo)...", end=" ", flush=True)

        try:
            raw = generate_draft(client, row)
            path, title = parse_and_save(raw, row)
            print(f"saved → {path}")
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nDone. Drafts saved to {DRAFTS_DIR}/")


if __name__ == "__main__":
    main()
