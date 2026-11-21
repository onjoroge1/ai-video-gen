#!/usr/bin/env python3
"""Translated title + description for a Field Guide Short in the 20 languages that YouTube
Studio's auto-translate gives viral Shorts (operator, 2026-11-19).
    python3 scripts/fg_localize_short.py <video_id> <job_dir>
Run from ~/ai-video-gen-local. Title/description only (no subtitle tracks)."""
import sys
sys.path.insert(0, "scripts")
from dotenv import load_dotenv; load_dotenv(".env")
import localize_video as lv
NAMES = {"ar": "Arabic", "bn": "Bengali", "de-DE": "German", "es-US": "Spanish (US / Latin American)",
         "fr-FR": "French", "hi": "Hindi", "id": "Indonesian", "it": "Italian", "iw": "Hebrew",
         "ja": "Japanese", "ko": "Korean", "ml": "Malayalam", "nl-NL": "Dutch",
         "pa": "Punjabi (Gurmukhi script)", "pl": "Polish", "pt-BR": "Portuguese (Brazilian)",
         "ru": "Russian", "ta": "Tamil", "te": "Telugu", "uk": "Ukrainian"}
lv.LANG_NAMES.update(NAMES)
sys.exit(lv.main([sys.argv[1], "--job", sys.argv[2], "--channel", "fieldguide",
                  "--langs", ",".join(NAMES), "--no-captions", "--if-changed"]))
