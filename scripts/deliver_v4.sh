#!/bin/zsh
# Upload a delivered illustrated film privately, then audit it and check it against the
# four reported defects. One command, so the gap between "it rendered" and "we know what
# it is" stays short. Usage: scripts/deliver_v4.sh jobs/bees_b "Title" slug
set -e
cd /Users/obadiah/ai-video-gen-local
JOB=$1; TITLE=$2; SLUG=$3
[ -f "$JOB/explainer.mp4" ] || { echo "no explainer.mp4 in $JOB"; exit 1; }

echo "=== acceptance (the four defects + runtime)"
/opt/homebrew/bin/python3 scripts/accept_v4.py "$JOB" || true

echo "=== audit"
/opt/homebrew/bin/python3 scripts/audit_film.py "$JOB" | tee "$JOB/audit.txt" || true

echo "=== upload (private)"
/opt/homebrew/bin/python3 scripts/youtube_upload.py \
  --video "$JOB/explainer.mp4" --title "$TITLE" \
  --description-file "$JOB/description.txt" --thumbnail "$JOB/thumbnail.jpg"

echo "=== library"
F=/Users/obadiah/Documents/video/finished_videos
cp "$JOB/explainer.mp4" "$F/$SLUG.mp4"
cp "$JOB/thumbnail.jpg" "$F/$SLUG.thumb"
cp "$JOB/description.txt" "$F/$SLUG.desc"
cp "$JOB/audit.txt" "$F/$SLUG.audit" 2>/dev/null || true
echo "copied to $F/$SLUG.*  — index.json still needs its entry"
