#!/bin/bash
# Run after the pipeline to push the latest DB + drafts to GitHub.
# Streamlit Cloud auto-redeploys within ~30 seconds of a push.
#
# Usage: ./sync.sh
#        ./sync.sh "ran generate + published 3 articles"  (custom message)

set -e

MSG="${1:-pipeline sync $(date '+%Y-%m-%d %H:%M')}"

git add data/pipeline.db drafts/
git diff --cached --quiet && echo "Nothing new to sync." && exit 0

git commit -m "$MSG"
git push
echo "Synced. Streamlit Cloud will redeploy shortly."
