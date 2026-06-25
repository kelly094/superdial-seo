import json
import math
import os
import sys

import anthropic
import requests
import state
from dotenv import load_dotenv
from utils import slugify

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
        * (1 + math.log1p(kw["cpc"]))
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
