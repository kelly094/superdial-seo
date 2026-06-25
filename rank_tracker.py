"""
Google Search Console rank tracking.
First run opens a browser for OAuth consent. Token cached at data/gsc_token.json.

Usage:
    python rank_tracker.py --dry-run    # verify OAuth works, print slug list
"""

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import state

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
CLIENT_SECRET_PATH = Path("client_secret.json")
TOKEN_PATH = Path("data/gsc_token.json")
SITE_URL = os.getenv("GSC_SITE_URL", "").rstrip("/")

_QUERY_MIN_IMPRESSIONS = 5
_QUERY_TOP_N = 25
_DAYS = 7


def get_gsc_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
    return build("searchconsole", "v1", credentials=creds)


def _date_range():
    end = date.today()
    start = end - timedelta(days=_DAYS)
    return start.isoformat(), end.isoformat()


def fetch_page_metrics(service, slugs: list) -> list:
    """Fetch page-level metrics for all slugs in one API call."""
    start_date, end_date = _date_range()
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "rowLimit": 1000,
    }
    resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    slug_set = set(slugs)
    rows = []
    for row in resp.get("rows", []):
        page_url = row["keys"][0].rstrip("/")
        slug = page_url.split("/")[-1]
        if slug not in slug_set:
            continue
        rows.append({
            "slug": slug,
            "date": end_date,
            "position": round(row["position"], 2),
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "source": "page",
            "query": None,
        })
    return rows


def fetch_query_metrics(service, slug: str) -> list:
    """Fetch query-level metrics for a single article slug."""
    start_date, end_date = _date_range()
    page_url = f"{SITE_URL}/{slug}"
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "dimensionFilterGroups": [{
            "filters": [{"dimension": "page", "expression": page_url, "operator": "equals"}]
        }],
        "rowLimit": 100,
    }
    resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    rows = []
    for row in resp.get("rows", []):
        if row["impressions"] < _QUERY_MIN_IMPRESSIONS:
            continue
        rows.append({
            "slug": slug,
            "date": end_date,
            "position": round(row["position"], 2),
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "source": "query",
            "query": row["keys"][0],
        })
    rows.sort(key=lambda r: r["impressions"], reverse=True)
    return rows[:_QUERY_TOP_N]


def fetch_all(slugs: list) -> list:
    """Fetch page-level + query-level metrics for all slugs."""
    if not SITE_URL:
        raise ValueError("GSC_SITE_URL not set in .env")
    service = get_gsc_service()
    rows = fetch_page_metrics(service, slugs)
    tracked_slugs = {r["slug"] for r in rows}
    for slug in tracked_slugs:
        rows.extend(fetch_query_metrics(service, slug))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state.init_db()
    slugs = state.get_all_published_slugs()
    print(f"Published slugs to track: {slugs}")

    if args.dry_run:
        print("[dry-run] Authenticating with GSC...")
        get_gsc_service()
        print("GSC auth OK.")
    else:
        rows = fetch_all(slugs)
        print(f"Fetched {len(rows)} rows.")
