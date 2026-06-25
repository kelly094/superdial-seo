import os
import re
from collections import defaultdict

from dotenv import load_dotenv
from tavily import TavilyClient

MIN_CITE_YEAR = 2024

load_dotenv()

_client = None

# Only cite from these authoritative sources — everything else is filtered out
TRUSTED_DOMAINS = [
    "hfma.org",
    "caqh.org",
    "cms.gov",
    "beckershospitalreview.com",
    "ama-assn.org",
    "advisory.com",
    "healthaffairs.org",
    "modernhealthcare.com",
    "fiercehealthcare.com",
    "mgma.com",
    "himss.org",
    "kff.org",
    "commonwealthfund.org",
    "nejm.org",
    "jamanetwork.com",
    "healthcarefinancenews.com",
    "healthcareitnews.com",
    "medscape.com",
    "ajmc.com",
]


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        key = os.getenv("TAVILY_API_KEY")
        if not key:
            raise ValueError("TAVILY_API_KEY not set in .env")
        _client = TavilyClient(api_key=key)
    return _client


def _is_recent(source: dict) -> bool:
    text = f"{source.get('title', '')} {source.get('content', '')} {source.get('url', '')}"
    years = re.findall(r'\b(20\d{2})\b', text)
    return any(int(y) >= MIN_CITE_YEAR for y in years)


def _trusted_domain(url: str) -> str | None:
    """Return the matched trusted domain, or None if not trusted."""
    for d in TRUSTED_DOMAINS:
        if d in url:
            return d
    return None


def _diverse(sources: list, max_per_domain: int = 2, total: int = 6) -> list:
    """Cap results at max_per_domain per source and return up to total."""
    counts: dict = defaultdict(int)
    out = []
    for s in sources:
        domain = _trusted_domain(s.get("url", "")) or "other"
        if counts[domain] < max_per_domain:
            out.append(s)
            counts[domain] += 1
        if len(out) >= total:
            break
    return out


def fetch_research_context(keyword: str) -> str:
    """Return a formatted block of recent, authoritative sources for the keyword."""
    try:
        client = _get_client()
    except ValueError:
        return ""

    def _search_and_filter(query: str, max_results: int = 10, depth: str = "advanced") -> list:
        resp = client.search(query=query, max_results=max_results, search_depth=depth)
        return [
            s for s in resp.get("results", [])
            if _is_recent(s) and _trusted_domain(s.get("url", "")) is not None
        ]

    # Pass 1: broad query, filter to trusted domains only
    sources = _search_and_filter(
        f"{keyword} 2025 2026 healthcare statistics report data"
    )

    # Pass 2: if still thin, explicitly name the publications we want
    if len(sources) < 3:
        extra = _search_and_filter(
            f"{keyword} site:hfma.org OR site:caqh.org OR site:cms.gov "
            f"OR site:beckershospitalreview.com OR site:modernhealthcare.com 2025",
            depth="basic",
        )
        seen = {s["url"] for s in sources}
        sources += [s for s in extra if s["url"] not in seen]

    # Pass 3: targeted search per high-value domain if still sparse
    if len(sources) < 3:
        for site in ["hfma.org", "beckershospitalreview.com", "caqh.org", "cms.gov"]:
            if len(sources) >= 4:
                break
            extra = _search_and_filter(
                f"{keyword} 2025",
                max_results=5,
                depth="basic",
            )
            # only keep the ones from this specific site
            seen = {s["url"] for s in sources}
            new = [s for s in extra if site in s.get("url", "") and s["url"] not in seen]
            sources += new

    if not sources:
        return ""

    diverse = _diverse(sources)

    lines = [
        "Recent authoritative sources (2024+ only) — cite these inline where relevant "
        "and list every source used in ## Sources. Use at least 3 different sources:"
    ]
    for s in diverse:
        snippet = s.get("content", "")[:300].strip().replace("\n", " ")
        lines.append(f"- {s['title']} | {s['url']}\n  {snippet}")

    return "\n".join(lines)
