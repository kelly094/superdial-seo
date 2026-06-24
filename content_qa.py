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
