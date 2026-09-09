"""Causal-chain story contract: the shape the reference explainers actually use.

The illustrated lane inherited a positional arc — a beat's role came from where it sat in the
scene list, so `_role_for(index, count)` could label a fact dump a "reversal" purely because it
landed 76% of the way through. Nothing about the story had to be true for the arc to validate.

This module models the other thing. A causal story is a chain: each step happens *because of* the
step before it, and the video's job is to walk that chain until the situation has inverted. The
link is declared by the author and checked here, so a script that lists six facts in a row fails
even when its beats are perfectly spaced.

Shape taken from two reference videos, measured rather than assumed:

* one-sentence hook that promises the reversal but withholds the concrete subject;
* a spoken, numbered step spine, unequal in length;
* the mechanism named once, early (16% of runtime), then demonstrated for the rest;
* a false resolution broken by a single short hinge sentence;
* an escalation chain where each consequence is caused by the previous one;
* an end state explicitly worse than the start;
* optionally, the same pattern shown in other domains, which turns a story into a lens;
* a close that hands the viewer the opening object back as a tool.

Provider-free and render-free on purpose: this validates intent before a cent is spent, and the
illustrated lane consumes it rather than reimplementing it.
"""
from __future__ import annotations

import os
import re
from typing import Any


SCHEMA_VERSION = "causal_story_v1"

# The mechanism must land inside this fraction of runtime. The reference states its principle at
# 36s of 220s (16.4%) and spends the remaining 84% earning it. This is the single largest
# difference from the "reveal an answer every so often" shape it replaces.
# Measured, not chosen, and re-measured as the corpus grew. Five reference videos place the
# mechanism at 16.4%, 17.3%, 19.4%, 19.6% and 19.7% of runtime — every one inside this line. It was
# originally fitted to two of them and four later references agreed, so it is a real property of
# the format rather than an artifact of a small sample. (hippo_weed sits at 54.8%, but that is
# almost_happened_plan, which carries its own 60% override: a plan that never ran cannot state why
# it would have failed until late.)
#
# Overridable because a run may need to ship despite a late mechanism, NOT because the number is
# soft. Raising it moves the output away from the references the corpus exists to match.
#
# RAISING IT ALSO DOES NOT WORK, which was measured rather than argued. The spine prompt tells the
# planner the mechanism "must sit in the first {pct}% of the list", so the planner aims at the
# boundary and drifts a few seconds past it wherever the boundary is:
#
#     deadline 20% (38s)  ->  mechanism landed at 43s
#     deadline 26% (48s)  ->  mechanism landed at 55s
#
# The beat moved LATER when the line moved later. No value of this constant fixes LATE_MECHANISM;
# the planner has to be given a TARGET near where the references actually sit (~18%) instead of a
# ceiling to drift up against, because a ceiling gets treated as a target.
MECHANISM_DEADLINE_PCT = float(os.environ.get("MECHANISM_DEADLINE_PCT", "0.20"))
# Reference hooks are 15 and 8 words. The cap is the promise, not the topic.
MAX_HOOK_WORDS = 18
# "Except the problem is not solved." is 6 words. A long hinge is not a hinge.
MAX_HINGE_WORDS = 10
MIN_ESCALATIONS = 2
# Spoken chapters are not causal steps. The reference videos group 12 causal steps into 6 spoken
# chapters and 11 into 4 — a presentational spine laid over the chain, which is why aligning the
# two one-to-one drifted by up to 31 seconds. Bands are the observed 6 and 4, widened.
MIN_CHAPTERS = 4
MAX_CHAPTERS = 8
MIN_PARALLEL_CASES = 2
# Below this runtime the contract relaxes four rules. Every fixture the contract was FITTED to runs
# 101-225s and the rules encode that length as if it were the format: a 220-second telling has room
# to state its principle in the first fifth, hand its opening object back at the end, and stack two
# parallel cases. A 64-second telling of the SAME STORY, by the same engine, does none of those --
# see fixtures/causal/cobra_bounty_short.json, which is recorded with expect.pass false precisely to
# mark where the contract stopped describing the format and started describing the run time.
#
# 120s, not 90 or 64: the shortest fitted reference is 101s and the short reference is 64s, so the
# boundary sits between them with room on both sides rather than on top of either.
SHORT_FORM_MAX_SEC = float(os.environ.get("SHORT_FORM_MAX_SEC", "120"))
# The reference short states its principle at 30.8%. Reference documentaries land at 16-20%, and
# that gap is structural: a story with four steps instead of six reaches its rule later as a
# fraction, because the setup it must lay first does not shrink proportionally.
SHORT_FORM_MECHANISM_PCT = float(os.environ.get("SHORT_FORM_MECHANISM_PCT", "0.35"))
# Two sentences, not one, and the second reverses the first: "The government paid people to kill
# cobras. So people started making cobras." The turn IS the hook at this length. Still bounded --
# three sentences is a summary, not a promise.
SHORT_FORM_MAX_HOOK_SENTENCES = 2
# One well-chosen echo carries the pattern in a minute. Demanding two spends runtime the format
# does not have on proving something the viewer already accepted.
SHORT_FORM_MIN_PARALLEL_CASES = 1


def is_short_form(runtime_sec: float) -> bool:
    """Is this runtime short enough that the compressed contract applies?

    A positive runtime under the boundary. Zero or missing means unknown, and unknown keeps the
    stricter rules: a contract should not relax because a caller forgot to say how long the video is.
    """
    try:
        runtime = float(runtime_sec or 0.0)
    except (TypeError, ValueError):
        return False
    return 0.0 < runtime <= SHORT_FORM_MAX_SEC

SETUP = "setup"
INTERVENTION = "intervention"
FALSE_RESOLUTION = "false_resolution"
HINGE = "hinge"
MECHANISM = "mechanism"
ESCALATION = "escalation"
REVERSAL = "reversal"
GENERALIZATION = "generalization"
TOOL = "tool"
VERDICT = "verdict"

STEP_ROLES = (
    SETUP, INTERVENTION, FALSE_RESOLUTION, HINGE, MECHANISM,
    ESCALATION, REVERSAL, GENERALIZATION, TOOL, VERDICT,
)
# Two ways to land the same beat, both observed. The lens close hands the opening object back as
# a question the viewer can reuse; the indictment close restates the opening claim now that it
# has been proved. Requiring the lens close rejected the second reference video outright, which
# is what a held-out fixture is for.
CLOSING_ROLES = (TOOL, VERDICT)
# Articles carry no callback signal. Matching on the first word of "the extraction system" meant
# testing whether the close contained the word "the", which every close does.
_STOPWORDS = {"a", "an", "the", "its", "his", "her", "their", "our", "this", "that"}
# Roles that may appear more than once. Everything else is a singleton: two hinges means the
# story broke its own false resolution twice, which reads as a structural mistake, not a beat.
_REPEATABLE = {ESCALATION, GENERALIZATION}
_CHAPTER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight")
# Consume the marker's own punctuation too; leaving the full stop behind meant the "hinge"
# measured after stripping still began with ". ".
_MARKER = re.compile(r"^\s*step\s+(?:%s|\d+)\b[.:,;\u2014-]*\s*" % "|".join(_CHAPTER_WORDS), re.I)



def _text(value: Any) -> str:
    return str(value or "").strip()


def _words(value: str) -> int:
    return len(_text(value).split())


def _issue(code: str, message: str, step_id: str = "") -> dict:
    return {"code": code, "message": message, "step_id": step_id}


def _normalize_steps(raw: Any) -> list[dict]:
    steps = []
    for index, item in enumerate(raw or []):
        item = item if isinstance(item, dict) else {}
        steps.append({
            "step_id": _text(item.get("step_id")) or f"step_{index + 1:02d}",
            "index": index,
            "role": _text(item.get("role")).lower(),
            "event_function": _text(item.get("event_function")),
            "label": _text(item.get("label")),
            "start_sec": float(item.get("start_sec") or 0.0),
            "situation": _text(item.get("situation")),
            "caused_by": _text(item.get("caused_by")),
            "chapter": int(item.get("chapter") or 0),
            "narration_anchor": " ".join(_text(item.get("situation")).split()[:12]),
        })
    return steps


def _check_engine(steps: list[dict], engine: dict | None, issues: list[dict]) -> None:
    """Check the story against the shape it declared, not against every shape ever observed.

    Without an engine the validator accepts the union of both reference videos, which means it
    cannot tell a story missing its false resolution from a story that never needed one. The
    engine turns that into a stated intent that can be wrong.
    """
    if not engine:
        return
    present = [step["role"] for step in steps]
    for role in engine.get("required", ()):
        if role not in present:
            issues.append(_issue(
                "ENGINE_MISSING_ROLE",
                f"{engine['name']} requires a {role} beat"))

    # Order is checked on MILESTONES only. Escalation and generalization repeat and run through
    # the whole story, so treating them as ordered positions asked a story to place its first
    # escalation after its mechanism — which no reference does and nothing requires. The engine's
    # claim is about the milestones the story passes through, not about the connective tissue
    # between them.
    named = [role for role in engine.get("sequence", ())
             if role in present and role not in _REPEATABLE]
    seen, position = [], -1
    for step in steps:
        if step["role"] not in named or step["role"] in seen:
            continue
        seen.append(step["role"])
        index = named.index(step["role"])
        if index < position:
            issues.append(_issue(
                "ENGINE_ORDER",
                f"{step['role']} appears after {named[position]}, but {engine['name']} runs "
                + " -> ".join(named),
                step["step_id"]))
            return
        position = index

    closing = engine.get("closing")
    if closing and steps and steps[-1]["role"] != closing:
        issues.append(_issue(
            "ENGINE_CLOSE",
            f"{engine['name']} closes on a {closing}, not a {steps[-1]['role']}",
            steps[-1]["step_id"]))


def _check_roles(steps: list[dict], issues: list[dict], engine: dict | None = None) -> None:
    counts: dict[str, int] = {}
    for step in steps:
        if step["role"] not in STEP_ROLES:
            issues.append(_issue(
                "UNKNOWN_ROLE",
                f"{step['role'] or '(blank)'} is not a causal-story role; expected one of "
                + ", ".join(STEP_ROLES),
                step["step_id"]))
            continue
        counts[step["role"]] = counts.get(step["role"], 0) + 1

    for role, count in counts.items():
        if count > 1 and role not in _REPEATABLE:
            issues.append(_issue("DUPLICATE_ROLE", f"{role} may appear only once, found {count}"))

    for required in (SETUP, MECHANISM, REVERSAL):
        if not counts.get(required):
            issues.append(_issue("MISSING_ROLE", f"a causal story requires a {required} step"))
    if not any(counts.get(role) for role in CLOSING_ROLES):
        issues.append(_issue(
            "MISSING_ROLE",
            "a causal story must close on a tool (hand the opening object back as a question) "
            "or a verdict (restate the opening claim now that it is proved)"))

    compounded = sum(s["role"] == REVERSAL and s.get("event_function") == "compounds_exploit"
                     for s in steps) if (engine or {}).get("compiled_compounding") else 0
    # A SPIRAL IS ONE SHAPE, NOT THE ONLY SHAPE. Two escalations is right where people keep
    # responding to an incentive -- tails are cut, then rats are farmed -- because each round of
    # exploitation invites the next. An ecological cascade does not spiral: the cats go, the
    # rabbits surge, the vegetation goes, and that is the whole mechanism running once. Demanding
    # a second escalation of removed_keystone asks for a beat the events do not contain.
    minimum = int((engine or {}).get("min_escalations") or MIN_ESCALATIONS)
    if counts.get(ESCALATION, 0) + compounded < minimum:
        issues.append(_issue(
            "THIN_CHAIN",
            f"found {counts.get(ESCALATION, 0)} escalation steps; this engine needs at least "
            f"{minimum} or it is a single cause-and-effect, not a spiral"))

    # Only for engines that HAVE a false resolution. accidental_invention requires a hinge and has
    # no false_resolution in its sequence at all -- its own comment says "the hinge here is the
    # anomaly rather than a broken promise, so a false resolution is optional: many of these
    # stories have no moment of apparent success to break". Firing unconditionally made that engine
    # impossible to satisfy for ANY input, and repair_chain never inserts a false resolution, so
    # nothing downstream could rescue it.
    # REQUIRED, not merely present in the sequence. removed_keystone can carry a false resolution
    # -- the target species really did respond at first -- but it does not require one, because
    # plenty of introductions never worked even briefly. Reading the sequence rather than the
    # requirement demanded a beat the engine calls optional, and refused a story for omitting it.
    engine_has_false_resolution = FALSE_RESOLUTION in ((engine or {}).get("required")
                                                       or (engine or {}).get("sequence") or ())
    if engine is not None and not engine_has_false_resolution:
        pass
    elif counts.get(HINGE) and not counts.get(FALSE_RESOLUTION):
        issues.append(_issue(
            "UNEARNED_HINGE",
            "a hinge only lands after a false resolution; state that the fix worked before "
            "breaking it"))


def _check_order(steps: list[dict], issues: list[dict]) -> None:
    by_role = {}
    for step in steps:
        by_role.setdefault(step["role"], []).append(step)

    if steps and steps[0]["role"] != SETUP:
        issues.append(_issue("BAD_OPENING", "the first step must be the setup", steps[0]["step_id"]))
    if steps and steps[-1]["role"] not in CLOSING_ROLES:
        issues.append(_issue(
            "BAD_CLOSE",
            "the last step must be a tool or a verdict, and must return to the opening",
            steps[-1]["step_id"]))

    def first(role):
        return by_role[role][0]["index"] if by_role.get(role) else None

    hinge, false_res = first(HINGE), first(FALSE_RESOLUTION)
    if hinge is not None and false_res is not None and hinge < false_res:
        issues.append(_issue("HINGE_BEFORE_RESOLUTION",
                             "the hinge breaks the false resolution, so it must follow it"))

    reversal = first(REVERSAL)
    if reversal is not None:
        late = [s for s in by_role.get(ESCALATION, []) if s["index"] > reversal]
        if late:
            issues.append(_issue(
                "ESCALATION_AFTER_REVERSAL",
                "the reversal is the end of the chain; escalations cannot follow it",
                late[0]["step_id"]))

    for step in by_role.get(GENERALIZATION, []):
        if reversal is not None and step["index"] < reversal:
            issues.append(_issue(
                "EARLY_GENERALIZATION",
                "generalize only after the reversal has landed; otherwise the pattern has not "
                "been earned yet",
                step["step_id"]))


def _check_chain(steps: list[dict], issues: list[dict]) -> None:
    """Every step but the setup must name the step it follows from, and the links must resolve.

    This is the check the positional arc could not express. A list of true facts about a topic
    has no `caused_by` edges to offer, so it fails here rather than at render time.
    """
    known = {step["step_id"]: step for step in steps}
    for step in steps:
        if step["role"] == SETUP:
            if step["caused_by"]:
                issues.append(_issue("CAUSED_SETUP",
                                     "the setup starts the chain and cannot be caused by a step",
                                     step["step_id"]))
            continue
        if not step["caused_by"]:
            issues.append(_issue(
                "ORPHAN_STEP",
                f"{step['role']} does not say what caused it; every step after the setup must "
                "name the step it follows from",
                step["step_id"]))
            continue
        parent = known.get(step["caused_by"])
        if parent is None:
            issues.append(_issue("DANGLING_CAUSE",
                                 f"caused_by {step['caused_by']!r} is not a step in this story",
                                 step["step_id"]))
        elif parent["index"] >= step["index"]:
            issues.append(_issue("BACKWARD_CAUSE",
                                 f"{step['step_id']} is caused by a step that comes after it",
                                 step["step_id"]))


def _check_chapters(steps: list[dict], issues: list[dict]) -> None:
    """The spoken chapter spine: contiguous, in order, and within the observed count.

    Each chapter becomes one audible "Step N" in the narration, which is the retention device the
    references use — a micro-reset that re-earns the viewer's attention. Chapters may hold several
    causal steps, but a step cannot sit outside one and the numbering cannot jump.
    """
    numbered = [step for step in steps if step["chapter"]]
    if not numbered:
        issues.append(_issue(
            "NO_CHAPTERS",
            "assign each step a chapter number; the spoken step spine is what the narration says "
            "out loud, and it is measured separately from the causal chain"))
        return
    unassigned = [step for step in steps if not step["chapter"]]
    if unassigned:
        issues.append(_issue("STEP_OUTSIDE_CHAPTER",
                             "every step belongs to a spoken chapter", unassigned[0]["step_id"]))

    chapters = [step["chapter"] for step in steps if step["chapter"]]
    distinct = sorted(set(chapters))
    if distinct != list(range(1, len(distinct) + 1)):
        issues.append(_issue("CHAPTER_GAP",
                             f"chapters must run 1..n without gaps, found {distinct}"))
    if chapters != sorted(chapters):
        issues.append(_issue("CHAPTER_OUT_OF_ORDER",
                             "steps must be listed in chapter order"))
    # Only police the spine when there IS one. A storyboard may carry compressed step
    # descriptions rather than verbatim narration, and demanding a spoken marker from those would
    # fail a perfectly good contract. When any marker is present the count must be right, which is
    # the case that matters: a run announced one, one, two, three, five, six, four, five and the
    # count-only check waved it through.
    announced = any(_opener_marker(step.get("situation")) for step in steps)
    opener = {}
    for index, step in enumerate(steps):
        opener.setdefault(step["chapter"], index)
    for chapter, index in sorted(opener.items()) if announced else ():
        if not chapter:
            continue
        spoken = _opener_marker(steps[index].get("situation"))
        if not spoken:
            issues.append(_issue("CHAPTER_NOT_ANNOUNCED",
                                 f"chapter {chapter} never says its number out loud",
                                 steps[index]["step_id"]))
        elif _marker_number(spoken.group(0)) != chapter:
            issues.append(_issue(
                "CHAPTER_MISNUMBERED",
                f"chapter {chapter} announces itself as {spoken.group(0).strip()!r}; the spoken "
                "spine is a count and a wrong number reads as the story restarting",
                steps[index]["step_id"]))

    if not MIN_CHAPTERS <= len(distinct) <= MAX_CHAPTERS:
        issues.append(_issue(
            "CHAPTER_COUNT",
            f"{len(distinct)} spoken chapters against a reference band of "
            f"{MIN_CHAPTERS}-{MAX_CHAPTERS}"))


def _opener_marker(text: str):
    """The chapter marker, which on the first scene may follow the spoken hook.

    _MARKER is anchored to position zero, but the shape finalize_narration deliberately writes puts
    the promise sentence and the format tag AHEAD of the number on the scene that opens the video:
    "both reference videos open on a promise sentence and say the number second". Matching only at
    position zero therefore rejected the contract's own output and demanded the numeral be the
    first thing the viewer hears -- the exact failure finalize_narration exists to prevent, arriving
    from the validator instead of the writer.

    Bounded to the first three sentences because that is precisely what may legally precede it: the
    hook and the format tag. A marker any deeper is not announcing a chapter, it is buried in one.
    """
    for part in re.split(r"(?<=[.!?])\s+", _text(text))[:3]:
        found = _MARKER.match(part)
        if found:
            return found
    return None


def _check_timing(steps: list[dict], runtime_sec: float, issues: list[dict],
                  engine: dict | None = None) -> None:
    if runtime_sec <= 0:
        issues.append(_issue("NO_RUNTIME", "runtime_sec is required to place the mechanism"))
        return
    ordered = [s["start_sec"] for s in steps]
    if any(b < a for a, b in zip(ordered, ordered[1:])):
        issues.append(_issue("UNORDERED_TIMELINE", "step start_sec values must increase"))

    mechanism = next((s for s in steps if s["role"] == MECHANISM), None)
    if mechanism is None:
        return
    # The deadline belongs to the engine. Stories built on the reference videos state their
    # principle early and demonstrate it; a reveal-structured story cannot, because the principle
    # IS the ending. Without an engine the measured default applies.
    pct = MECHANISM_DEADLINE_PCT
    if engine:
        import story_engines
        pct = story_engines.mechanism_deadline_pct(engine, MECHANISM_DEADLINE_PCT)
    # A short telling reaches its rule later as a FRACTION, because the setup it must lay first does
    # not shrink with the runtime. The reference short states its principle at 30.8% and is right to
    # -- measured, not conceded. Engines that already declare a later deadline (the reveal-structured
    # ones, at 60%) keep theirs; this raises a floor, it never lowers a ceiling.
    if is_short_form(runtime_sec):
        pct = max(pct, SHORT_FORM_MECHANISM_PCT)
    deadline = runtime_sec * pct
    if mechanism["start_sec"] > deadline:
        issues.append(_issue(
            "LATE_MECHANISM",
            f"the mechanism lands at {mechanism['start_sec']:.0f}s, past the "
            f"{deadline:.0f}s mark ({pct:.0%} of runtime); state the "
            "principle early and spend the rest of the video earning it",
            mechanism["step_id"]))


def _check_hook(hook: dict, steps: list[dict], issues: list[dict],
                short_form: bool = False) -> None:
    line = _text(hook.get("line"))
    if not line:
        issues.append(_issue("NO_HOOK", "a causal story opens with one hook sentence"))
        return
    if _words(line) > MAX_HOOK_WORDS:
        issues.append(_issue(
            "LONG_HOOK",
            f"the hook is {_words(line)} words against a {MAX_HOOK_WORDS}-word budget; it "
            "promises the shape of the story, it does not summarize it"))
    # One sentence at documentary length, two when the format is short. The reference short opens
    # "The government paid people to kill cobras. So people started making cobras." -- the second
    # sentence IS the reversal, and collapsing it into one loses the beat the hook exists to land.
    max_sentences = SHORT_FORM_MAX_HOOK_SENTENCES if short_form else 1
    sentences = len([part for part in re.split(r"[.!?]+", line) if part.strip()])
    if sentences > max_sentences:
        issues.append(_issue(
            "MULTI_SENTENCE_HOOK",
            f"the hook is {sentences} sentences against a {max_sentences}-sentence budget"))

    withheld = _text(hook.get("withheld_subject"))
    if not withheld:
        return
    # The curiosity-gap variant: the hook promises a reversal about "a problem", and the concrete
    # noun arrives seconds later. If the hook already says "cobras" there is nothing to stay for.
    if re.search(rf"\b{re.escape(withheld.lower())}", line.lower()):
        issues.append(_issue(
            "SUBJECT_NOT_WITHHELD",
            f"the hook names {withheld!r}, so the curiosity gap it declares is not open"))
    elif not any(re.search(rf"\b{re.escape(withheld.lower())}", s["situation"].lower())
                 for s in steps):
        issues.append(_issue(
            "SUBJECT_NEVER_PAID_OFF",
            f"the hook withholds {withheld!r} but no step ever names it"))


def _check_reversal(payload: dict, steps: list[dict], issues: list[dict]) -> None:
    reversal = next((s for s in steps if s["role"] == REVERSAL), None)
    if reversal is None:
        return
    start_state = _text(payload.get("start_state"))
    end_state = _text(reversal["situation"])
    if not start_state:
        issues.append(_issue(
            "NO_START_STATE",
            "declare start_state so the reversal can be shown to be worse than the beginning"))
    elif start_state.lower() == end_state.lower():
        issues.append(_issue("NULL_REVERSAL",
                             "the end state is identical to the start state; nothing reversed",
                             reversal["step_id"]))


def _check_hinge(steps: list[dict], issues: list[dict]) -> None:
    """What a hinge is, expressed as checks rather than as advice.

    A hinge asserts that a stated success is not real. Both references are flat statements —
    "Except the problem is not solved." and "The system works perfectly until the rains stop." A
    live run instead labelled "So which drained it faster, hotter summers or the missing rivers?"
    as its hinge: that poses a choice, it breaks nothing, and the story carried on unturned. A
    question and an empty signpost are both mechanically detectable, so neither needs a judge.
    """
    for step in steps:
        if step["role"] != HINGE:
            continue
        turn = _MARKER.sub("", step["situation"]).strip()
        if turn.endswith("?"):
            issues.append(_issue(
                "HINGE_IS_A_QUESTION",
                "the hinge asks a question instead of breaking the false resolution; it must "
                "assert that the apparent success is not real",
                step["step_id"]))
        elif turn and len([word for word in re.findall(r"[a-z']+", turn.lower())
                           if word not in _SIGNPOST_WORDS]) < 2:
            issues.append(_issue(
                "HINGE_IS_A_SIGNPOST",
                f"{turn!r} announces a turn without making one; the hinge is the turn itself",
                step["step_id"]))
        # The spoken chapter marker is a structural device, not part of the turn, so it does not
        # spend the hinge's budget. A hinge that opens a chapter would otherwise be penalised two
        # words for a prefix the format itself requires.
        turn = _MARKER.sub("", step["situation"]).strip()
        if _words(turn) > MAX_HINGE_WORDS:
            issues.append(_issue(
                "SOFT_HINGE",
                f"the hinge is {_words(turn)} words; it lands in "
                f"{MAX_HINGE_WORDS} or fewer or it is not a turn",
                step["step_id"]))


def _check_parallel_cases(payload: dict, steps: list[dict], issues: list[dict],
                          short_form: bool = False) -> None:
    cases = [case for case in (payload.get("parallel_cases") or []) if isinstance(case, dict)]
    has_generalization = any(step["role"] == GENERALIZATION for step in steps)
    if not has_generalization:
        return
    required_cases = SHORT_FORM_MIN_PARALLEL_CASES if short_form else MIN_PARALLEL_CASES
    if len(cases) < required_cases:
        issues.append(_issue(
            "THIN_GENERALIZATION",
            f"a generalization step needs at least {required_cases} parallel cases to show "
            f"a pattern rather than a coincidence; found {len(cases)}"))
    for index, case in enumerate(cases):
        missing = [key for key in ("domain", "problem", "solution", "result")
                   if not _text(case.get(key))]
        if missing:
            issues.append(_issue(
                "UNPARALLEL_CASE",
                f"case {index + 1} is missing {', '.join(missing)}; the cases must be "
                "structurally identical so the repetition itself carries the argument"))

    # A parallel case belongs in the generalization, and NOWHERE ELSE. A measured draft put the
    # Hanoi rat bounty in an escalation beat, so the video left Delhi for Vietnam before Delhi's
    # own story had resolved -- and every structural check passed, because a beat labelled
    # escalation was present and in order. The engine's escalation is the SAME situation getting
    # worse; a second country is a comparison, and a comparison offered before the first story
    # lands reads as the story changing subject.
    #
    # Matched on the case's own domain nouns rather than a keyword list, so it costs nothing and
    # travels to any topic. Short domain words are dropped: "software" or "public health" identify
    # a case, "the" and "in" identify nothing.
    # Match only on words that DISTINGUISH the case from this story. A domain label like "colonial
    # public health (Hanoi)" shares "colonial" with a story about colonial officials in Delhi, and
    # matching that flagged the setup beat of a draft with nothing wrong with it. A word the story
    # already uses about itself is not evidence that a comparison has been imported.
    own_words = set()
    for step in steps:
        if step["role"] in (SETUP, INTERVENTION, FALSE_RESOLUTION):
            own_words |= {word for word in re.findall(r"[a-z]+", step["situation"].lower())
                          if len(word) > 4}

    for step in steps:
        if step["role"] == GENERALIZATION:
            continue
        situation = step["situation"].casefold()
        for index, case in enumerate(cases):
            domain_words = [word for word in re.findall(r"[a-z]+", _text(case.get("domain")).lower())
                            if len(word) > 4 and word not in _STOPWORDS and word not in own_words]
            hit = next((word for word in domain_words
                        if re.search(rf"\b{re.escape(word)}", situation)), "")
            if hit:
                issues.append(_issue(
                    "PARALLEL_CASE_OUT_OF_PLACE",
                    f"the {step['role']} beat names {hit!r}, which belongs to parallel case "
                    f"{index + 1} ({_text(case.get('domain'))}); a comparison offered before the "
                    "story resolves reads as the story changing subject. Move it to the "
                    "generalization",
                    step["step_id"]))


def _check_close(payload: dict, steps: list[dict], issues: list[dict],
                 short_form: bool = False) -> None:
    opening_object = _text(payload.get("opening_object"))
    if not opening_object:
        issues.append(_issue("NO_OPENING_OBJECT",
                             "declare opening_object so the close can return to it"))
        return
    close = next((s for s in reversed(steps) if s["role"] in CLOSING_ROLES), None)
    if close is None:
        return
    # Any content word is enough of a callback; requiring the exact phrase would fail a close
    # that says "the cobra farms" against an opening object of "cobra farms everywhere".
    content = [word for word in re.findall(r"[a-z]+", opening_object.lower())
               if word not in _STOPWORDS]
    haystack = close["situation"].lower()

    def _mentions(words: list[str]) -> bool:
        """Does the close name any of these, allowing an English plural to differ?

        "cobras" in the setup against "cobra farms" in the close is the same subject, and an exact
        word-boundary match called it a missing callback. Trimming a trailing s off both sides is
        the whole of the morphology this needs -- these are nouns from one sentence of narration,
        not a stemming problem.
        """
        for word in words:
            stem = word[:-1] if len(word) > 4 and word.endswith("s") else word
            if re.search(rf"\b{re.escape(stem)}", haystack):
                return True
        return False
    # At short length the close may return to the PROBLEM instead of the opening object. The
    # reference short ends "Ask: where are the cobra farms?" -- it never hands the coin back, and it
    # is the stronger close for it, because a minute has no room to re-establish an object before
    # reusing it. Returning to the setup's own subject is the same move made on what the story
    # actually spent its time on. A close that returns to NEITHER still fails.
    targets = [content]
    if short_form and steps:
        setup = next((step for step in steps if step["role"] == SETUP), steps[0])
        targets.append([word for word in re.findall(r"[a-z]+", setup["situation"].lower())
                        if word not in _STOPWORDS and len(word) > 3])
    hit = any(words and _mentions(words) for words in targets)
    if content and not hit:
        issues.append(_issue(
            "NO_CALLBACK",
            f"the closing step never returns to {opening_object!r}"
            + (" nor to the situation the story opened on" if short_form else
               "; both reference closes come back to the thing the story opened on"),
            close["step_id"]))


def validate_causal_story(payload: dict, engine: dict | None = None) -> dict:
    """Check a declared causal story. Provider-free, so it costs nothing to fail.

    `engine` is optional: without it the generic contract applies, which is what the reference
    fixtures and every earlier caller expect.
    """
    payload = payload if isinstance(payload, dict) else {}
    steps = _normalize_steps(payload.get("steps"))
    issues: list[dict] = []

    if not steps:
        issues.append(_issue("NO_STEPS", "a causal story requires at least one step"))
        return {"schema_version": SCHEMA_VERSION, "passed": False, "errors": issues,
                "steps": steps}

    hook = payload.get("hook") if isinstance(payload.get("hook"), dict) else {}
    _check_roles(steps, issues, engine)
    _check_order(steps, issues)
    _check_engine(steps, engine, issues)
    _check_chain(steps, issues)
    _check_chapters(steps, issues)
    _check_timing(steps, float(payload.get("runtime_sec") or 0.0), issues, engine)
    short_form = is_short_form(float(payload.get("runtime_sec") or 0.0))
    _check_hook(hook, steps, issues, short_form)
    _check_hinge(steps, issues)
    _check_reversal(payload, steps, issues)
    _check_parallel_cases(payload, steps, issues, short_form)
    _check_close(payload, steps, issues, short_form)

    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not issues,
        "errors": issues,
        "steps": steps,
        "chain": [
            {"step_id": step["step_id"], "role": step["role"], "caused_by": step["caused_by"],
             "chapter": step["chapter"]}
            for step in steps
        ],
        "chapter_count": len({step["chapter"] for step in steps if step["chapter"]}),
        "engine": (engine or {}).get("name", ""),
    }


def story_direction(question: str, operator_direction: str = "") -> str:
    """The causal-chain contract, written for the existing script call.

    Replaces the "reveal an answer every so often" direction. The behavioural difference is the
    last line of each paragraph: state the principle once, then spend the video demonstrating it.
    """
    base = f"""
CAUSAL STORY STRUCTURE — REQUIRED FOR THIS VIDEO:
Tell one causal chain about: {question}
Open with ONE sentence, at most {MAX_HOOK_WORDS} words, that promises how the situation inverts.
Name the actor and the reversal in plain, concrete words, and let one named actor be the subject of
both halves: they do the sensible thing AND they cause the disaster. Do not greet the viewer or
announce the video.

Then walk the chain in {MIN_CHAPTERS}-{MAX_CHAPTERS} chapters. They are structural: they set word
budgets and group the storyboard, and they are NOT announced in the narration — never write "Step
one", "Part two", "First," or any other spoken signpost. A chapter may contain several causal steps; give
each step a chapter number and do not make the chapters equal in length. Every step after the
first must happen BECAUSE of a named earlier step — set caused_by to that step's id. If a step
would still make sense in a different position, it is a fact, not a step, and does not belong.

Required spine: setup (the world and the problem) -> intervention (the fix someone applies) ->
false_resolution (state plainly that it worked) -> hinge (ONE sentence, at most {MAX_HINGE_WORDS}
words, that breaks it) -> mechanism (name the principle, in the first {MECHANISM_DEADLINE_PCT:.0%}
of runtime) -> at least {MIN_ESCALATIONS} escalation steps, each caused by the previous one ->
reversal (the end state, explicitly worse than start_state) -> optional generalization ->
tool (hand the viewer the opening object back as a question they can use).

State the mechanism ONCE, early, and then earn it. Do not re-explain it at intervals and do not
pause the story to deliver an answer. The remaining runtime is demonstration.

If you include a generalization step, give at least {MIN_PARALLEL_CASES} parallel cases from
different domains, each with the same four parts (domain, problem, solution, result) in the same
order, so the repetition itself carries the argument.

Vary sentence length deliberately. After a long sentence that builds, land a short one of five
words or fewer. The short fragments are what a viewer remembers.
""".strip()
    extra = _text(operator_direction)
    return base if not extra else f"{base}\n\nOPERATOR DIRECTION:\n{extra}"


# ---------------------------------------------------------------------------
# Grading against the reference transcripts
#
# Bands measured from the reference videos rather than chosen. Fitted originally to two: 184 and
# 179 words per minute; hooks of 15 and 11 words; median sentence 6 and 10 words; short landings
# 40% and 18%; 6 and 4 spoken step markers. Each band is the observed spread widened to the nearest
# round number, so every reference sits inside it and a script that drifts outside is measurably
# unlike them.
#
# The corpus then grew to five and corrected one of them, which is what a corpus is for. Widening
# to round numbers absorbed the new references on every band but ONE: the Pompeii video opens on a
# four-word hook ("What happened at Pompeii?"), under a floor of 5 fitted to hooks of 15 and 11.
# The floor is now 4 because a real reference measured 4 — a band that rejects the corpus it was
# derived from is measuring the wrong thing. Observed across five: hooks 4-15, wpm 165.3-193.7,
# median sentence 6-11, short landings 18.2%-46.0%, step markers 4-6, loudness -17.6 to -17.1 dB.
# ---------------------------------------------------------------------------

REFERENCE_BANDS = {
    "words_per_minute":   (165.0, 200.0),
    "hook_words":         (4, MAX_HOOK_WORDS),
    "mechanism_pct":      (0.0, MECHANISM_DEADLINE_PCT),
    "median_sentence":    (5, 12),
    "short_landing_pct":  (0.15, 0.50),
    "step_markers":       (4, 8),
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")
_STEP_MARKER = re.compile(r"\bstep (one|two|three|four|five|six|seven|eight|\d+)\b", re.I)


def _band(name: str, value: float) -> dict:
    low, high = REFERENCE_BANDS[name]
    return {"metric": name, "value": round(float(value), 3),
            "band": [low, high], "in_band": low <= value <= high}


def measure_narration(text: str, runtime_sec: float, hook: str = "") -> dict:
    """Measure the prose properties the references share. Works on a transcript or a script.

    `hook` is separate because the two inputs differ in shape. In a transcript the hook IS the
    first sentence, so falling back to it is right. A generated script carries the hook in its own
    field and opens its narration on the first chapter marker, so measuring sentence one scored a
    12-word hook as two words — the sentence it read was "Step one."
    """
    text = _text(text)
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences or runtime_sec <= 0:
        return {"measured": False, "metrics": []}
    lengths = sorted(len(s.split()) for s in sentences)
    short = [s for s in sentences if len(s.split()) <= 5]
    return {
        "measured": True,
        "word_count": len(text.split()),
        "sentence_count": len(sentences),
        "metrics": [
            _band("words_per_minute", len(text.split()) / runtime_sec * 60),
            _band("hook_words", len(_text(hook).split()) if _text(hook)
                  else len(sentences[0].split())),
            _band("median_sentence", lengths[len(lengths) // 2]),
            _band("short_landing_pct", len(short) / len(sentences)),
            _band("step_markers", len(_STEP_MARKER.findall(text))),
        ],
    }


def grade(payload: dict, narration: str = "") -> dict:
    """Score a candidate story the way the reference videos score.

    Structure and prose are graded separately on purpose. The contract can guarantee the
    structure — that is what `validate_causal_story` checks and what the illustrated lane
    consumes. It cannot guarantee the prose: word rate, sentence rhythm and the short landings
    are a generation target the script model has to hit, and this is the ruler for it.
    """
    payload = payload if isinstance(payload, dict) else {}
    structure = validate_causal_story(payload)
    runtime = float(payload.get("runtime_sec") or 0.0)

    mechanism = next((s for s in structure["steps"] if s["role"] == MECHANISM), None)
    structural_metrics = []
    if mechanism and runtime > 0:
        structural_metrics.append(_band("mechanism_pct", mechanism["start_sec"] / runtime))

    if not narration:
        # Fall back to the declared step lines so a contract with no script attached still gets
        # a structural read. Flagged, because a skeleton is not prose and must not score as if
        # it were: the step lines are one sentence each by construction.
        narration = " ".join(step["situation"] for step in structure["steps"])
        prose_is_skeleton = True
    else:
        prose_is_skeleton = False

    prose = measure_narration(narration, runtime,
                              hook=_text((payload.get("hook") or {}).get("line")
                                         if isinstance(payload.get("hook"), dict) else ""))
    metrics = structural_metrics + (prose.get("metrics") or [])
    passing = [m for m in metrics if m["in_band"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "structure_passed": structure["passed"],
        "structure_errors": structure["errors"],
        "prose_is_skeleton": prose_is_skeleton,
        "metrics": metrics,
        "score": round(100.0 * len(passing) / len(metrics), 1) if metrics else 0.0,
        "out_of_band": [m for m in metrics if not m["in_band"]],
    }


# ---------------------------------------------------------------------------
# Deterministic repair
#
# The first real run came back with setup x2, false_resolution x3, verdict x2 and escalations
# sequenced after the reversal. Those are label mistakes on a beat order that was otherwise sound,
# and every one of them is mechanically decidable — so they are repaired here rather than paid for
# again. Repair only ever RELABELS; it never reorders beats, because narration order is the one
# thing the planner genuinely owns and a reordering would desynchronise it from the script.
#
# Every change is returned so the caller can log it. A silent repair would hide a planner that has
# stopped complying, which is the thing worth knowing.
# ---------------------------------------------------------------------------

_SINGLETON_ROLES = (SETUP, INTERVENTION, FALSE_RESOLUTION, HINGE, MECHANISM, REVERSAL)


def repair_chain(steps: list[dict], engine: dict | None = None) -> tuple[list[dict], list[str]]:
    """Relabel a planned beat order into a legal chain. Returns (steps, changes).

    With an engine, the close is repaired to THAT engine's closing role rather than the generic
    verdict — otherwise repairing a backfiring-solution story would hand it an indictment ending
    and the engine check would then reject what repair had just produced.
    """
    steps = [dict(step) for step in steps]
    changes: list[str] = []
    if not steps:
        return steps, changes

    def note(index, field, old, new):
        if old != new:
            changes.append(f"beat {index + 1}: {field} {old!r} -> {new!r}")

    # 1. Unknown roles become escalations rather than failing the whole plan.
    for index, step in enumerate(steps):
        if step.get("role") not in STEP_ROLES:
            note(index, "role", step.get("role"), ESCALATION)
            step["role"] = ESCALATION

    # 2. The close is whatever the last beat is; an earlier tool/verdict is a mislabelled beat.
    closing = (engine or {}).get("closing") or VERDICT
    if steps[-1]["role"] not in CLOSING_ROLES:
        note(len(steps) - 1, "role", steps[-1]["role"], closing)
        steps[-1]["role"] = closing
    elif engine and steps[-1]["role"] != closing:
        note(len(steps) - 1, "role", steps[-1]["role"], closing)
        steps[-1]["role"] = closing
    # Demote a stray closing beat to a role the ENGINE actually has. Generalization was the
    # unconditional target, and for an engine whose sequence has no generalization that manufactures
    # a beat which can never pass: a generalization needs two parallel cases to show a pattern, and
    # accumulating_indictment fetches none on purpose — "the counterfactual carries the argument,
    # which is why the close is a verdict". A render died on THIN_GENERALIZATION for a case the
    # repair itself had invented. Power reversal has no generalization either, so this hit both of
    # the engines the corpus backs best.
    sequence = (engine or {}).get("sequence") or ()
    demoted = GENERALIZATION if GENERALIZATION in sequence else ESCALATION
    for index, step in enumerate(steps[:-1]):
        if step["role"] in CLOSING_ROLES:
            note(index, "role", step["role"], demoted)
            step["role"] = demoted

    # 3. The first beat is the setup; a later one is a beat that continues the story.
    if steps[0]["role"] != SETUP:
        note(0, "role", steps[0]["role"], SETUP)
        steps[0]["role"] = SETUP
    for index, step in enumerate(steps[1:], start=1):
        if step["role"] == SETUP:
            note(index, "role", SETUP, ESCALATION)
            step["role"] = ESCALATION

    # 4. Remaining singletons: keep the earliest, demote the rest.
    for role in (INTERVENTION, FALSE_RESOLUTION, HINGE, MECHANISM):
        seen = False
        for index, step in enumerate(steps):
            if step["role"] != role:
                continue
            if seen:
                note(index, "role", role, ESCALATION)
                step["role"] = ESCALATION
            seen = True

    # 5. The reversal ends the chain, so it is the beat just before the trailing
    #    generalization/close block — wherever the planner happened to put the label.
    tail = len(steps) - 1
    while tail > 0 and steps[tail]["role"] in (GENERALIZATION,) + CLOSING_ROLES:
        tail -= 1
    for index, step in enumerate(steps):
        if step["role"] == REVERSAL and index != tail:
            note(index, "role", REVERSAL, ESCALATION)
            step["role"] = ESCALATION
    if tail > 0 and steps[tail]["role"] != REVERSAL:
        note(tail, "role", steps[tail]["role"], REVERSAL)
        steps[tail]["role"] = REVERSAL
    # A generalization can only be earned after the reversal has landed, so one sitting before it
    # is an escalation that was mislabelled — not a pattern the story has yet shown.
    for index, step in enumerate(steps[:tail]):
        if step["role"] == GENERALIZATION:
            note(index, "role", GENERALIZATION, ESCALATION)
            step["role"] = ESCALATION

    # 5b. A hinge before the false resolution has nothing to break yet. Demote it and take the
    #     beat immediately after the false resolution instead — that is where the turn lands.
    positions = {step["role"]: index for index, step in enumerate(steps)}
    hinge_at, resolution_at = positions.get(HINGE), positions.get(FALSE_RESOLUTION)
    if hinge_at is not None and resolution_at is not None and hinge_at < resolution_at:
        note(hinge_at, "role", HINGE, ESCALATION)
        steps[hinge_at]["role"] = ESCALATION
        candidate = resolution_at + 1
        if candidate < len(steps) and steps[candidate]["role"] == ESCALATION:
            note(candidate, "role", ESCALATION, HINGE)
            steps[candidate]["role"] = HINGE

    # 6. Causal edges: the setup starts the chain, everything else follows something earlier.
    ids = [step.get("step_id") for step in steps]
    known = set(ids)
    if steps[0].get("caused_by"):
        note(0, "caused_by", steps[0]["caused_by"], "")
        steps[0]["caused_by"] = ""
    for index, step in enumerate(steps[1:], start=1):
        parent = step.get("caused_by") or ""
        resolves = parent in known and ids.index(parent) < index
        if not resolves:
            note(index, "caused_by", parent, ids[index - 1])
            step["caused_by"] = ids[index - 1]

    # 7. Chapters: contiguous from 1, and inside the observed band. Beats keep their grouping
    #    wherever the planner supplied one; otherwise they are split evenly.
    raw = [step.get("chapter") or 0 for step in steps]
    if not all(raw) or sorted(raw) != raw:
        span = max(1, round(len(steps) / MIN_CHAPTERS))
        for index, step in enumerate(steps):
            step["chapter"] = min(MAX_CHAPTERS, index // span + 1)
        changes.append(f"chapters renumbered into {len({s['chapter'] for s in steps})} groups")
    else:
        remap = {old: new for new, old in enumerate(sorted(set(raw)), start=1)}
        if remap != {value: value for value in remap}:
            changes.append(f"chapters renumbered {sorted(set(raw))} -> {sorted(remap.values())}")
        for step in steps:
            step["chapter"] = remap[step["chapter"]]
    return steps, changes


# ---------------------------------------------------------------------------
# Deterministic narration finishing
#
# Two properties kept failing across live runs even with explicit prompt rules: the spoken chapter
# marker (4 of 8 chapters announced, then 3) and the hinge word cap (24 words, then 22). Both are
# mechanical, and both were being asked of a prompt that simultaneously tells the writer every
# narration is about the same length — a contradiction the systemic instruction wins.
#
# So they are done here instead. Neither invents or deletes content: the marker is a prefix, and
# hinge overflow moves into the next scene rather than being dropped.
# ---------------------------------------------------------------------------



def _marker_number(marker: str) -> int:
    """The number a spoken marker names, in words or digits.

    "Step 1" and "Step one" are the same announcement; comparing the rendered word form rejected
    the numeral, which is a legitimate way for a narrator to say it.
    """
    token = re.sub(r"^\s*step\s+", "", marker.strip(), flags=re.I).strip(".:,;—- ").casefold()
    if token.isdigit():
        return int(token)
    return _CHAPTER_WORDS.index(token) + 1 if token in _CHAPTER_WORDS else -1


def _spoken(chapter: int) -> str:
    name = _CHAPTER_WORDS[chapter - 1] if 1 <= chapter <= len(_CHAPTER_WORDS) else str(chapter)
    return f"Step {name}."


_SIGNPOST_WORDS = {
    "a", "an", "the", "is", "was", "are", "were", "be", "been", "here", "there", "this", "that",
    "these", "those", "it", "its", "and", "but", "so", "then", "now", "of", "to", "in", "on",
    "part", "thing", "point", "what", "why", "how", "watch", "look", "see", "comes", "next",
}


def _turn_sentence(sentences: list[str]) -> int:
    """Which sentence is the actual turn.

    Taking the first one that fits the cap kept "Here is the strange part." and moved the real
    reversal — "Both rivers still flow today" — out of the hinge, which is a worse hinge than the
    one it replaced. Content words separate a signpost from a statement without needing to parse
    the sentence: the signpost is almost entirely function words.
    """
    best, best_score = -1, -1
    for index, sentence in enumerate(sentences):
        if _words(sentence) > MAX_HINGE_WORDS:
            continue
        score = len([word for word in re.findall(r"[a-z']+", sentence.lower())
                     if word not in _SIGNPOST_WORDS])
        if score > best_score:
            best, best_score = index, score
    return best


def speaks_chapter_markers() -> bool:
    """SPOKEN_CHAPTER_MARKERS=1 restores the spoken "Step one." openers. Default OFF.

    The corpus references DO say their numbers, and that is why this was built: all six open on a
    hook and then announce the chapter. Copying it was defensible and it is still available, which
    is why this is a flag and not a deletion.

    It is off because the device costs more than it returns HERE. Three things went wrong that the
    references never had to deal with. The marker became the scene's `anchor_phrase` -- the first
    five words of the opening sentence, which on a chapter opener IS the marker -- so it flowed
    into the evidence state and then into the image-to-video prompt: two renders animated the word
    "Step", at $1.12 of Kling v3 pro. It also lands in the same narration the fidelity boundary
    measures against a factual event, where a structural numeral has nothing to support it. And a
    90-second story that stops four times to count is not the 64-second reference's shape, it is a
    lecture wearing its outline on the outside.

    Chapters themselves are untouched: they still carry grouping, word budgets and the storyboard
    payload. Only the spoken numeral goes.
    """
    import os
    return os.environ.get("SPOKEN_CHAPTER_MARKERS", "0") == "1"


def finalize_narration(scenes: list[dict], hook: str = "", format_tag: str = "") -> list[str]:
    """Guarantee the spoken hook, the chapter spine, and the hinge cap. Returns what it changed.

    THE HOOK IS SPOKEN. `script["hook"]` used to reach only the YouTube description, so the video's
    first words were the literal numeral "Step one." Both reference videos open on a promise
    sentence and say the number second — the cobra reference reserves 0-5.0s for it, the famine
    reference 0-3.0s — and a viewer who hears "Step one" before knowing the subject has been given
    a chapter marker instead of a reason to stay.

    Order matters and is the opposite of the first version: markers are settled FIRST, then the
    hinge is measured on prose with its marker held aside. Trimming first let the trim select the
    marker itself as the turn, which reduced the most important sentence in one script to the two
    words "Step one."

    IDEMPOTENT. Running it twice must produce the same text. The first version stripped only the
    chapter marker before rebuilding, so a second pass saw the hook still sitting in the narration,
    treated it as body, and prepended a second copy of hook + tag + marker. Nothing in the pipeline
    calls this twice today, but a retry or a second normalisation pass would have silently doubled
    the opening.

    This edits narration, so it is deliberately conservative: it normalises a marker and removes a
    duplicate. It does NOT trim an over-long hinge — an earlier version did, and its heuristic
    deleted the reversal: given "Here is the strange part. The plan failed completely. Important
    evidence was discovered later." it kept the last sentence and threw away the turn. Length is a
    judgement about writing, so SOFT_HINGE reports it and the run fails honestly instead of the
    code quietly removing the most important sentence in the video.
    """
    changes: list[str] = []
    if not scenes:
        return changes

    def _sentence(value: str) -> str:
        # Each lead element becomes its own spoken sentence, so it is capitalised and stopped. The
        # format tag is stored lowercase ("explained like you are five") and would otherwise be
        # read mid-sentence.
        value = _text(value).rstrip(".")
        return (value[0].upper() + value[1:] + ".") if value else ""

    def _strip_lead(narration: str) -> str:
        """Remove a previously-applied hook, tag and marker so the rebuild is idempotent.

        ORDER-INDEPENDENT, and it has to be. The first version stripped hook, then tag, then
        marker, each only at position zero -- so it handled the lead it writes and nothing else.
        When the planner opened a scene with its own "Step one." the hook no longer sat at
        position zero, the strip did nothing, and the rebuild prepended hook + tag in front of a
        body that still contained them. The video then opened on the numeral this whole function
        exists to prevent, with the promise sentence buried and said twice:

            "Step one. An official pays to erase a menace... Explained like you are five.
             Step one. A coin lands. The cobras stay."

        Looping until nothing more can be removed accepts the lead pieces in any order and any
        number, which is what a planner that writes its own markers actually produces.
        """
        body = narration
        parts = [part for part in (_sentence(hook), _sentence(format_tag)) if part]
        removing = True
        while removing:
            removing = False
            without_marker = _MARKER.sub("", body).strip()
            if without_marker != body:
                body, removing = without_marker, True
            for part in parts:
                if body.casefold().startswith(part.casefold()):
                    body, removing = body[len(part):].strip(), True
        return body

    # 1. The spoken spine. Each chapter's first scene announces that chapter's number; a marker
    #    anywhere else is a duplicate. Normalising rather than adding-when-absent is the fix for
    #    a run whose chapters read one, one, two, three, five, six, four, five: the model had
    #    written its own numbers and add-when-absent left every one of them in place.
    opener = {}
    for index, scene in enumerate(scenes):
        opener.setdefault(scene.get("chapter") or 0, index)
    for index, scene in enumerate(scenes):
        chapter = scene.get("chapter") or 0
        narration = _text(scene.get("narration"))
        if not narration:
            continue
        # Strip any lead this function applied on a previous pass, not just the marker. Stripping
        # the marker alone left the hook in the body and a second pass prepended another copy.
        body = _strip_lead(narration)
        if opener.get(chapter) == index and chapter:
            # The very first scene carries the spoken hook ahead of its marker, which is the
            # reference shape: promise, format tag, then the number. Every later chapter opener
            # gets the marker alone. With markers off, the hook still leads and the number does not
            # follow it -- and a marker the planner wrote itself is stripped by _strip_lead above,
            # so turning the flag off removes them wherever they came from.
            lead = ""
            if index == 0:
                lead = " ".join(p for p in (_sentence(hook), _sentence(format_tag)) if p).strip()
            marker = _spoken(chapter) if speaks_chapter_markers() else ""
            wanted = " ".join(part for part in (lead, marker, body) if part).strip()
            if wanted != narration:
                scene["narration"] = wanted
                changes.append(
                    (f"chapter {chapter}: marker set to {_spoken(chapter)!r}" if marker
                     else f"chapter {chapter}: opener left unmarked (spoken markers off)")
                    + (" after the spoken hook" if lead else ""))
        elif body != narration:
            scene["narration"] = body
            changes.append(f"scene {index + 1}: duplicate marker removed mid-chapter")

    # 2. The hinge is REPORTED, never trimmed.
    #
    # An earlier version selected the "turn" sentence by content-word count and dropped the rest.
    # On "Here is the strange part. The plan failed completely. Important evidence was discovered
    # later." it kept the last sentence — 4 content words — and deleted "The plan failed
    # completely", which IS the turn. It removed the most important sentence in the video and
    # reported success.
    #
    # There is no reliable way to identify a story's turn by counting words, and a wrong guess here
    # is unrecoverable because the narration is gone. Length is a judgement about writing, so
    # SOFT_HINGE says so and the run fails before any spend. Free, honest, and reversible.
    for index, scene in enumerate(scenes):
        if _text(scene.get("role") or scene.get("causal_role")).lower() != HINGE:
            continue
        body = _MARKER.sub("", _text(scene.get("narration"))).strip()
        if _words(body) > MAX_HINGE_WORDS:
            changes.append(
                f"scene {index + 1}: hinge is {_words(body)} words and was left intact; "
                "SOFT_HINGE will report it")
    return changes
