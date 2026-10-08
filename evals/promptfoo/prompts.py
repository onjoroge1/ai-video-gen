"""promptfoo prompt functions: render the pipeline's own prompts from fixtures.

Each function receives promptfoo's context ({"vars": {...}}) and returns the chat messages the
pipeline would send, so an eval exercises the identical request. Repo root is put on sys.path
because promptfoo runs these from its own working directory.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fixture(name: str) -> dict:
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as handle:
        return json.load(handle)


def planner(context: dict) -> list[dict]:
    """The causal-lane beat-sheet request for one cached dossier."""
    import story_planner as sp
    v = context.get("vars") or {}
    dossier = _fixture(v["dossier"])
    user = sp.planner_prompt(
        v["question"], int(v.get("duration") or 300), v.get("engine") or "removed_keystone",
        dossier, operator_direction=v.get("direction") or "")
    return [{"role": "system", "content": sp.planner_system_prompt()},
            {"role": "user", "content": user}]


def editor(context: dict) -> list[dict]:
    """The targeted editor's request for a script fixture with detected defects."""
    import script_editor as se
    v = context.get("vars") or {}
    script = _fixture(v["script"])
    defects = se.detect_defects(script, script.get("_claim_validation"))
    payload = se.build_payload(script, script.get("_research_dossier"), defects)
    return [{"role": "system", "content": se._SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def template(context: dict) -> list[dict]:
    """The scene-template fill request for one cached dossier (story_template)."""
    import story_template as st
    v = context.get("vars") or {}
    dossier = _fixture(v["dossier"])
    user = st.fill_prompt(v["question"], int(v.get("duration") or 300),
                          v.get("engine") or "removed_keystone", dossier,
                          operator_direction=v.get("direction") or "")
    return [{"role": "system", "content": st._SYSTEM},
            {"role": "user", "content": user}]
