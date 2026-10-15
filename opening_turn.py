"""THE TURN BY 45 SECONDS (operator decision, 2026-10-14).

The sentence that first states the opening's consequence -- in plain words, what the decision
released or what the programme cost: the escape, the flood, "the sea got nothing back" -- must
END within 45.0 seconds of narration. A hinge that only signals trouble ("But a pond is not a
sealed box.") does not count.

WHY A WORD COUNT. Before TTS the only clock is words. 45 s at the SLOWEST measured narration
rate (2.588 w/s, longform_evidence) is 116 spoken words counted from the frame's first word; at
the rates measured to the turn (2.62-2.82 w/s) 116 words lands at 41-44 s. The writer is given a
TARGET of 40 s = 103 words, the direction files' "about forty seconds", below the limit, because
a ceiling gets treated as a target (causal_story.MECHANISM_DEADLINE_PCT's comment, measured).

WHAT IT REPLACES. The ladder's opening group was sized by the 20% mechanism deadline -- 164-166
spoken words at 300 s, every job -- and the turn landed at its end: 146-179 words (54-66 s) in
seven saved films, 236 (89 s) in escobar. The logged "words to the consequence" counted to the end
of the first ESCALATION (231-291) and was renamed. This is the first ENFORCED positional quantity
on a ladder opening (the 10-07 contract made the shorts-fitted ones advisory); it is located
semantically, by the opening read's verbatim "turn" quote, and checked deterministically.

SCOPE. OPENING_MODE=ladder (contract ladder_v1, myth included) films of removed_keystone,
backfiring_solution and state_programme at a requested runtime of 225 s or more. Below 225 s the
20% cap is already under 45 s; hook mode and the reveal engines are untouched.

MEASUREMENT.
  * ENFORCED BY THE STRUCTURAL FALLBACK ALONE since paid check (a), 2026-10-15 (TURN_LOCATOR):
    the read's quote matched the hand labels on 5 of the 8 saved openings, and the bar was 8/8.
    The read's NONE (no sentence states it) still raises OPENING_CONSEQUENCE_UNSPOKEN
    (UNSPOKEN_FROM_READ): the fallback says where, never whether.
  * By quote (reported; enforcing only under TURN_LOCATOR="quote"): the read's "turn" field is
    accepted only when it is a verbatim substring of ONE sentence between the first intervention
    row and the last part of the first mechanism beat; quote_turn_words is every spoken word
    through the end of that sentence.
  * Conservative fallback, which never under-measures the hand labels (tests/fixtures):
      shape A -- the consequence claims are disjoint from the mechanism event's -- the end of the
               hinge row (the bees: the hinge says the escape);
      shape B -- they overlap, the engine is state_programme (harm_pathway IS the mechanism), or
               the consequence claims are unknown -- the end of the first mechanism beat's last
               part (carp, aral, escobar: the planner filed the consequence as the mechanism).
  * Shape B under the fallback is late BY CONSTRUCTION: the allocator ends the opening group at
    103 words and the first mechanism beat follows it, so the end of that beat lands at about
    103 + 60-75 words. The single revision is not bought for it (it could only get there by
    cutting the mechanism into the opening budget); the film records late_turn.
  * After TTS: turn_end_sec = the scene's start_sec + the word's end in that scene's
    word_times. Report-only, never part of the readiness score (no third opening grade).

If still late after the single revision, an unattended World film continues: `late_turn`
{words, est_sec, measured_sec} is recorded in run_result and is NOT a degraded reason.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from longform_evidence import SLOWEST_MEASURED_WORDS_PER_SECOND

TURN_LIMIT_SEC = 45.0
TURN_TARGET_SEC = 40.0
WORDS_PER_SECOND = SLOWEST_MEASURED_WORDS_PER_SECOND
TURN_LIMIT_WORDS = int(TURN_LIMIT_SEC * WORDS_PER_SECOND)     # 116
TURN_TARGET_WORDS = int(TURN_TARGET_SEC * WORDS_PER_SECOND)   # 103
TURN_ENGINES = frozenset({"removed_keystone", "backfiring_solution", "state_programme"})
TURN_MIN_RUNTIME_SEC = 225.0
LATE_TURN = "LATE_TURN"
# The one opening row that may GROW in the turn revision: the row that receives the consequence
# (the row before the hinge). Every other row may only shrink.
CONSEQUENCE_ROW_GROWTH_WORDS = 20
# Feasibility of a planned opening against the 103-word target. 25 words is the smallest row the
# allocator hands out (103 - a 17-word frame - a 10-word hinge = 76 over three rows), and the
# myth/bust/danger/question block measured 46 words on escobar, 33 of them after its myth line.
MAX_ROWS_BEFORE_MECHANISM = 3
ROW_FLOOR_WORDS = 25
HINGE_WORDS = 10
MYTH_BLOCK_WORDS = 33
NONE_QUOTE = "NONE"
# WHAT ENFORCES THE TURN. The design located it by the read's verbatim "turn" quote, on the
# condition that the quote matched the critic's hand labels on all eight saved openings. Paid check
# (a), 2026-10-15 ($0.128, eight reads): 5/8. bees_v13, v15, v16 and carp quoted the labelled
# sentence and bees_v14 answered NONE, but escobar quoted two sentences ("They bred. Then their
# young wandered off ..."), and aral and aral-v2 quoted a later, more explicit sentence than the
# label (247 against 159 words; 197 against 172). The read never measured EARLIER than a label,
# but the bar was 8/8, so by the operator's rule for that check the turn is ENFORCED by the
# structural fallback alone: "fallback". The quote is still asked for and recorded beside it
# (quote_turn_words, quote_scene, consequence_spoken) as a report. "quote" restores the design.
TURN_LOCATOR = "fallback"
# THE READ'S "NONE" STILL BLOCKS. The fallback is conservative about WHERE the consequence is
# said, never about WHETHER: writer check (b), 2026-10-15, wrote bees_v16's opening under the new
# budgets and closed it on a hinge that only signals trouble ("But a grid only works while it
# stays on."). The fallback counts that hinge as the turn (116 words, on time) and claim binding
# passes it, while the read answered NONE -- correctly, as it did for bees_v14 in check (a), with
# no false NONE on the seven openings that do state it. So a NONE on the narration it judged
# still raises OPENING_CONSEQUENCE_UNSPOKEN at the storyboard (read_says_unspoken). It can only
# add a finding, never relax the fallback; False makes the read's answer a report as well.
UNSPOKEN_FROM_READ = True

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_OPENING_ROWS = ("setup", "intervention", "false_resolution")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _role(scene: dict) -> str:
    return _text((scene or {}).get("causal_role") or (scene or {}).get("story_role")).lower()


def _words(text: str) -> int:
    return len(_text(text).split())


def _tokens(text: str) -> list[str]:
    folded = _text(text).lower().replace("’", "'").replace("‘", "'")
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", folded)


def _contains(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return bool(n) and any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE.split(_text(text)) if part.strip()]


# ── scope ──────────────────────────────────────────────────────────────────────────────────────

def rule_applies(engine_id: str | None, runtime_sec, opening_mode: str | None = "ladder") -> bool:
    """Does the turn rule bind this film? Ladder opening, a backfire/History engine, >= 225 s."""
    mode = _text(opening_mode).lower()
    if mode not in ("ladder", "ladder_v1"):
        return False
    try:
        runtime = float(runtime_sec or 0.0)
    except (TypeError, ValueError):
        return False
    return _text(engine_id).lower() in TURN_ENGINES and runtime >= TURN_MIN_RUNTIME_SEC


def stamp(engine_id: str | None, runtime_sec, opening_mode: str | None) -> dict:
    """The rule as a script carries it (`_turn_rule`), so every later stage reads one decision."""
    applies = rule_applies(engine_id, runtime_sec, opening_mode)
    return {"applies": applies, "engine": _text(engine_id).lower(),
            "runtime_sec": float(runtime_sec or 0.0),
            "target_words": TURN_TARGET_WORDS, "limit_words": TURN_LIMIT_WORDS,
            "limit_sec": TURN_LIMIT_SEC, "words_per_second": WORDS_PER_SECOND}


def script_runtime(script: dict) -> float:
    stamped = script.get("_turn_rule") if isinstance(script.get("_turn_rule"), dict) else {}
    plan = script.get("_runtime_plan") if isinstance(script.get("_runtime_plan"), dict) else {}
    try:
        return float(stamped.get("runtime_sec") or plan.get("target_seconds") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def script_rule(script: dict | None) -> bool:
    """The rule for a finished script: its stamp when it carries one, else derived from its engine,
    its opening contract and its target runtime (checkpoints written before the stamp)."""
    script = script if isinstance(script, dict) else {}
    stamped = script.get("_turn_rule")
    if isinstance(stamped, dict) and "applies" in stamped:
        return bool(stamped["applies"])
    import causal_story as cs
    contract = "ladder" if _text(script.get("_opening_contract")) == cs.OPENING_CONTRACT else ""
    return rule_applies(script.get("_story_engine"), script_runtime(script), contract)


# ── where the turn can be ──────────────────────────────────────────────────────────────────────

def window(scenes: list) -> dict:
    """Indices of the rows the turn may sit in, and of the rows around it. {} without a mechanism.

    lo: the first intervention row (the frame and the need come before any consequence);
    hi: the last part of the FIRST mechanism beat; hinge: the hinge before the mechanism;
    receiving: the row that receives the consequence -- the last intervention/false_resolution
    row before the hinge (the row before the mechanism when there is no hinge).
    """
    scenes = [s for s in scenes or [] if isinstance(s, dict)]
    roles = [_role(s) for s in scenes]
    mechanism = next((i for i, r in enumerate(roles) if r == "mechanism"), None)
    if mechanism is None:
        return {}
    hi = mechanism
    while (hi + 1 < len(scenes) and roles[hi + 1] == "mechanism"
           and (_text(scenes[hi + 1].get("continues")) or int(scenes[hi + 1].get("beat_part") or 1) > 1)):
        hi += 1
    lo = next((i for i, r in enumerate(roles[:mechanism]) if r == "intervention"), 0)
    hinge = next((i for i in range(mechanism - 1, -1, -1) if roles[i] == "hinge"), None)
    stop = hinge if hinge is not None else mechanism
    receiving = next((i for i in range(stop - 1, -1, -1)
                      if roles[i] in ("false_resolution", "intervention")), max(0, stop - 1))
    return {"lo": lo, "hi": hi, "mechanism": mechanism, "hinge": hinge, "receiving": receiving}


def consequence_shape(engine_id: str | None, consequence_claims, mechanism_claims) -> str:
    """A: the consequence is its own fact, told before the mechanism. B: it is (part of) the
    mechanism's event -- always for state_programme, whose harm_pathway IS the mechanism -- or
    unknown, which is measured as B because B never under-measures."""
    if _text(engine_id).lower() == "state_programme":
        return "B"
    wanted = {_text(c) for c in consequence_claims or [] if _text(c)}
    if not wanted:
        return "B"
    return "B" if wanted & {_text(c) for c in mechanism_claims or [] if _text(c)} else "A"


def event_claims(scene: dict) -> list[str]:
    event = (scene or {}).get("event")
    refs = event.get("claim_refs") if isinstance(event, dict) else None
    return [_text(r) for r in refs or [] if _text(r)]


def opening_consequence_claims(opening: dict | None) -> list[str]:
    refs = ((opening or {}).get("claim_refs") or {}) if isinstance(opening, dict) else {}
    return [_text(r) for r in (refs.get("consequence") or []) if _text(r)] if isinstance(refs, dict) else []


def scenes_shape(scenes: list, opening: dict | None, engine_id: str | None) -> str:
    bounds = window(scenes)
    mechanism_claims = event_claims(scenes[bounds["mechanism"]]) if bounds else []
    return consequence_shape(engine_id, opening_consequence_claims(opening), mechanism_claims)


def window_digest(scenes: list) -> str:
    """The narration the turn was measured on: frame through the last mechanism part."""
    bounds = window(scenes)
    if not bounds:
        return ""
    joined = "\n".join(_text(s.get("narration")) for s in scenes[:bounds["hi"] + 1])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _words_before(scenes: list, index: int) -> int:
    return sum(_words(s.get("narration")) for s in scenes[:index])


def locate(scenes: list, quote: str, lo: int, hi: int) -> tuple[int, int, int] | None:
    """(scene index, sentence index, words through the end of that sentence) for the first
    sentence in rows lo..hi that contains the quote verbatim (case, punctuation and quote marks
    folded); None when no single sentence does."""
    wanted = _tokens(quote)
    if len(wanted) < 2:
        return None
    for index in range(max(0, lo), min(hi, len(scenes) - 1) + 1):
        before = _words_before(scenes, index)
        running = 0
        for k, sentence in enumerate(sentences(scenes[index].get("narration"))):
            running += _words(sentence)
            if _contains(_tokens(sentence), wanted):
                return index, k, before + running
    return None


def is_none_quote(quote) -> bool:
    return _text(quote).strip("\"'. ").upper() == NONE_QUOTE


def fallback_row(bounds: dict, shape: str) -> int:
    """The conservative structural turn row: shape A, the hinge (the row before the mechanism when
    there is none); shape B, the last part of the first mechanism beat."""
    if shape == "A":
        index = bounds["hinge"] if bounds["hinge"] is not None else bounds["mechanism"] - 1
    else:
        index = bounds["hi"]
    return max(0, index)


def measure_turn(scenes: list, opening: dict | None, engine_id: str | None, quote: str = "",
                 row_hint: int | None = None, applies: bool = True,
                 locator: str | None = None) -> dict:
    """Where the turn ends, in spoken words from the frame's first word. See the module notes.

    `locator` (default TURN_LOCATOR): "fallback" -- turn_words, scene, late and source are the
    structural fallback; the read's quote, when it locates one sentence in the window, is reported
    as quote_turn_words / quote_scene and decides nothing. "quote" -- the design: the quote first,
    then `row_hint`, then the fallback.

    `row_hint`: a row known to END on the consequence (a storyboard repair that appended it
    there). Under "quote" it is used when the quote does not locate the turn; under "fallback" it
    is reported only, because the repair was ASKED to put the consequence there.
    """
    locator = (locator or TURN_LOCATOR).strip().lower()
    scenes = [s for s in scenes or [] if isinstance(s, dict)]
    bounds = window(scenes)
    base = {"applies": bool(applies), "limit_words": TURN_LIMIT_WORDS,
            "target_words": TURN_TARGET_WORDS, "limit_sec": TURN_LIMIT_SEC, "locator": locator}
    if not bounds:
        return dict(base, measurable=False, late=False)
    shape = scenes_shape(scenes, opening, engine_id)
    spoken = None
    quote = _text(quote)
    if is_none_quote(quote):
        spoken, quote = False, ""
    found = locate(scenes, quote, bounds["lo"], bounds["hi"]) if quote else None
    if found:
        spoken = True
    hint = (int(row_hint) if row_hint is not None and bounds["lo"] <= int(row_hint) <= bounds["hi"]
            else None)
    if locator == "quote" and found:
        index, _sentence, words = found
        source = "quote"
    elif locator == "quote" and hint is not None:
        index, source = hint, "hint"
        words = _words_before(scenes, index + 1)
    else:
        index = fallback_row(bounds, shape)
        words, source = _words_before(scenes, index + 1), "fallback"
    out = dict(base, measurable=True, turn_words=words, scene=index + 1,
               scene_id=_text(scenes[index].get("scene_id")), source=source, shape=shape,
               quote=quote if found else "", consequence_spoken=spoken,
               est_sec=round(words / WORDS_PER_SECOND, 1),
               late=bool(applies) and words > TURN_LIMIT_WORDS,
               window=[bounds["lo"] + 1, bounds["hi"] + 1], digest=window_digest(scenes))
    if found:
        out.update(quote_turn_words=found[2], quote_scene=found[0] + 1)
    if hint is not None and source != "hint":
        out.update(hint_turn_words=_words_before(scenes, hint + 1), hint_scene=hint + 1)
    return out


def turn_row_is_mechanism(scenes: list, turn: dict | None) -> bool:
    """Does the measured turn end on a mechanism row? Under the fallback that is every shape-B
    film: the turn is counted to the end of the first mechanism beat, which the allocator places
    after the 103-word opening group, so it is late by construction and no opening revision can
    bring it inside 116 words without cutting the mechanism into the opening budget."""
    index = int((turn or {}).get("scene") or 0) - 1
    scenes = scenes or []
    return 0 <= index < len(scenes) and isinstance(scenes[index], dict) and _role(scenes[index]) == "mechanism"


def measure_script(script: dict, quote: str = "", row_hint: int | None = None) -> dict:
    return measure_turn(script.get("scenes") or [], script.get("_opening"),
                        script.get("_story_engine"), quote=quote, row_hint=row_hint,
                        applies=script_rule(script))


def remeasure(script: dict) -> dict:
    """Re-measure on the script's CURRENT narration, carrying the read's quote and any repair
    hint. A semantic 'no sentence states it' survives only while the narration it judged does."""
    prior = script.get("_opening_turn") if isinstance(script.get("_opening_turn"), dict) else {}
    scenes = script.get("scenes") or []
    hint = None
    if _text(prior.get("hint_scene_id")):
        hint = next((i for i, s in enumerate(scenes)
                     if _text(s.get("scene_id")) == _text(prior.get("hint_scene_id"))), None)
    turn = measure_script(script, quote=_text(prior.get("quote")), row_hint=hint)
    if not turn.get("measurable"):
        return turn
    if prior.get("consequence_spoken") is False and prior.get("digest") == turn.get("digest"):
        turn["consequence_spoken"] = False
    if _text(prior.get("hint_scene_id")):
        turn["hint_scene_id"] = prior["hint_scene_id"]
    for key in ("revised", "read_quote"):
        if key in prior:
            turn[key] = prior[key]
    return turn


def read_says_unspoken(script: dict, locator: str | None = None) -> bool:
    """The opening read found no sentence stating the consequence, on the narration it read.

    A blocking finding under the "quote" locator, and under the "fallback" one while
    UNSPOKEN_FROM_READ holds (see there); otherwise a report, and OPENING_CONSEQUENCE_UNSPOKEN
    is left to claim binding."""
    if (locator or TURN_LOCATOR).strip().lower() != "quote" and not UNSPOKEN_FROM_READ:
        return False
    turn = script.get("_opening_turn") if isinstance(script.get("_opening_turn"), dict) else {}
    if turn.get("consequence_spoken") is not False:
        return False
    digest = window_digest(script.get("scenes") or [])
    return bool(digest) and digest == turn.get("digest")


# ── after TTS ──────────────────────────────────────────────────────────────────────────────────

def _bare(word) -> str:
    return re.sub(r"[^a-z0-9]", "", str(word or "").lower())


def turn_end_sec(scenes: list, turn: dict, scene_starts: list, word_times_by_scene: list) -> dict:
    """When the turn sentence's last word ENDS, from the audio actually bought.

    scene start (audio_timing_report) + that word's end in the scene's word_times. The word
    times are transcribed from the padded file, so a structural pause before the scene is already
    inside them (bees_v16 scene 4: "free" ends at 4.96 s of a 5.31 s file whose raw TTS is
    4.61 s); adding the pause again would count it twice. {} when the inputs do not line up.
    """
    if not turn or not turn.get("measurable"):
        return {}
    index = int(turn.get("scene") or 0) - 1
    if not (0 <= index < len(scenes) and index < len(scene_starts) and index < len(word_times_by_scene)):
        return {}
    start = scene_starts[index]
    timings = [w for w in (word_times_by_scene[index] or []) if isinstance(w, (list, tuple)) and len(w) >= 3]
    tokens = _text(scenes[index].get("narration")).split()
    in_scene = int(turn.get("turn_words") or 0) - _words_before(scenes, index)
    if start is None or not timings or not tokens or in_scene <= 0:
        return {}
    last = min(in_scene, len(tokens)) - 1
    target = _bare(tokens[last])
    occurrence = sum(1 for t in tokens[:last + 1] if _bare(t) == target)
    matched = [i for i, w in enumerate(timings) if _bare(w[0]) == target]
    if target and len(matched) >= occurrence:
        position, method = matched[occurrence - 1], "matched_word"
    else:
        position = min(len(timings) - 1, max(0, round((last + 1) * len(timings) / len(tokens)) - 1))
        method = "proportional"
    end = float(start) + float(timings[position][2])
    return {"turn_end_sec": round(end, 1), "method": method,
            "late": end > TURN_LIMIT_SEC, "limit_sec": TURN_LIMIT_SEC}


def late_turn_record(turn: dict | None) -> dict | None:
    """run_result's `late_turn` when a film still misses after its single revision; else None.
    Reported, never a degraded reason (operator decision 3, 2026-10-14)."""
    if not isinstance(turn, dict) or not turn.get("applies") or not turn.get("late"):
        return None
    return {"words": turn.get("turn_words"), "est_sec": turn.get("est_sec"),
            "measured_sec": turn.get("measured_sec"), "limit_words": TURN_LIMIT_WORDS,
            "limit_sec": TURN_LIMIT_SEC, "source": turn.get("source"), "shape": turn.get("shape")}


def run_result_fields(script: dict | None) -> dict:
    turn = (script or {}).get("_opening_turn") if isinstance(script, dict) else None
    if not isinstance(turn, dict) or not turn.get("measurable"):
        return {}
    keep = ("applies", "turn_words", "est_sec", "measured_sec", "source", "shape", "scene",
            "quote", "late", "limit_words", "target_words", "revised", "locator",
            "quote_turn_words", "quote_scene", "consequence_spoken", "read_quote")
    return {"opening_turn": {k: turn.get(k) for k in keep if k in turn},
            "late_turn": late_turn_record(turn)}


def log_line(turn: dict, stage: str) -> str:
    if not turn or not turn.get("measurable"):
        return f"Turn ({stage}): not measurable (no mechanism row)"
    where = {"quote": "by the read's quote", "hint": "at the repaired consequence row",
             "fallback": f"structural fallback, shape {turn.get('shape')}"}.get(turn.get("source"), "")
    measured = (f", ends at {turn['measured_sec']:.1f}s" if isinstance(turn.get("measured_sec"), (int, float))
                else "")
    report = ""
    if turn.get("source") != "quote" and turn.get("quote_turn_words") is not None:
        report = (f" — the read quotes scene {turn.get('quote_scene')}, ending at word "
                  f"{turn['quote_turn_words']} (report only)")
    elif turn.get("consequence_spoken") is False:
        report = (" — the read says NO sentence states the consequence"
                  + (" (OPENING_CONSEQUENCE_UNSPOKEN at the storyboard)"
                     if UNSPOKEN_FROM_READ or turn.get("source") == "quote" else " (report only)"))
    return (f"Turn ({stage}): {turn['turn_words']} words to the end of the first consequence "
            f"(scene {turn['scene']}, {where}; ~{turn['est_sec']:.1f}s at {WORDS_PER_SECOND} w/s"
            f"{measured}) — target {TURN_TARGET_WORDS}, limit {TURN_LIMIT_WORDS}"
            + (" — LATE_TURN" if turn.get("late") else "")
            + ("" if turn.get("applies") else " (report only: the turn rule does not bind this film)")
            + report)


# ── the plan, before any writing spend ─────────────────────────────────────────────────────────

def _compiled_opening(plan: dict, engine_id: str, research_dossier: dict | None) -> list[dict]:
    """The sheet's beats in the order the compiler will narrate them, hinge device included."""
    from copy import deepcopy
    import story_compiler as sc
    import story_engines as se
    import story_fact_model as sfm
    beats = [deepcopy(b) for b in (plan or {}).get("beats") or []
             if isinstance(b, dict) and (_text(b.get("beat")) or sfm.event_of(b)["text"])]
    for i, beat in enumerate(beats):
        beat["n"] = i + 1
    claims = None
    try:
        import explainer_pipeline as ep
        claims = ep._spine_claims(research_dossier or {})
    except Exception:                       # noqa: BLE001 - the order is a report, not a gate
        claims = None
    result = sc.compile_roles(beats, engine_id, claims)
    if not result.get("compiled"):
        return []
    rows = sc.splice_derived(result.get("beats") or [], result)
    order = se.expected_order(engine_id)
    rows = [b for b in rows if (b.get("role") or "") in order]
    rows.sort(key=lambda b: order.index(b["role"]))
    if "mechanism" in [b["role"] for b in rows] and "hinge" not in [b["role"] for b in rows]:
        mechanism = next(i for i, b in enumerate(rows) if b["role"] == "mechanism")
        rows.insert(mechanism, {"role": "hinge", "beat_id": "(compiler hinge device)",
                                "event": {"text": "", "claim_refs": []}})
    return rows


def plan_feasibility(plan: dict, engine_id: str, research_dossier: dict | None, duration_sec,
                     opening_mode: str = "ladder", myth: bool = False) -> dict:
    """Can this sheet's opening reach its consequence by the 103-word target? Deterministic, $0.

    Flags: more than three narrated beats before the mechanism; no consequence claim_refs, or ones
    the dossier does not hold (aral-v2's top-level layout read as empty); a frame + myth block +
    rows + hinge floor over the target. Records the shape and the compiled order, which is not the
    listed order (aral-v2 listed the warning before apparent_success; the film did not).
    """
    import story_fact_model as sfm
    out = {"applies": rule_applies(engine_id, duration_sec, opening_mode),
           "target_words": TURN_TARGET_WORDS, "limit_words": TURN_LIMIT_WORDS}
    if not out["applies"]:
        return out
    import explainer_pipeline as ep
    opening = ep._plan_opening(plan)
    rows = _compiled_opening(plan, engine_id, research_dossier)
    out["compiled_order"] = [f"{b['role']} ({_text(b.get('beat_id'))})" for b in rows]
    mechanism = next((i for i, b in enumerate(rows) if b["role"] == "mechanism"), None)
    before = [b for b in rows[:mechanism if mechanism is not None else len(rows)]
              if b["role"] in _OPENING_ROWS]
    issues = []
    out["rows_before_mechanism"] = len(before)
    if mechanism is None:
        issues.append("TURN_NO_MECHANISM: the sheet compiles no mechanism, so the turn cannot be placed")
    if len(before) > MAX_ROWS_BEFORE_MECHANISM:
        issues.append(f"TURN_TOO_MANY_ROWS: {len(before)} narrated beats before the mechanism "
                      f"({', '.join(b['role'] for b in before)}); at most {MAX_ROWS_BEFORE_MECHANISM} "
                      f"fit a {TURN_TARGET_WORDS}-word turn -- fold one into another")
    consequence = opening_consequence_claims(opening)
    known = {_text(c.get("claim_id")) for c in ((research_dossier or {}).get("claims") or [])
             if isinstance(c, dict)}
    if not opening:
        issues.append("TURN_NO_OPENING: the sheet has no opening block with a consequence")
    elif not consequence:
        issues.append("TURN_CONSEQUENCE_UNCITED: opening.claim_refs.consequence is empty, so no "
                      "opening row can carry the consequence's facts")
    elif known and [c for c in consequence if c not in known]:
        issues.append("TURN_CONSEQUENCE_UNKNOWN_CLAIM: the consequence cites "
                      f"{[c for c in consequence if c not in known]}, which the dossier does not hold")
    frame = _text((opening or {}).get("frame")) or _text((plan or {}).get("hook"))
    # The frame is spoken as the hook, which is held to MAX_HOOK_WORDS (a longer one is rewritten
    # before any narration is written: aral-v2 planned 19 words and spoke 16).
    import causal_story as cs
    frame_words = min(_words(frame), cs.MAX_HOOK_WORDS)
    estimate = (frame_words + (MYTH_BLOCK_WORDS if myth else 0)
                + max(1, len(before)) * ROW_FLOOR_WORDS + HINGE_WORDS)
    out["estimate_words"] = estimate
    if estimate > TURN_TARGET_WORDS:
        issues.append(f"TURN_OPENING_TOO_LONG: frame {frame_words}"
                      + (f" + myth/bust/danger/question ~{MYTH_BLOCK_WORDS}" if myth else "")
                      + f" + {max(1, len(before))} row(s) x {ROW_FLOOR_WORDS} + hinge {HINGE_WORDS}"
                      f" = {estimate} words before the turn, over the {TURN_TARGET_WORDS}-word target")
    mechanism_claims = sfm.event_of(rows[mechanism])["claim_refs"] if mechanism is not None else []
    out["shape"] = consequence_shape(engine_id, consequence, mechanism_claims)
    out["issues"] = issues
    out["feasible"] = not issues
    return out


def feasibility_markdown(feasibility: dict) -> list[str]:
    if not feasibility or not feasibility.get("applies"):
        return []
    lines = [f"Turn: {feasibility['target_words']} target / {feasibility['limit_words']} limit "
             f"spoken words, frame included (40 s / 45 s at {WORDS_PER_SECOND} w/s); shape "
             f"{feasibility.get('shape', '?')} ("
             + ("the consequence is its own fact, spoken before the hinge"
                if feasibility.get("shape") == "A" else
                "the consequence is the mechanism's event: say it plainly before the hinge, "
                "and let the mechanism document it") + ")"]
    if feasibility.get("compiled_order"):
        lines.append("Compiled order: " + " -> ".join(feasibility["compiled_order"]))
    lines.append(f"Narrated beats before the mechanism: {feasibility.get('rows_before_mechanism')}"
                 f" (estimated floor {feasibility.get('estimate_words')} words to the turn)")
    if feasibility.get("issues"):
        lines.append("TURN NOT FEASIBLE AS PLANNED -- edit plan.approved.json before approving:")
        lines += [f"  - {issue}" for issue in feasibility["issues"]]
    else:
        lines.append("Turn feasible as planned.")
    return lines
