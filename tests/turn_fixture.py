"""Shared fixture for the turn-by-45 tests (opening_turn, operator decision 2026-10-14).

fixtures/opening_turn/saved_openings.json was extracted read-only from the eight saved ladder
jobs (bees_v13-v16, asian-carp, escobar-hippos, history-aral-sea, history-aral-sea-v2): the
scenes through the first escalation, the planner's opening, a planner-like sheet rebuilt from the
accepted beats, aral-v2's approved plan, and the late-turn critic's hand labels -- words through
the end of the first sentence that states the consequence, and the second it ends (computed by
the critic with +0.7 s for a structural pause, which the word_times already contain; see
opening_turn.turn_end_sec). Nothing here reaches a provider.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import causal_story as cs
import opening_turn as ot

with open(os.path.join(ROOT, "fixtures", "opening_turn", "saved_openings.json"), encoding="utf-8") as _h:
    SAVED = json.load(_h)

LABELLED = {job: entry for job, entry in SAVED.items() if entry["label"]["words"]}
ESCAPE = "Except in October 1957, grids off, twenty-six queens flew free."
V16 = SAVED["bees_v16"]["deletion"]


def script_for(job, **extra):
    entry = SAVED[job]
    return dict({"hook": entry["hook"], "_opening": copy.deepcopy(entry["opening"]),
                 "_opening_contract": cs.OPENING_CONTRACT, "_story_engine": entry["engine"],
                 "_turn_rule": ot.stamp(entry["engine"], entry["runtime_sec"], "ladder"),
                 "scenes": copy.deepcopy(entry["scenes"])}, **extra)


def dossier_for(job, names=""):
    claims = [{"claim_id": c, "claim": f"claim {c}"} for c in SAVED[job]["known_claims"]]
    if names:
        claims.append({"claim_id": "cNAMES", "claim": names})
    return {"claims": claims}


def delete_sentences(text, sentences):
    for sentence in sentences:
        text = text.replace(sentence, " ")
    return " ".join(text.split())


def trimmed_rows():
    """bees_v16's opening reduced to 104 words by deleting its own sentences (validation step 5)."""
    script = script_for("bees_v16")
    return {scene["scene_id"]: delete_sentences(scene["narration"], V16["delete"])
            for scene in script["scenes"][:4]}
