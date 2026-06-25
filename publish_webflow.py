"""
Publishes article drafts from drafts/ to Webflow CMS Reference collection as unpublished items.

Usage:
    python publish_webflow.py --list-fields          # inspect your collection schema
    python publish_webflow.py drafts/some-slug.md    # publish a single draft
    python publish_webflow.py --all                  # publish all drafts in drafts/ folder
"""

import argparse
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

WEBFLOW_API_TOKEN = os.getenv("WEBFLOW_API_TOKEN")
WEBFLOW_COLLECTION_ID = os.getenv("WEBFLOW_COLLECTION_ID")

if not WEBFLOW_API_TOKEN:
    sys.exit("Error: WEBFLOW_API_TOKEN not set in .env")
if not WEBFLOW_COLLECTION_ID:
    sys.exit("Error: WEBFLOW_COLLECTION_ID not set in .env")

BASE_URL = "https://api.webflow.com/v2"
HEADERS = {
    "Authorization": f"Bearer {WEBFLOW_API_TOKEN}",
    "Content-Type": "application/json",
}

# ── Field name mapping ──────────────────────────────────────────────────────
# Run `python publish_webflow.py --list-fields` to see your collection's
# exact field slugs, then update these to match.
FIELD_NAME = "name"           # item title / name field (always required)
FIELD_SLUG = "slug"           # URL slug field
FIELD_BODY = "post-body"      # rich text / body field — UPDATE if different
FIELD_META = "meta-description"  # meta description field — UPDATE if different or remove
# ────────────────────────────────────────────────────────────────────────────


def parse_frontmatter(path):
    text = Path(path).read_text()
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not fm_match:
        sys.exit(f"No frontmatter found in {path}")

    fm = {}
    for line in fm_match.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"')

    body = text[fm_match.end():].strip()
    return fm, body


def list_fields():
    url = f"{BASE_URL}/collections/{WEBFLOW_COLLECTION_ID}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    data = r.json()

    print(f"\nCollection: {data.get('displayName', data.get('name', ''))}")
    print(f"Slug: {data.get('slug', '')}\n")
    print(f"{'Field Name':<35} {'Slug':<35} {'Type':<20} {'Required'}")
    print("-" * 100)
    for field in data.get("fields", []):
        required = "Yes" if field.get("isRequired") else ""
        print(f"{field.get('displayName', ''):<35} {field.get('slug', ''):<35} {field.get('type', ''):<20} {required}")


def publish_draft(path, dry_run=False):
    fm, body = parse_frontmatter(path)

    title = fm.get("title", "")
    slug = fm.get("slug", "")
    meta = fm.get("meta_description", "")

    if not title:
        sys.exit(f"No title found in frontmatter of {path}")

    field_data = {
        FIELD_NAME: title,
        FIELD_SLUG: slug,
        FIELD_BODY: body,
    }
    if meta and FIELD_META:
        field_data[FIELD_META] = meta

    payload = {
        "isArchived": False,
        "isDraft": True,  # creates as unpublished — Kelly reviews before publishing
        "fieldData": field_data,
    }

    if dry_run:
        print(f"[dry-run] Would create: '{title}' (slug: {slug})")
        return

    url = f"{BASE_URL}/collections/{WEBFLOW_COLLECTION_ID}/items"
    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code in (200, 201):
        item_id = r.json().get("id", "")
        print(f"Created (unpublished): '{title}' — item ID: {item_id}")
    else:
        print(f"Error {r.status_code}: {r.text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="Draft .md files to publish")
    parser.add_argument("--all", action="store_true", help="Publish all drafts in drafts/ folder")
    parser.add_argument("--list-fields", action="store_true", help="Inspect collection field schema")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be published without creating items")
    args = parser.parse_args()

    if args.list_fields:
        list_fields()
        return

    paths = []
    if args.all:
        paths = sorted(Path("drafts").glob("*.md"))
        if not paths:
            sys.exit("No .md files found in drafts/")
    elif args.files:
        paths = [Path(f) for f in args.files]
    else:
        parser.print_help()
        return

    for path in paths:
        print(f"Publishing {path.name}...", end=" ", flush=True)
        try:
            publish_draft(path, dry_run=args.dry_run)
        except requests.HTTPError as e:
            print(f"HTTP error: {e}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()


def publish_draft_and_return_id(path) -> str:
    """Publish a single draft and return the Webflow item ID. Raises on failure."""
    fm, body = parse_frontmatter(path)
    title = fm.get("title", "")
    slug = fm.get("slug", "")
    meta = fm.get("meta_description", "")

    if not title:
        raise ValueError(f"No title in frontmatter of {path}")

    field_data = {FIELD_NAME: title, FIELD_SLUG: slug, FIELD_BODY: body}
    if meta and FIELD_META:
        field_data[FIELD_META] = meta

    payload = {"isArchived": False, "isDraft": True, "fieldData": field_data}
    url = f"{BASE_URL}/collections/{WEBFLOW_COLLECTION_ID}/items"
    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code in (200, 201):
        return r.json().get("id", "")
    raise RuntimeError(f"Webflow error {r.status_code}: {r.text}")
