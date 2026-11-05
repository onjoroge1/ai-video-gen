"""Segmenter for the story-contract lane: approved narration -> scenes, WITHOUT changing words.

The split is deterministic (sentence boundaries, contract parts and length), so no model can
reword the approved text on the way. A model may then plan the pictures for each scene (image
prompt and visual beats anchored on verbatim phrases); its anchors are checked against the scene's
own words and replaced by the sentence's first words when they do not match.

The output is the `_state.json` shape that jobs/lionfish-v2/hand_build.py produced and resumed
through the existing claim ledger, storyboard, TTS and render path: scenes carrying narration,
claim_refs, an event built from the cited claims, roles, and visual beats.

`role` here is a picture/palette label for the downstream renderer, not a story structure: the
lane applies no role order (story_contract_policy). It is chosen from the contract part, then
moved to the nearest role whose accepted claim kinds include every claim the scene cites, so the
claim ledger -- which stays hard -- never refuses a true fact for wearing the wrong label.
"""
from __future__ import annotations

import copy
import json
import math
import re

import story_contract_policy as policy

ENGINE = "unfolding_consequence"     # the downstream renderer's vocabulary for roles and palettes
TARGET_SCENE_WORDS = 34
MAX_SCENE_WORDS = 50
MIN_SCENE_WORDS = 12
WORDS_PER_BEAT = 8                   # about one picture per 3 s (rendered-contract slideshow rule)

PART_ROLE = {"opening": "setup", "attempt": "intervention", "complication": "mechanism",
             "development": "escalation", "ending": "reversal"}
# Fallback order when a part's role cannot cite the scene's claim kinds.
ROLE_FALLBACKS = ("setup", "escalation", "mechanism", "reversal", "intervention")
EVENT_FUNCTION = {"setup": "establishes_problem", "intervention": "fix_adopted",
                  "false_resolution": "apparent_success", "hinge": "warning_recorded",
                  "mechanism": "consequence_pathway", "escalation": "consequence_spreads",
                  "reversal": "still_unfolding", "tool": ""}

STYLE = "Hand-drawn ink-and-cut-paper illustration, natural full colour, crisp ink lines. "
TAIL = " No text, no labels, no maps, no gore."


class SegmentError(ValueError):
    pass


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


def _part_base(part: str) -> str:
    base = _text(part).lower().split("_")[0]
    return base if base in PART_ROLE else "development"


def split_scenes(sentences: list[dict]) -> list[list[int]]:
    """Contiguous groups of sentence indices. Breaks at a contract part change once the scene has
    MIN_SCENE_WORDS, and before a sentence that would push it past MAX_SCENE_WORDS (or past the
    target, when the scene is already long enough). The first scene always carries a claim."""
    groups: list[list[int]] = []
    current: list[int] = []
    words = 0
    for i, s in enumerate(sentences):
        n = len(s["text"].split())
        part_change = bool(current) and _text(s.get("part")) != _text(sentences[current[-1]].get("part"))
        too_long = bool(current) and (words + n > MAX_SCENE_WORDS
                                      or (words >= TARGET_SCENE_WORDS and words + n > TARGET_SCENE_WORDS + 8))
        if current and ((part_change and words >= MIN_SCENE_WORDS) or too_long):
            groups.append(current)
            current, words = [], 0
        current.append(i)
        words += n
    if current:
        if groups and words < MIN_SCENE_WORDS and sum(len(sentences[j]["text"].split()) for j in groups[-1]) + words <= MAX_SCENE_WORDS + 10:
            groups[-1].extend(current)
        else:
            groups.append(current)
    # The first scene must cite something: an opening of pure framing is merged forward.
    while len(groups) > 1 and not any(sentences[j]["claim_ids"] for j in groups[0]):
        groups[0:2] = [groups[0] + groups[1]]
    return groups


def _accepted(role: str) -> tuple:
    try:
        import story_fact_model as sfm
        return tuple(sfm.accepted_claim_kinds(role, ENGINE))
    except Exception:  # noqa: BLE001 - no table, no constraint
        return ()


def compatible_role(preferred: str, claim_kinds: list[str]) -> str:
    kinds = {k for k in claim_kinds if k}
    if not kinds:
        return preferred
    for role in (preferred,) + tuple(r for r in ROLE_FALLBACKS if r != preferred):
        accepted = _accepted(role)
        if not accepted or kinds <= set(accepted):
            return role
    return preferred


def _anchor_ok(anchor: str, narration: str) -> bool:
    return bool(anchor) and anchor in narration


def _default_anchor(sentence: str) -> str:
    return " ".join(sentence.split()[:4])


def visual_beat(anchor, purpose, visual, objects, *, source="distinct", shot="medium",
                camera="locked", human=False) -> dict:
    return {"anchor_phrase": anchor, "purpose": purpose, "visual": visual, "state_before": "",
            "state_after": "", "required_objects": list(objects or [])[:4],
            "forbidden_objects": ["text", "labels"], "source": source, "asset_strategy": source,
            "pure_evidence": not human, "human_visible": bool(human), "bolt_visible": False,
            "bolt_action": "", "new_information": True, "shot_size": shot,
            "camera_direction": camera}


def plan_visuals_prompt(question: str, scenes: list[dict], contract: dict) -> str:
    rows = "\n".join(f"scene {i}: {s['narration']}" for i, s in enumerate(scenes, 1))
    return f"""You plan pictures for an illustrated documentary ("{question}"), hand-drawn ink and
cut paper, natural colour, no text in any picture. The narration is FIXED; you never change it.

Recurring image (if any): {json.dumps(contract.get('recurring_image'), ensure_ascii=False)}

Scenes:
{rows}

For each scene give an image_prompt (the scene's master picture) and visual_beats: one beat per
~{WORDS_PER_BEAT} spoken words, each anchored on an EXACT phrase copied from that scene's narration
(3-6 words, verbatim, in order of appearance). Real people are drawn anonymous (from behind or in
profile, never a likeness). Each beat: anchor_phrase, visual (what we see), required_objects (2-3
nouns), human_visible (true only if a person is clearly visible), shot_size (wide|medium|close).

Reply with JSON only:
{{"scenes": [{{"image_prompt": "...", "emphasis_words": ["..."], "visual_beats": [
   {{"anchor_phrase": "...", "visual": "...", "required_objects": ["..."], "human_visible": false,
     "shot_size": "medium"}}]}}]}}"""


def apply_visual_plan(scenes: list[dict], plan: dict | None) -> list[dict]:
    """Attach image prompts and beats; every anchor must be a verbatim substring of the scene."""
    rows = (plan or {}).get("scenes") if isinstance(plan, dict) else None
    report = []
    for i, scene in enumerate(scenes):
        row = rows[i] if isinstance(rows, list) and i < len(rows) and isinstance(rows[i], dict) else {}
        narration = scene["narration"]
        sentences = scene["_sentences"]
        beats, rejected = [], 0
        for b in row.get("visual_beats") or []:
            if not isinstance(b, dict):
                continue
            anchor = _text(b.get("anchor_phrase"))
            if not _anchor_ok(anchor, narration):
                rejected += 1
                continue
            beats.append(visual_beat(anchor, "evidence", _text(b.get("visual")) or narration[:120],
                                     b.get("required_objects") or [], shot=_text(b.get("shot_size")) or "medium",
                                     human=bool(b.get("human_visible"))))
        # Enough pictures: one per WORDS_PER_BEAT words, at least one per sentence start that has
        # none, each anchored on the sentence's own first words.
        need = max(1, math.ceil(len(narration.split()) / WORDS_PER_BEAT))
        anchored = {b["anchor_phrase"] for b in beats}
        for s in sentences:
            if len(beats) >= need:
                break
            anchor = _default_anchor(s)
            if anchor in anchored or not _anchor_ok(anchor, narration):
                continue
            beats.append(visual_beat(anchor, "evidence", f"an illustration of: {s}", [], shot="medium"))
            anchored.add(anchor)
        beats.sort(key=lambda b: narration.find(b["anchor_phrase"]))
        if beats:
            beats[0]["source"] = beats[0]["asset_strategy"] = "master"
        scene["visual_beats"] = beats
        prompt = _text(row.get("image_prompt")) or (beats[0]["visual"] if beats else narration[:160])
        scene["image_prompt"] = STYLE + prompt.rstrip(".") + "." + TAIL
        scene["text"] = dict(scene.get("text") or {}, emphasis_words=[w for w in row.get("emphasis_words") or [] if _text(w)][:3])
        scene["motion_anchor_phrase"] = beats[0]["anchor_phrase"] if beats else _default_anchor(sentences[0])
        report.append({"scene": i + 1, "beats": len(beats), "rejected_anchors": rejected, "needed": need})
    return report


SCENE_DEFAULTS = {
    "scene_type": "cinematic_intro", "environment_type": "nature", "human_present": False,
    "human_action": "", "mascot_present": False, "bolt_mode": "absent", "shot_type": "medium",
    "text_overlay": "", "text_sub": "",
    "text": {"placement": "lower_third", "alignment": "center", "emphasis_words": [],
             "title_color": "warm coral", "accent_color": "red", "subtitle_color": "white", "card": False},
    "_story_format": "standard_explainer", "scope": "primary_story", "changes_state": {"from": "", "to": ""},
    "_story_compiler_version": "story_contract_v1", "question_opened": "", "question_answered": "",
    "new_complication": "", "visible_consequence": "", "opens_loop": "", "closes_loop": "",
    "human_intention": "", "human_belief": "", "viewer_knows": "", "human_knows": "",
    "expected_outcome": "", "actual_outcome": "", "belief_changed": "", "decision_caused": "",
    "continuity_anchor": "", "causal_link": "", "beat_part": 1, "beat_part_count": 1,
}


def build_scenes(sentences: list[dict], dossier: dict) -> list[dict]:
    """Scenes in hand_build's shape, before pictures. Raises SegmentError if words would change."""
    claims = {c["claim_id"]: c for c in (dossier or {}).get("claims") or [] if c.get("claim_id")}
    groups = split_scenes(sentences)
    scenes, prev_scene = [], ""
    last_with_claims = max((i for i, g in enumerate(groups) if any(sentences[j]["claim_ids"] for j in g)), default=-1)
    for n, group in enumerate(groups, 1):
        sents = [sentences[j] for j in group]
        narration = policy.normalize_narration(" ".join(s["text"] for s in sents))
        refs = list(dict.fromkeys(c for s in sents for c in s["claim_ids"] if c in claims))
        part = _part_base(sents[0].get("part"))
        scene = copy.deepcopy(SCENE_DEFAULTS)
        if not refs and n - 1 > last_with_claims:
            role = "tool"                               # a claim-free close: the callback
        else:
            role = compatible_role(PART_ROLE[part], [_text(claims[c].get("claim_kind")).lower() for c in refs])
        sid = "scene_%03d" % n
        prev = scenes[-1] if scenes else None
        # A run of scenes in one role is one beat told in parts (v2's event_01, event_01b, ...):
        # the first scene is the beat, the rest continue it. A claim-free middle scene continues
        # the previous beat and carries its event.
        run_base = ""
        if prev is not None and (prev["role"] == role or (not refs and role != "tool")):
            run_base = prev["continues"] or prev["beat_id"]
        if run_base:
            k = sum(1 for x in scenes if x["continues"] == run_base) + 1
            beat_id, continues = f"{run_base}{chr(ord('a') + min(k, 25))}", run_base
            event = ({"text": " ".join(_text(claims[c].get("claim")) for c in refs), "claim_refs": refs}
                     if refs else dict(prev["event"]))
        elif role == "tool":
            beat_id, continues, event = f"event_{n:02d}:tool", "", {"text": "", "claim_refs": []}
        else:
            beat_id, continues = f"event_{n:02d}", ""
            event = {"text": " ".join(_text(claims[c].get("claim")) for c in refs), "claim_refs": refs}
        scene.update(
            n=str(n), id=str(n), story_beat_n=str(n), scene_id=sid, beat_id=beat_id,
            continues=continues, role=role, _role=role, story_role=role, causal_role=role,
            chapter=1 + sum(1 for k in range(1, n) if _part_base(sentences[groups[k][0]].get("part"))
                            != _part_base(sentences[groups[k - 1][0]].get("part"))),
            narration=narration, _words_as_written=len(narration.split()),
            claim_refs=[{"claim_id": c, "narration_phrase": s["text"], "evidence_id": ""}
                        for s in sents for c in s["claim_ids"] if c in claims],
            event=event, event_function=EVENT_FUNCTION.get(role, ""), caused_by=prev_scene,
            story_pct=0.0, _sentences=[s["text"] for s in sents],
            _contract_parts=list(dict.fromkeys(_text(s.get("part")) for s in sents)),
            _sentence_kinds=[s["kind"] for s in sents])
        scenes.append(scene)
        prev_scene = sid
    tools = [s for s in scenes if s["role"] == "tool"]
    for s in tools:
        s["context_refs"] = [x["beat_id"] for x in scenes if x["role"] != "tool" and not x["continues"]][-4:]
    total = sum(len(s["narration"].split()) for s in scenes) or 1
    seen = 0
    for s in scenes:
        s["story_pct"] = round(seen / total, 3)
        seen += len(s["narration"].split())
    check_words_preserved(sentences, scenes)
    return scenes


def check_words_preserved(sentences: list[dict], scenes: list[dict]) -> None:
    approved = policy.normalize_narration(" ".join(s["text"] for s in sentences))
    produced = policy.scenes_narration(scenes)
    if approved != produced:
        a, b = approved.split(), produced.split()
        k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        raise SegmentError(f"segmenter changed the narration at word {k}: "
                           f"{' '.join(a[k:k + 6])!r} -> {' '.join(b[k:k + 6])!r}")


def _opening_fields(contract: dict, sentences: list[dict]) -> dict:
    opening = [s for s in sentences if _part_base(s.get("part")) == "opening"] or sentences[:3]
    questions = [s["text"] for s in opening if s["text"].rstrip().endswith("?")]
    first = opening[0]["text"] if opening else ""
    refs_with = [s for s in opening if s["claim_ids"]]
    image = contract.get("recurring_image") if isinstance(contract.get("recurring_image"), dict) else {}
    return {
        "voice": "story_contract", "frame": first,
        "problem": refs_with[0]["text"] if refs_with else "",
        "solution": "", "transition": "",
        "consequence": refs_with[-1]["text"] if refs_with else "",
        "question": questions[-1] if questions else _text(contract.get("central_question")),
        "callback": {"kind": "object", "text": _text(image.get("image"))} if _text(image.get("image")) else {},
        "claim_refs": {"problem": list(refs_with[0]["claim_ids"]) if refs_with else [],
                       "solution": [], "transition": [],
                       "consequence": list(refs_with[-1]["claim_ids"]) if refs_with else []},
        "missing_claims": [],
    }


def build_state(record: dict, *, title: str = "", visual_plan: dict | None = None,
                duration_sec: int = 300) -> dict:
    """The `_state.json` the pipeline resumes from, for an APPROVED narration record."""
    sentences = record["sentences"]
    dossier = record["dossier"]
    contract = record.get("contract") or {}
    scenes = build_scenes(sentences, dossier)
    visual_report = apply_visual_plan(scenes, visual_plan)
    check_words_preserved(sentences, scenes)
    image = contract.get("recurring_image") if isinstance(contract.get("recurring_image"), dict) else {}
    callback = _text(image.get("image"))
    budget = {"first_act_scene_count": min(5, len(scenes)), "first_act_cap": 1, "overall_cap": 4,
              "bolt_scenes": [], "overrides": []}
    beats = [{"n": s["n"], "pct": s["story_pct"], "role": s["role"], "beat": s["narration"][:80],
              "human_present": False, "bolt_mode": "absent"} for s in scenes]
    hp = contract.get("human_perspective") or {}
    script = {
        "title": title or _text(record.get("question")),
        "hook": sentences[0]["text"],
        "scenes": scenes,
        "style_mode": "educational",
        "_lane": policy.LANE,
        "_story_contract_lane": {
            "lane_version": record.get("lane_version"),
            "contract_sha256": record.get("contract_sha256"),
            "approved_narration_sha256": record.get("sha256"),
            "narration_version": record.get("version"),
            "status": record.get("status"),
            "gate_policy": policy.GATES,
            "visual_plan": visual_report,
        },
        "_research_dossier": dossier,
        "_story_engine": ENGINE,
        "_planned_story_engine": ENGINE,
        "_compiled_story": True,
        "_story_format": "standard_explainer",
        "_story_format_requested": "standard_explainer",
        "_story_format_fallback_reason": "",
        "_opening": _opening_fields(contract, sentences),
        # Keeps the opening identity check (a real person no claim names is refused) and the turn
        # MEASURE; the lane makes the turn report-only (story_contract_policy).
        "_opening_contract": "ladder_v1",
        "_character_plan": budget,
        "_entailment_cache": {},
        "_parallel_cases": [],
        "_payoffs": [],
        "_causal_repairs": [],
        "_topic_channel": "",
        "_story_contract": {
            "version": 2, "core_question": _text(contract.get("central_question")) or _text(record.get("question")),
            "title_promise": title or _text(record.get("question")),
            "thumbnail_promise": sentences[0]["text"],
            "accepted_belief": _text((contract.get("reasonable_attempt") or {}).get("why_it_made_sense")),
            "replacement_model": _text(contract.get("ending_answer")),
            "human_subject": _text(hp.get("person")),
            # Every storyboard beat needs a declared intent; the contract's want, else its question.
            "subject_goal": _text(hp.get("want")) or _text(contract.get("central_question")),
            "recurring_location": "", "opening_object": callback, "final_callback_object": callback,
            "character_budget": budget, "stages": [], "open_loops": [],
            "target_runtime_sec": duration_sec, "beat_count": len(scenes), "scene_count": len(scenes),
            "beats": beats, "story_format_requested": "standard_explainer",
            "story_format_effective": "standard_explainer",
        },
    }
    return {"script": script, "style_mode": "educational", "short_grade": None,
            "video_format": "landscape"}


def segment_report(state: dict) -> str:
    scenes = state["script"]["scenes"]
    lines = ["# Segmented narration (words unchanged)", ""]
    for s in scenes:
        refs = ", ".join(r["claim_id"] for r in s["claim_refs"]) or "—"
        lines.append(f"{s['n']}. [{s['role']}] ({s['_words_as_written']}w; {refs}; "
                     f"{len(s['visual_beats'])} pictures) {s['narration']}")
    return "\n".join(lines) + "\n"


def strip_private(state: dict) -> dict:
    """Remove the segmenter's private helper keys before the state is resumed."""
    out = json.loads(json.dumps(state))
    for s in out["script"]["scenes"]:
        for k in ("_sentences",):
            s.pop(k, None)
    return out


