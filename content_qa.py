import json
import os
import re

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
{{"warnings": [{{"category": "roi_claim", "excerpt": "the exact flagged sentence or phrase"}}, ...]}}

If no issues are found, return: {{"warnings": []}}

Article to review:
---
{article}
---"""


def _parse_frontmatter(text: str) -> dict:
    """Return frontmatter key/value pairs from a draft file."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


def scan_seo_fields(draft_text: str, keyword: str = None) -> list:
    """Rule-based SEO checks on title and meta description. No API call."""
    fm = _parse_frontmatter(draft_text)
    title = fm.get("title", "")
    meta  = fm.get("meta_description", "")
    kw    = keyword or fm.get("keyword", "")
    warnings = []

    if title:
        if len(title) > 65:
            warnings.append({
                "category": "title_seo",
                "excerpt": f"Title too long ({len(title)} chars, max 65): {title}",
            })
        elif len(title) < 30:
            warnings.append({
                "category": "title_seo",
                "excerpt": f"Title too short ({len(title)} chars, min 30): {title}",
            })
        if kw and kw.lower() not in title.lower():
            warnings.append({
                "category": "title_seo",
                "excerpt": f"Target keyword not in title — keyword: \"{kw}\" | title: \"{title}\"",
            })

    if meta:
        if len(meta) > 160:
            warnings.append({
                "category": "meta_seo",
                "excerpt": f"Meta description too long ({len(meta)} chars, max 160): {meta[:120]}…",
            })
        elif len(meta) < 120:
            warnings.append({
                "category": "meta_seo",
                "excerpt": f"Meta description too short ({len(meta)} chars, min 120): {meta}",
            })

    return warnings


def scan_draft(draft_text: str) -> list:
    if not draft_text.strip():
        return []
    try:
        msg = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": QA_PROMPT.format(article=draft_text[:8000])}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        return data.get("warnings", [])
    except Exception as e:
        print(f"  QA scan error (non-blocking): {e}")
        return []
