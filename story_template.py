"""Scene-level story templates the engines own: fixed slots the writer fills, no splitter.

The causal lane planned in BEATS (facts) and a separate pass split each beat into scenes to
reach visual-state density. That split is where the killer bees film duplicated itself: one beat
became two scenes and the claim repair rewrote both halves toward the same sentence. A template
plans directly in SCENES. Every slot is one scene with a fixed role, a word budget and a target
visual-state count; the writer fills narration and cites claims, and nothing is split afterwards.

The spine is the engine's required roles in order (from event_functions). Escalation is the one
repeatable role, so it is a flexible BAND of consecutive scenes sized to the runtime; every other
role gets a share of the scene count by narrative weight. The result for a 300s film is roughly
the shape the delivered films reached (about 27 scenes), but authored instead of emergent.

  build_slots(engine_id, duration)         -> the ordered scene skeleton
  fill_prompt(question, duration, engine, dossier)  -> the writer request (one call)
  score_fill(filled, engine, dossier, duration)     -> deterministic 0-100, no model
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

# About this many seconds per scene. The delivered cane toad and killer bees films settled near
# 10.5 s/scene (27 scenes for ~285 s) with 4-5 visual states each, which the rendered gate passed
# once the holds were split. The template aims for that shape directly.
SCENE_SECONDS = 10.5
MIN_SCENES = 12
MAX_SCENES = 40
MIN_ESCALATION_SCENES = 2

# Share of the scene count per role. Escalation dominates because the compounding IS the story;
# the others are proportioned from the delivered films' beat counts. Normalised over the roles an
# engine actually has, then escalation absorbs the rounding remainder.
ROLE_WEIGHTS = {
    "setup": 0.17,
    "intervention": 0.08,
    "false_resolution": 0.08,
    "mechanism": 0.13,
    "escalation": 0.40,
    "reversal": 0.12,
    "takeaway": 0.04,
}

# The role order a filled template must follow. Takeaway is the spoken lesson the engines carry as
# `tool`; it is not a sourced event, so it never cites a claim.
ENGINE_ROLE_ORDER = {
    "removed_keystone": ("setup", "intervention", "false_resolution", "mechanism",
                         "escalation", "reversal", "takeaway"),
    "backfiring_solution": ("setup", "intervention", "false_resolution", "mechanism",
                            "escalation", "reversal", "takeaway"),
}
_DEFAULT_ORDER = ("setup", "intervention", "mechanism", "escalation", "reversal", "takeaway")

_TAKEAWAY_MEANING = ("one spoken sentence naming the pattern the story proves; no new fact, no "
                     "number, no proper noun the film has not already said")

_STOP = {"the", "and", "that", "with", "from", "into", "were", "was", "had", "has", "have",
         "then", "than", "this", "these", "those", "their", "they", "them", "its", "for", "but",
         "not", "are", "been", "being", "after", "before", "while", "where", "which", "about",
         "could", "would", "also", "more", "most", "some", "each", "both", "when", "over"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", _text(text).lower()) if w not in _STOP}


def role_order(engine_id: str) -> tuple[str, ...]:
    return ENGINE_ROLE_ORDER.get((engine_id or "").strip().lower(), _DEFAULT_ORDER)


def _role_label(engine_id: str, role: str) -> str:
    import event_functions as ef
    mapping = ef.map_for(engine_id)
    meanings = dict(getattr(mapping, "role_meanings", {}) or {}) if mapping else {}
    if role == "takeaway":
        return _TAKEAWAY_MEANING
    return meanings.get(role) or {
        "setup": "the world before the fix",
        "intervention": "the deliberate fix, introduced",
        "false_resolution": "the part that appeared to work",
        "mechanism": "why the fix backfires — the rule the story turns on",
        "escalation": "the consequence compounding, one further reach each scene",
        "reversal": "what the system became",
    }.get(role, role)


def target_scene_count(duration_sec: float) -> int:
    return max(MIN_SCENES, min(MAX_SCENES, round(float(duration_sec or 0) / SCENE_SECONDS)))


def _role_counts(engine_id: str, n_total: int) -> dict[str, int]:
    """Distribute n_total scenes across the engine's roles by weight; escalation takes the slack."""
    roles = role_order(engine_id)
    weights = {r: ROLE_WEIGHTS.get(r, 0.1) for r in roles}
    scale = sum(weights.values())
    counts = {r: max(1, int(round(n_total * weights[r] / scale))) for r in roles}
    # Reconcile to exactly n_total by moving scenes to/from the escalation band.
    counts["escalation"] = max(MIN_ESCALATION_SCENES,
                               counts.get("escalation", 0) + (n_total - sum(counts.values())))
    # If reconciliation overshot (tiny n), trim non-escalation roles down toward 1.
    while sum(counts.values()) > n_total:
        donor = max((r for r in roles if r != "escalation" and counts[r] > 1),
                    key=lambda r: counts[r], default=None)
        if donor is None:
            counts["escalation"] = max(MIN_ESCALATION_SCENES, counts["escalation"] - 1)
            if counts["escalation"] <= MIN_ESCALATION_SCENES and sum(counts.values()) > n_total:
                break
        else:
            counts[donor] -= 1
    return counts


def build_slots(engine_id: str, duration_sec: float) -> list[dict]:
    """The ordered scene skeleton: one dict per scene with role, label, word band, state target."""
    from runtime_planner import runtime_word_bounds
    from longform_evidence import MAX_STATES_PER_SCENE, TARGET_VISUAL_STATE_SECONDS
    n_total = target_scene_count(duration_sec)
    counts = _role_counts(engine_id, n_total)
    n_total = sum(counts.values())
    total_words = runtime_word_bounds(duration_sec, n_total)[0]
    per_scene = total_words / max(1, n_total)
    lo, hi = max(6, int(math.floor(per_scene * 0.7))), int(math.ceil(per_scene * 1.3))
    scene_seconds = float(duration_sec or 0) / max(1, n_total)
    states = max(2, min(MAX_STATES_PER_SCENE, round(scene_seconds / TARGET_VISUAL_STATE_SECONDS)))
    slots: list[dict] = []
    n = 0
    for role in role_order(engine_id):
        for k in range(counts.get(role, 0)):
            n += 1
            slots.append({
                "scene": n,
                "role": role,
                "label": _role_label(engine_id, role),
                "words_min": lo,
                "words_max": hi,
                "states": states,
                "band": "escalation" if role == "escalation" else "spine",
                "band_index": k + 1,
                "band_count": counts.get(role, 0),
                "is_cold_open": n == 1,
                "needs_claim": role != "takeaway",
            })
    return slots


_SYSTEM = ("You are a factual explainer writer filling a fixed scene template. Return ONLY valid "
           "JSON, no markdown, no code fences.")


def fill_prompt(question: str, duration_sec: float, engine_id: str,
                research_dossier: dict | None, *, operator_direction: str = "") -> str:
    """The one writer request for a whole film: fill every scene slot, in order."""
    import causal_story as cs
    from longform_research import claim_context_for_prompt
    slots = build_slots(engine_id, duration_sec)
    n = len(slots)
    lines = []
    for s in slots:
        band = (f" (escalation {s['band_index']} of {s['band_count']}: a FURTHER reach, scale or "
                "cost than the escalation before it — never the same one again)"
                if s["band"] == "escalation" else "")
        cold = (" — this scene opens the film: its narration is the HOOK (one sentence, at most "
                f"{cs.MAX_HOOK_WORDS} words, the promise) followed by the COLD OPEN (one sentence "
                "showing the aftermath of the fix gone wrong, a picture the viewer can see), and "
                "the first visual is that aftermath" if s["is_cold_open"] else "")
        claim = "" if not s["needs_claim"] else " — cite at least one claim_id"
        lines.append(f'{s["scene"]}. [{s["role"]}] {s["words_min"]}-{s["words_max"]} words, '
                     f'about {s["states"]} visual beats: {s["label"]}{band}{cold}{claim}')
    template = "\n".join(lines)
    claim_context = claim_context_for_prompt(research_dossier or {})
    schema = ('{"title": "...", "hook": "one sentence, the promise", '
              '"cold_open": {"text": "one aftermath sentence", "claim_refs": ["claim_id"]}, '
              '"opening_object": "the subject as it appears in the cold-open aftermath image", '
              '"scenes": [{"scene": <int>, "role": "<role>", "narration": "...", '
              '"visual": "one line, what the viewer sees", '
              '"claim_refs": [{"claim_id": "id", "narration_phrase": "the exact sentence it supports"}]}]}')
    out = [
        f'Write a {int(duration_sec)}-second factual explainer: "{question}".',
        f'Engine: {engine_id}. Fill EVERY one of the {n} scene slots below, in order, exactly one '
        'scene object per slot with the same scene number and role. Each scene is one spoken '
        'passage within its word budget; keep inside the budget so the film lands on time.',
        '',
        'HARD RULES, each enforced by a check after you write:',
        '- Every scene says something the earlier scenes did NOT. Never restate an earlier scene; '
        'refer back with an article or pronoun ("the queens", "that bend") instead of repeating it.',
        '- A scene asserts only what its cited claims support: no number, date, place, named actor, '
        'motive or quantity absent from the ledger. A scene with no sourced fact is pure connective '
        'tissue and needs no claim.',
        '- The cold open shows the damage; it does not restate the hook or explain anything.',
        '- The takeaway names the pattern in one sentence and introduces no new fact or proper noun.',
        '- No meta narration: never say "in this video", "explained like you are five", "as we saw".',
        '',
        'SCENE TEMPLATE:',
        template,
        '',
        f'Return ONLY JSON: {schema}',
    ]
    if claim_context:
        out += ['', 'BINDING RESEARCH CLAIM LEDGER (use only these; do not invent a claim or URL):',
                json.dumps(claim_context, ensure_ascii=False)]
    if operator_direction:
        out += ['', 'OPERATOR DIRECTION (subordinate to the rules above):', operator_direction]
    return "\n".join(out)


def _dossier_ids(research_dossier: dict | None) -> set[str]:
    return {_text(c.get("claim_id")) for c in ((research_dossier or {}).get("claims") or [])
            if isinstance(c, dict)}


def score_fill(filled: dict, engine_id: str, research_dossier: dict | None,
               duration_sec: float) -> dict:
    """Deterministic 0-100 for a filled template. Mirrors the pipeline's pre-spend gates."""
    import causal_story as cs
    slots = build_slots(engine_id, duration_sec)
    issues: list[str] = []
    score = 100.0
    if not isinstance(filled, dict):
        return {"score": 0.0, "issues": ["not a JSON object"]}
    scenes = filled.get("scenes") if isinstance(filled.get("scenes"), list) else []

    # Shape: one scene per slot, roles in the template order.
    if len(scenes) != len(slots):
        score -= 20
        issues.append(f"{len(scenes)} scenes for {len(slots)} slots")
    got_roles = [_text(s.get("role")).lower() for s in scenes]
    want_roles = [s["role"] for s in slots]
    if got_roles[:len(want_roles)] != want_roles[:len(got_roles)]:
        score -= 20
        issues.append("roles out of template order")

    # Cold open on scene 1.
    cold = filled.get("cold_open")
    cold_text = _text(cold.get("text")) if isinstance(cold, dict) else _text(cold)
    cold_issues = cs.check_cold_open(cold_text, _text(filled.get("hook")))
    known = _dossier_ids(research_dossier)
    cold_refs = [r for r in ((cold.get("claim_refs") or []) if isinstance(cold, dict) else []) if _text(r)]
    if cold_text and known and not [r for r in cold_refs if r in known]:
        cold_issues.append({"code": "COLD_OPEN_UNCITED"})
    if cold_issues:
        score -= 15
        issues.extend("cold open: " + _text(i.get("code")) for i in cold_issues)

    # Word budgets.
    over = []
    for slot, scene in zip(slots, scenes):
        n = len(_text(scene.get("narration")).split())
        if n and not (slot["words_min"] * 0.6 <= n <= slot["words_max"] * 1.4):
            over.append(f"scene {slot['scene']} {n}w (want {slot['words_min']}-{slot['words_max']})")
    if over:
        score -= min(15, 3 * len(over))
        issues.append("word budget: " + "; ".join(over[:4]))

    # Repeats: reuse the pipeline's own detector.
    import explainer_pipeline as ep
    dupes = ep.duplicate_narration([{"narration": _text(s.get("narration")),
                                     "causal_role": _text(s.get("role")),
                                     "beat_id": f"s{i}", "continues": ""}
                                    for i, s in enumerate(scenes)])
    if dupes:
        score -= 10 * len(dupes)
        issues.extend(f"repeat: scene {d['scene']} restates scene {d['duplicate_of']} ({d['overlap']:.0%})"
                      for d in dupes[:4])

    # Distinct escalation: consecutive escalation scenes must each add words.
    esc = [(slot["scene"], _words(scene.get("narration")))
           for slot, scene in zip(slots, scenes) if slot["band"] == "escalation"]
    thin = 0
    for a, b in zip(esc, esc[1:]):
        if a[1] and b[1] and len(a[1] & b[1]) / len(a[1] | b[1]) >= 0.5:
            thin += 1
    if thin:
        score -= 5 * thin
        issues.append(f"{thin} escalation scene(s) add little over the one before")

    # Claims: factual slots cite a claim in the ledger.
    if known:
        uncited = []
        for slot, scene in zip(slots, scenes):
            if not slot["needs_claim"]:
                continue
            refs = [_text((r or {}).get("claim_id")) for r in (scene.get("claim_refs") or [])
                    if isinstance(r, dict)]
            if not [r for r in refs if r in known]:
                uncited.append(slot["scene"])
        if uncited:
            score -= min(15, 2 * len(uncited))
            issues.append(f"{len(uncited)} factual scene(s) cite no ledger claim: {uncited[:6]}")

    # Meta phrases.
    meta = [slot["scene"] for slot, scene in zip(slots, scenes)
            if re.search(r"in this video|explained like|as we saw|let'?s dive", _text(scene.get("narration")), re.I)]
    if meta:
        score -= 5 * len(meta)
        issues.append(f"meta narration in scenes {meta}")

    words_total = sum(len(_text(s.get("narration")).split()) for s in scenes)
    return {"score": round(max(0.0, score), 1), "issues": issues, "scenes": len(scenes),
            "slots": len(slots), "words": words_total,
            "escalation_scenes": sum(1 for s in slots if s["band"] == "escalation"),
            "repeats": len(dupes)}
