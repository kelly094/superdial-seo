#!/bin/bash
# Weekly keyword scan — runs every Monday at 7am via crontab.
# Discovers new keywords, then syncs DB to GitHub so Streamlit Cloud updates.

set -e

DIR="/Users/kelly/Documents/superdial-seo"
LOG="$DIR/logs/cron.log"
mkdir -p "$DIR/logs"

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') weekly keyword scan ===" >> "$LOG"

cd "$DIR"
source venv/bin/activate

python pipeline.py --step keywords >> "$LOG" 2>&1

# Push updated DB to GitHub so Streamlit Cloud reflects new keywords
git add data/pipeline.db
git diff --cached --quiet || git commit -m "weekly keyword scan $(date '+%Y-%m-%d')" && git push >> "$LOG" 2>&1

echo "Done." >> "$LOG"
