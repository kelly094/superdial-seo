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
