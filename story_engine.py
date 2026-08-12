"""Named story formats + deterministic structure gates for narration scripts.

Why this exists: the long-form prompt ORDERS the failure we kept seeing. IRON RULE 2
(explainer_pipeline.py:1478) says "IMMEDIATELY resolve its first mechanism ... within the first ~2
beats"; RULE 3 says "NAME THE STAGES"; RULE 4 says "NEVER hoard the answer". The model obeyed --
our cancer script names "metastasis" 6% of the way in and reads out a table of contents at scene 5.
Meanwhile the social lane says the opposite ("WITHHOLD its answer until the reveal"), so the two
formats hold contradictory doctrines and neither is checked.

The doctrine here is DISTRIBUTED DISCOVERIES, DELAYED CAUSAL RESOLUTION. Concrete evidence early;
the initial observation resolved by ~25-35%; the COMPLETE CAUSAL ANSWER delayed until the viewer
knows why it matters -- but with enough runtime left to actually explain it and resolve the opening.
What is withheld is not vocabulary, it is the final causal understanding: "doctors call this
metastasis" NAMES a thing without explaining how a cell escapes, survives the blood, and colonises
an organ. Hence three term groups rather than one (see TermGroups).

Separate module, stdlib only, no pipeline import: the gates must be runnable against fixtures with
zero spend, so a wrong threshold costs nothing to find. It becomes LIVE via an import + call sites in
explainer_pipeline.py -- the trap this repo keeps hitting (sim/build.build, bolt_seq) is about call
sites, not file location.

Modelled on sim/direction.py:41-52 and its check() at :241-411, including the part that matters most:
anything a string can decide is a FAILURE; anything needing judgement is a REVIEW and is NEVER
auto-passed. A check that guesses launders an unverified assumption into a green tick.
"""
from __future__ import annotations

import json
import os
import re
import statistics as _st
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------- tokenizing
# One tokenizer, one denominator, so every percentage below is comparable. Word position is a free
# proxy for runtime position because the TTS rate is constant (explainer_pipeline assumes ~2.64 w/s;
# hotd/gates.py:36 measures 162 wpm). Do NOT "improve" this by calling TTS -- that costs money and
# buys nothing, unlike sim/build.py:55-66 where the runtime BAND itself is the thing being gated.
_TOKEN = re.compile(r"[^\W\d_]+(?:['-][^\W\d_]+)*", re.UNICODE)
_SENT = re.compile(r"(?<=[.!?…])\s+")

# Splitting on every ". " let abbreviations manufacture <=5-word sentences out of thin air:
# "In 1903 Dr. Kerr and Dr. Rahman opened the vault..." measured as [3, 3, 22] instead of [28], i.e.
# two free "punch lines" per honorific. Since cadence gates BOTH tails, that is a direct route to
# faking the short fraction without writing a single short line. Re-measured after this guard landed:
# only 2 of the 18 fixtures+renders move at all and both by <1pp, and the reference transcript's
# 39.5% long / 42.1% short do NOT move -- so the calibration those bands were set from was never an
# abbreviation artefact. The guard is here to stop the gaming route, not to correct the baseline.
_ABBR = (r"(?:Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Mt|Rev|Gen|Col|Capt|Lt|Sgt|vs|etc|al|No|Fig|Eq|approx"
         r"|Inc|Ltd|Co|e\.g|i\.e|(?:[A-Z]\.)*[A-Z])")
_ABBR_TAIL = re.compile(r"(?:^|\s)" + _ABBR + r"\.$")


def _words(text: str) -> list:
    return _TOKEN.findall((text or "").casefold())


def _sentences(text: str) -> list:
    """Sentence split that does not treat an abbreviation's period as a sentence end."""
    text = (text or "").strip()
    if not text:
        return []
    out, buf = [], ""
    for part in _SENT.split(text):
        buf = (buf + " " + part).strip() if buf else part
        if _ABBR_TAIL.search(buf):
            continue                      # "Dr." / "U.S." -- keep accumulating, not a sentence end
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return [s for s in out if s.strip()]


_PHRASE_STOP = {"a", "an", "the", "of", "to", "in", "into", "for", "and", "or", "its", "it", "their",
                "from", "on", "at", "with", "new", "own", "that", "this", "then", "out", "up"}


def _stem_tok(w: str) -> str:
    """Crude suffix strip so break/broke is the only irregular we lose. Real inflection is the whole
    problem this exists to solve -- see _first_pos_pct."""
    for suf in ("ing", "ies", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _first_pos_pct(text: str, terms, window: int = 26, need: float = 0.6,
                   long_need: float = 0.8) -> float | None:
    """Earliest position of any declared phrase, as % of total words.

    NOT substring matching. The first real run declared "cells break free from the tumor" / "survive
    the bloodstream" / "lie dormant for years" and then delivered "a cell broke free ... survived the
    blood ... It lay dormant" -- the promise kept perfectly, and an exact matcher scored it zero and
    reported the declaration as decorative. A gate that fails a script for conjugating its verbs is
    measuring the wrong thing.

    So: strip stopwords, stem what's left, and find the earliest point where `need` of a phrase's
    content words co-occur inside a `window`-token span. Single-word terms still match on a stemmed
    token-boundary prefix, so 'melanin' catches 'melanins' and 'cell' never matches 'excellent'.

    LONG phrases use a stricter ratio. At a flat 0.6 the 5-content-word promise "cells escape the
    tumour and survive the bloodstream" was scored as DELIVERED by the four-word sentence "The tumour
    cells survive." -- 3 of 5 words present, none of the causal content. Re-measured across the three
    fixtures that declare answer terms, `long_need` costs nothing: not one declared phrase is lost and
    the only movement is 67.6% -> 68.2% on a single term, while the false delivery above goes away.
    """
    toks = [_stem_tok(w) for w in _words(text)]
    if not toks:
        return None
    best = None
    for t in terms or ():
        parts = [_stem_tok(p) for p in _TOKEN.findall((t or "").casefold())]
        parts = [p for p in parts if p not in _PHRASE_STOP] or parts
        if not parts:
            continue
        if len(parts) == 1:
            idx = next((i for i, w in enumerate(toks) if w.startswith(parts[0])), None)
        else:
            want = max(1, round(len(parts) * (long_need if len(parts) >= 4 else need)))
            idx = None
            for i in range(len(toks)):
                span = set(toks[i:i + window])
                if sum(1 for p in parts if p in span) >= want:
                    idx = i
                    break
        if idx is not None:
            best = idx if best is None else min(best, idx)
    return None if best is None else 100.0 * best / len(toks)


# ------------------------------------------------------------------------------------------ regexes
# Every pattern below was backtested against all 13 renders/_ui_jobs/*/_state.json plus the reference
# transcript. Hit-counts are recorded so a future edit that silently stops matching is visible.

# Fires on 5 of our 10 scripts ("We trace one cell through three stages", "We'll answer it in three
# stages", ...) and 0 times on the reference.
#
# WIDENED after a probe of 14 natural structure-announcing phrasings caught only 2. The narrow verb
# list and the "of this"/"two|three|four|five"/"stage" anchors meant "what follows is", "let me show
# you", "coming up:", "we begin with", "part one / part two", "three acts" and "six stages" all walked
# straight through -- and injecting three of the misses into an otherwise-clean script scored
# agenda_hits = 0. IRON RULE 3 bans the behaviour; the regex has to ban the phrasings people use.
# Now catches 13/14. Verified against all 18 known samples (8 fixtures + 10 real renders): hit counts
# are byte-identical to the old regex on every one, so this adds ZERO false positives -- both control
# explainers and the reference transcript still score 0. The one deliberate miss is "over the next few
# minutes the whole picture is going to change": a vague promise, not a structure announcement, and
# any pattern loose enough to catch it starts hitting real narration.
_AGENDA_FAIL = re.compile(r"""
      \b(?:we|we'?ll|we\ will|let'?s|i'?ll|i\ want\ to)\s+
        (?:will\s+|want\s+to\s+|are\s+going\s+to\s+)?
        (?:trace|follow|chase|break\s+(?:this|it)\s+down|walk\s+through|go\s+through|unpack
          |dive\s+into|explore|examine|cover|look\s+at|show\s+you|begin\s+with|start\s+with
          |take\s+you\s+through)\b
    | \blet\s+me\s+(?:show\s+you|walk\s+you|take\s+you|explain\s+how)\b
    | \bin\s+this\s+(?:video|short|episode)\b
    | \bby\s+the\s+end\b
    | \bhere'?s\s+how\s+(?:it|this|that)\s+works?\b
    | \bstick\s+around\b
    | \bwhat\s+follows\s+is\b
    | \bcoming\s+up[:,]
    | \bhere\s+(?:is|'?s)\s+the\s+roadmap\b
    | \b(?:two|three|four|five|six|seven|eight|nine|[2-9])\s+
        (?:stages|steps|phases|layers|parts|acts|chapters|pieces|questions)\b
    | \b(?:stage|part|step|chapter|act)\s+(?:one|two|three|1|2|3)\b
    | \bfirst\b[^.?!]{0,120}[.?!]\s+(?:then|second(?:ly)?|next)\b[^.?!]{0,120}[.?!]\s+(?:then|third(?:ly)?|finally)\b
""", re.IGNORECASE | re.VERBOSE)

# Causal connectives. Used to compare EXPLANATORY density before the reversal against the mechanism
# beats -- a script that does its real explaining early and then restates it in jargon late is the one
# thing answer_position cannot see (see check()). Measured on the three role-carrying fixtures:
# pre-reversal density is 0.00/100w on all three against 0.71-0.83 after the mechanism, so this stays
# quiet on known-good scripts and fires on the inverted shape.
_CAUSAL = re.compile(r"\b(?:because|therefore|which\s+means|so\s+that|that\s+is\s+why|"
                     r"as\s+a\s+result|which\s+is\s+why|thanks\s+to|due\s+to|causes?|caused)\b",
                     re.IGNORECASE)

# REVIEW only: "three things happened that year" is legitimate content, not an agenda slide.
_AGENDA_REVIEW = re.compile(r"\b(?:two|three|four|five)\s+(?:things|reasons|ways)\b", re.IGNORECASE)

# "a hidden journey called metastasis, and here's how it works" -- names the answer as a label.
_DEFINITIONAL = re.compile(r"\b(?:a\s+process\s+called|which\s+is\s+called|is\s+called|known\s+as)\b",
                           re.IGNORECASE)

_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself|you'?re|you'?ve|you'?ll|you'?d)\b",
                            re.IGNORECASE)

_YEAR = re.compile(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b")


# ------------------------------------------------------------------------------------------- format
@dataclass
class StoryFormat:
    """A named narrative structure plus the machinery to enforce it.

    `bands` are (lo_pct, hi_pct) over WORD position, checked against what was actually delivered --
    never against the model's own declared `pct`, which is a claim, not a measurement.
    """
    name: str
    roles: tuple                       # the role palette this format allows
    required: tuple                    # roles that MUST appear
    bands: dict                        # role -> (lo_pct, hi_pct)
    # Cadence is gated on the LONG tail, not the median. First pass used a median band, which was an
    # artifact: the auto-transcribed reference under-segmented (clauses joined by commas), reading
    # median 14.5. On the accurate transcript it is median 8.5 with a 42% short-sentence fraction --
    # statistically indistinguishable from our own scripts on both counts. What actually separates
    # them is that 39.5% of the reference's sentences run to 15+ words against 5-19% of ours: it has
    # punches AND long lines, while ours are uniformly clipped and never let a thought run.
    # BOTH bounds matter. A floor alone was gamed the first time it ran: told to let thoughts run,
    # the model produced 75.3% long / 2.7% short -- it satisfied the floor by deleting every punch
    # line, which is the opposite failure and just as flat. The reference carries BOTH registers at
    # once (39.5% long AND 42.1% short); that co-presence is the property worth gating.
    long_band: tuple = (0.25, 0.55)    # fraction of sentences >= 15 words
    short_band: tuple = (0.15, 0.55)   # fraction of sentences <= 5 words
    max_short_run: int = 4             # consecutive <=5-word sentences before it reads as staccato
    # ...and the point where a staccato block stops being a style note and becomes a FAILURE. The two
    # tail fractions are order-blind: a script that dumps every short line into ONE contiguous block
    # and writes the rest uniformly long measures 52% short / 48% long -- the same profile as a
    # well-distributed script -- and passed with zero failures. Whether the short lines sit AT the
    # turns (cadence_block's actual instruction) is exactly what a run length measures, and a run
    # length is decidable by a string, so by this module's own doctrine it belongs in failures rather
    # than reviews. Threshold set from data, not taste: the longest run anywhere in the 8 fixtures and
    # 10 real renders is 5. 8 therefore fails nothing that exists and only catches the pathological
    # block. It is a new gate, not a loosened one -- the 4-run REVIEW below is unchanged.
    max_short_run_fail: int | None = 8
    # A scene must carry this many words before it may CLAIM a beat role. Guards the empty-scene
    # exploit; see check(). Required beats are held to `min_required_role_words`.
    min_role_words: int = 3
    min_required_role_words: int = 8
    opening_shape: str = "prime_question_intrigue"
    skip_conceit: bool = False
    requires: dict = field(default_factory=dict)
    architecture: str = ""             # FIXED ARCHITECTURE prompt text (filled in step 2)
    rules: str = ""                    # IRON RULES override block (filled in step 2)


# Bands from the measured reference beat map, then ADJUSTED so the video actually resolves. Cheddar
# Man puts its mechanism at 72-74% and never answers its own question -- it is a Part 1. Copying that
# timing would copy the dissatisfaction, so `mechanism` sits at 45-70% here and `resolution` is
# REQUIRED. At 3 minutes a 70% mechanism floor would leave 54s for mechanism + trade-off + payoff.
EVIDENCE_LED_MYSTERY = StoryFormat(
    name="evidence_led_mystery",
    roles=("anomaly", "credential", "false_belief", "seal", "reversal", "consequence",
           "personal_bridge", "scope_shift", "mechanism", "second_revelation", "resolution"),
    required=("anomaly", "false_belief", "reversal", "consequence", "mechanism", "resolution"),
    bands={
        "anomaly":           (0.0, 8.0),
        "credential":        (5.0, 15.0),
        "false_belief":      (12.0, 25.0),
        "seal":              (20.0, 30.0),
        "reversal":          (22.0, 35.0),
        "consequence":       (32.0, 45.0),
        "personal_bridge":   (40.0, 55.0),
        "scope_shift":       (40.0, 58.0),
        "mechanism":         (45.0, 70.0),
        "second_revelation": (70.0, 85.0),
        "resolution":        (85.0, 100.0),
    },
    opening_shape="evidence_led",
    skip_conceit=True,
    requires={"no_roadmap": True, "gate_central_answer": True, "require_resolution": True},
)

# Today's behaviour. `architecture`/`rules` stay empty until step 2 moves the current
# explainer_pipeline.py:1470-1541 text in verbatim; until then this format only carries the cadence
# band, which is a genuine defect in every long-form script we have (all 8 sit at median 6-7 words).
DEFAULT_EXPLAINER = StoryFormat(
    name="default_explainer",
    long_band=(0.0, 1.0), short_band=(0.0, 1.0),   # ungated: not changing the default lane yet
    max_short_run_fail=None,                       # ungated too -- the default lane stays untouched
    roles=("cold_consequence", "promise", "prediction_gate", "rules", "payoff", "escalation",
           "rehook", "mechanism", "reversal", "branch", "false_relief", "final_escalation",
           "final_payoff", "resonant_end"),
    required=(),
    bands={},
    requires={},
)

FORMATS = {f.name: f for f in (DEFAULT_EXPLAINER, EVIDENCE_LED_MYSTERY)}

# The evidence-led beat-sheet prompt. This REPLACES the default prompt wholesale rather than being
# appended to it -- the two doctrines contradict each other (default IRON RULE 4: "NEVER hoard the
# answer"; this: hoard the causal answer), and shipping both leaves the model to pick. Because it is
# a separate string, the default path in explainer_pipeline.py is untouched code and stays
# byte-identical, which is the whole basis for calling this a zero-regression change.
_EVIDENCE_LED_PROMPT = """Plan a {minutes}-minute YouTube explainer answering: "{question}".
Tone: {style}.{steer}
Design a SCENE-BY-SCENE BEAT SHEET of about {n_scenes} beats — one beat per scene, in order. Make \
beats GRANULAR: ONE micro-move each (a single consequence, number, or image), NOT a summary of \
several. Aim NEAR {n_scenes}; returning somewhat fewer is fine ONLY if the topic truly lacks that \
many DISTINCT beats — never pad with filler or repetition.

THE FORMAT — an EVIDENCE-LED MYSTERY. Doctrine: DISTRIBUTED DISCOVERIES, DELAYED CAUSAL RESOLUTION.
Give the viewer concrete evidence early. Resolve the opening OBSERVATION by 25-35%. Use that answer \
to open a bigger contradiction. Delay the COMPLETE CAUSAL EXPLANATION until the viewer understands \
why the contradiction matters — then explain it fully and RESOLVE the opening mystery before the end.

Return ONLY JSON: {{"title","hook","throughline","style_mode"(educational|scientific|cinematic|fun),\
"topic_terms":[the plain nouns naming the SUBJECT — say these early and often, the viewer must know \
what the video is about within two lines],"mechanism_terms":[technical vocabulary a viewer would \
have to look up],"central_answer_terms":[3-8 short PHRASES that together state the complete causal \
answer — e.g. "cells escape the tumour","survive the bloodstream","go dormant in a new organ". These \
are what you may NOT deliver before the reversal has created demand for them. Phrases, not single \
words.],"peak_scene":<int, the strongest reveal, ~65-75% through>,"beats":[{{"n":<int>,"pct":<int \
0-100>,"beat":"the SINGLE new idea/fact/story-move for this scene, concrete, one sentence","role":\
"{roles}","bolt_mode":"experience|demonstration|observation" — NOTE these are bolt_mode values, NOT roles; the "role" field may ONLY use the exact strings listed above it and nothing else}}]}}

IRON RULES:
1. ANOMALY FIRST — a STATEMENT, never a question. Open on ONE concrete, dated, located thing that is \
WRONG or does not fit, with the subject NAMED using the real noun from the title. Not a definition, \
not a number dump, not "let us investigate". "There's a skeleton in a cave in southwest England that \
scientists got completely wrong for over a hundred years" — object, place, authority, duration of \
error, and the viewer supplies the question themselves.
2. RESOLVED OBSERVATION BY 25-35% — NOT THE MECHANISM. You MUST land a real payoff by a third of the \
way in, but that payoff is an OBSERVATION that overturns what the viewer was just led to believe. \
"The skin was dark. The eyes were blue." is a payoff. "Melanin absorbs ultraviolet light" is the \
MECHANISM and belongs at 45-70%. The viewer is paid early in WHAT, and stays for WHY.
3. NO ROADMAP, NO AGENDA — BANNED. Never announce the video's own structure. Forbidden anywhere in \
the narration: "we'll trace", "we'll follow", "let's break this down", "here's how it works", "in \
this video", "by the end of this video", "stick around", "three stages/steps/layers", "stage one", \
and any "First… Then… Finally…" scaffold across three sentences. The viewer must never be told a \
journey is coming; they must already be inside one. Do NOT emit a "stages" array.
4. BUILD THE WRONG ANSWER BEFORE BREAKING IT. Spend real runtime (12-25%) on what a reasonable person \
would believe, stated sympathetically AS IF TRUE — "the face you'd expect on a man who spent his \
whole life under grey British skies". Never signal that it is wrong while stating it. It does NOT \
have to be a scientific consensus; a viewer's or a patient's reasonable assumption is stronger and \
far more defensible than claiming experts were fools. NEVER invent a controversy, a date, a study or \
a discredited belief that did not happen.
5. THE PERSONAL BRIDGE COMES BEFORE THE SCIENCE, not after. Around 40-55%, put the stake inside the \
viewer's own body or life — "a trade your ancestors were forced to make, with consequences written \
into your body right now" — and do it BEFORE explaining any mechanism. Once. Do not sprinkle "you" \
through every line; one landed bridge beats twenty pronouns.
6. RESOLVE IT. The final beats must answer the opening mystery and return to the original subject. \
This is NOT a Part 1 and NOT a cliffhanger. A video that withholds and then never pays is worse than \
one that explained too early.
7. CADENCE — LET THOUGHTS RUN. Vary sentence length hard. Long, unhurried sentences that carry a \
full causal chain, punctuated by short ones at the reveals ("It was dark." / "Read that again."). \
Roughly a quarter to a half of your sentences should run past 15 words. Uniformly clipped narration \
is the single most common failure in this pipeline: when every line is a punch, none of them lands.
8. CAUSAL SPINE: connect beats with BUT / THEREFORE / SO — never "and then". One idea per beat.
9. At most ONE prediction/guess prompt to the viewer, and never before the reversal — it competes \
with the evidence and pre-empts the surprise. The sealed false belief does that job better.

FIXED ARCHITECTURE (by PERCENT of runtime): {arch}
"""


def _arch_text(fmt: StoryFormat) -> str:
    order = ("anomaly", "credential", "false_belief", "seal", "reversal", "consequence",
             "personal_bridge", "scope_shift", "mechanism", "second_revelation", "resolution")
    bits = []
    for r in order:
        b = fmt.bands.get(r)
        if b:
            need = "" if r in fmt.required else " (optional)"
            bits.append(f"{b[0]:g}-{b[1]:g}% {r}{need}")
    return " · ".join(bits)


def beat_sheet_prompt(fmt: StoryFormat, question: str, style: str, n_scenes: int,
                      duration_sec: int, image_guidance: str = "") -> str:
    """The full beat-sheet user prompt for a non-default format. Returns "" for default_explainer so
    the caller keeps its existing string untouched."""
    if fmt.name == "default_explainer" or not fmt.bands:
        return ""
    return _EVIDENCE_LED_PROMPT.format(
        minutes=max(1, duration_sec // 60), question=question, style=style,
        steer=(f' Theme/setting steer: "{image_guidance}".' if image_guidance else ""),
        n_scenes=n_scenes, roles="|".join(fmt.roles), arch=_arch_text(fmt))


def cadence_block(fmt: StoryFormat, answer_terms=None) -> str:
    """Injected into EVERY expansion batch, not just the first.

    Written after the first real run came back at 5.4% long sentences -- identical to the default
    format's 5.3% -- with a run of TEN consecutive <=5-word lines. The beat sheet had asked for
    varied cadence and declared its central-answer phrases, but the narration is written by separate
    expansion calls that never saw either: stage 1 was fixed and stage 2 was not. The per-scene
    budget is ~14-20 words, which is exactly one good long sentence; the model was spending it on two
    short ones. That is the whole defect, so it is stated as a default here rather than a preference.
    """
    if fmt.name == "default_explainer" or not fmt.bands:
        return ""
    block = (
        ' CADENCE — TWO REGISTERS, BOTH REQUIRED. This is the most common failure in this pipeline '
        'and it fails in BOTH directions, so read the whole rule. You are writing for a voice, and a '
        'voice needs contrast:\n'
        '  · ABOUT A THIRD of your lines must RUN LONG — 15 words or more, one unbroken sentence '
        'carrying a full causal step (subject, cause and consequence in one breath, joined with '
        '"but", "so", "because", "which"). These are the lines that do the explaining.\n'
        '  · ABOUT 40%% must be SHORT — five words or fewer, landing on a reveal, a contradiction '
        'or a stake. "It was dark." "They don\'t." "Case closed." These are the lines that land.\n'
        '  · THE MIDDLE IS THE MINORITY — under a fifth. Measured on the reference this format is '
        'built from: 42%% short, 18%% middle, 40%% long. Medium-length lines are the default a model '
        'drifts into and they are the enemy; a run of 9-to-12-word sentences is the exact texture '
        'that reads as competent and forgettable. Write each scene as EITHER one long sentence '
        'carrying a full causal step OR one short punch. Reach for the middle only when neither '
        'fits.\n'
        'Both failures are equally fatal and equally common. All-short reads as a list being recited '
        'and no punch lands, because every line is a punch. All-long reads as a paper being read '
        'aloud and nothing lands at all, because the reveals have nowhere to fall. Put the short '
        'lines AT the turns and let everything else breathe.')
    if answer_terms:
        block += (
            ' THE CAUSAL ANSWER: the beat sheet committed to explaining this in these exact terms — '
            + "; ".join(f'"{t}"' for t in answer_terms)
            + '. When you write the mechanism and resolution beats, actually SAY these things rather '
              'than paraphrasing around them; that phrasing is the promise the opening made.')
    return block


def opening_block(fmt: StoryFormat) -> str:
    """Replaces the expansion batch's opening instructions. The default block independently orders
    "resolve its FIRST mechanism" and "NAME THE STAGES" into EVERY batch, so fixing only the beat
    sheet leaves two of the three agenda-slide sources alive."""
    if fmt.name == "default_explainer" or not fmt.bands:
        return ""
    return (
        ' This batch contains the OPENING. Scene 1 = the ANOMALY: one concrete, dated, located thing '
        'that is WRONG, subject NAMED with the real topic noun — never a euphemism or a pronoun on '
        'first mention. Scene 2 = the CREDENTIAL: who found it, when, why it mattered — a plain '
        'declarative, NOT a question. Following scenes = the FALSE BELIEF stated sympathetically as '
        'if it were true, then SEALED ("It made sense. Case closed."). Do NOT ask the title as a '
        'question. Do NOT preview what is coming. Do NOT name or explain any mechanism in this batch. '
        'Let sentences RUN — carry a whole causal chain in one line, and save the short punch for a '
        'reveal.')


def get(name: str) -> StoryFormat:
    """Look up a format; unknown names fall back to today's behaviour rather than raising, so a typo
    in an env var degrades to the status quo instead of breaking every render."""
    return FORMATS.get((name or "").strip().lower(), DEFAULT_EXPLAINER)


# ------------------------------------------------------------------------------------- normalizing
def _narration(script) -> list:
    """Accept either a live pipeline script ({"scenes":[{"narration",...}]}) or a fixture
    ({"narration":[...]}), so the same gates run on both without a shim at each call site."""
    if isinstance(script, dict):
        if isinstance(script.get("narration"), list):
            return [str(x or "") for x in script["narration"]]
        return [str((s or {}).get("narration") or "") for s in (script.get("scenes") or [])]
    if isinstance(script, list):
        return [str(x or "") for x in script]
    return [str(script or "")]


def _roles(script) -> list:
    if isinstance(script, dict):
        if isinstance(script.get("beat_roles"), list):
            return [str(x or "") for x in script["beat_roles"]]
        return [str((s or {}).get("_role") or "") for s in (script.get("scenes") or [])]
    return []


def _terms(script, key) -> list:
    if not isinstance(script, dict):
        return []
    return [str(x) for x in (script.get(key) or script.get("_" + key) or []) if str(x).strip()]


# ------------------------------------------------------------------------------------------- check
def check(script, fmt=None, strict: bool = False) -> dict:
    """Measure a narration script against a story format.

    Returns the sim/direction.check() shape verbatim:
        {"format", "passed", "failures", "requires_review", "measurements"}
    plus two ADDITIVE keys that exist for guard():
        "failure_codes"    -- stable slugs, e.g. "cadence.long_low", one per failing gate
        "failure_distance" -- {code: how far outside the band}, so "still failing but closer" is
                              distinguishable from "still failing and worse"
    `passed` is `not failures`. Reviews never block -- they are the honest answer for anything a
    string cannot decide, and they are surfaced rather than silently dropped.
    """
    fmt = fmt or DEFAULT_EXPLAINER
    if isinstance(fmt, str):
        fmt = get(fmt)
    lines = _narration(script)
    roles = _roles(script)
    full = " ".join(x for x in lines if x).strip()
    toks = _words(full)
    fail, review, meas = [], [], {}
    dist: dict = {}

    def _fail(code: str, msg: str, d: float = 1.0, agg: str = "max") -> None:
        """Record a failure under a STABLE code. The message carries the measured number for humans;
        the code is what guard() compares, because the message changes every time the number does."""
        fail.append(msg)
        dist[code] = (dist.get(code, 0.0) + float(d)) if agg == "sum" \
            else max(dist.get(code, 0.0), float(d))

    def _out(**kw):
        return {"format": fmt.name, "passed": not fail, "failures": fail,
                "requires_review": review, "measurements": meas,
                "failure_codes": sorted(dist), "failure_distance": dict(dist), **kw}

    if not toks:
        return {"format": fmt.name, "passed": False, "failures": ["empty narration"],
                "requires_review": [], "measurements": {},
                "failure_codes": ["empty"], "failure_distance": {"empty": 1.0}}

    meas["words"] = len(toks)
    meas["scenes"] = len(lines)

    # -- cadence: dynamic range, measured on the long tail. See StoryFormat.min_long_frac for why the
    # median and the short-sentence fraction are NOT gated -- the reference and our scripts are
    # indistinguishable on both. Calibration caveat: min_long_frac is set from ONE external sample
    # (reference 39.5%, our ten scripts 5.2-19.1%), so 0.25 is a separating value, not a proven
    # optimum. Widen it only against more outside examples, never to make a script pass.
    sents = _sentences(full)
    lens = [len(s.split()) for s in sents] or [0]
    med = float(_st.median(lens))
    mean = float(_st.mean(lens))
    short_frac = sum(1 for x in lens if x <= 5) / len(lens)
    long_frac = sum(1 for x in lens if x >= 15) / len(lens)
    run = mx = 0
    for x in lens:
        run = run + 1 if x <= 5 else 0
        mx = max(mx, run)
    meas.update({"sentences": len(sents), "median_sentence_words": round(med, 1),
                 "mean_sentence_words": round(mean, 1), "short_frac": round(short_frac, 3),
                 "long_frac": round(long_frac, 3), "max_short_run": mx,
                 "dynamic_range": round(mean / max(1.0, med), 2),
                 "sentences_per_scene": round(len(sents) / max(1, len(lines)), 2)})
    llo, lhi = fmt.long_band
    slo, shi = fmt.short_band
    if long_frac < llo:
        _fail("cadence.long_low",
              f"cadence: only {long_frac:.0%} of sentences run to 15+ words (need {llo:.0%}) "
              "-- every thought is clipped, so no punch lands", llo - long_frac)
    elif long_frac > lhi:
        _fail("cadence.long_high",
              f"cadence: {long_frac:.0%} of sentences run to 15+ words (max {lhi:.0%}) "
              "-- nothing is short enough to land as a beat", long_frac - lhi)
    if short_frac < slo:
        _fail("cadence.short_low",
              f"cadence: only {short_frac:.0%} of sentences are <=5 words (need {slo:.0%}) "
              "-- no punch lines at all; the reveals have nowhere to land", slo - short_frac)
    elif short_frac > shi:
        _fail("cadence.short_high",
              f"cadence: {short_frac:.0%} of sentences are <=5 words (max {shi:.0%})", short_frac - shi)
    if fmt.max_short_run_fail is not None and mx >= fmt.max_short_run_fail:
        _fail("cadence.short_run",
              f"cadence: {mx} consecutive <=5-word sentences -- the short lines are dumped in one "
              "staccato block instead of landing at the turns", mx)
    elif mx > fmt.max_short_run:
        review.append(f"cadence: {mx} consecutive <=5-word sentences")
    if max(lens) > 34:
        review.append(f"cadence: longest sentence {max(lens)} words -- check it survives TTS")

    # -- agenda slide. Announcing the structure is the tell that turns a story into a syllabus.
    hits = _AGENDA_FAIL.findall(full)
    meas["agenda_hits"] = len(hits)
    if hits:
        _fail("agenda_slide", f"agenda_slide: {len(hits)} structure-announcing phrase(s)", len(hits))
    if _AGENDA_REVIEW.search(full):
        review.append("agenda_slide: 'three things/reasons/ways' -- content or agenda?")

    # -- second person. REVIEW ONLY, deliberately. Density is gameable in the wrong direction ("you
    # see, your cells inside your body" scores higher and reads worse), and expl_35c293e6 measures
    # 2.44/100w -- nearly double the reference -- while still being a lecture. The real requirement
    # is the personal_bridge BEAT below, which is structural and not fakeable by pronoun-stuffing.
    sp = 100.0 * len(_SECOND_PERSON.findall(full)) / len(toks)
    meas["second_person_per_100w"] = round(sp, 2)
    if sp < 0.60:
        review.append(f"second_person: {sp:.2f}/100w -- story may never reach the viewer")
    elif sp > 3.0:
        review.append(f"second_person: {sp:.2f}/100w -- reads as a PSA")

    # -- evidence anchors. REVIEW ONLY and it must stay that way: a hard gate demanding a dated
    # anchor on "how does cancer spread" is a direct instruction to fabricate one, and
    # factcheck_script is worst at exactly that -- a plausible fake date.
    head = " ".join(toks[:max(1, len(toks) // 3)])
    meas["years_in_first_third"] = len(_YEAR.findall(" ".join(lines))[:20])
    if not _YEAR.search(" ".join(lines[:max(1, len(lines) // 3)])):
        review.append("evidence_anchors: no date in the first third (do NOT invent one)")

    fmt_gates_apply = bool(fmt.required or fmt.bands)
    if not fmt_gates_apply:
        return _out()

    # ---- structural gates below here need beat roles. Without them we CANNOT decide, so we say so
    # rather than passing. This is the sim/direction doctrine: never launder an unknown into a tick.
    if not any(r for r in roles):
        review.append("beat roles absent -- structural gates could not run (persist _role first)")
        return _out()
    if len(roles) != len(lines):
        review.append(f"beat roles misaligned ({len(roles)} roles vs {len(lines)} scenes) -- "
                      "structural gates skipped rather than guessed")
        return _out()

    # word position of each scene's start, so a role's delivered position is measurable
    starts, acc = [], 0
    for ln in lines:
        starts.append(100.0 * acc / len(toks))
        acc += len(_words(ln))

    # A role is claimed by the first scene that carries REAL NARRATION. Without the word-count floor
    # an EMPTY scene claims the beat: `starts` is cumulative-words-BEFORE-the-scene, so a zero-word
    # final scene sits at exactly 100.0% and sails through the 85-100% `resolution` band. Emptying the
    # resolution scene of a passing 12-scene script (text merged into its neighbour, so every other
    # role stays put) changed nothing except resolution 93.7% -> 100.0%: still passed, no review, and
    # the video now resolves nothing at all. IRON RULE 6 and require_resolution both reported
    # satisfied by a beat containing no words. Floors are set from data: across the fixtures the
    # thinnest scene holding a REQUIRED role is 19 words, and the only short role-carrying scenes are
    # the optional `seal` at 6-13 words ("It made sense. Case closed." is a legitimate seal), so 8
    # and 3 sit clear of everything real.
    scene_words = [len(_words(ln)) for ln in lines]
    first, thin = {}, {}
    for i, r in enumerate(roles):
        r = (r or "").strip().lower()
        if not r or r in first:
            continue
        if scene_words[i] < fmt.min_role_words:
            thin.setdefault(r, i)          # remember it, but it does not get to claim the beat
            continue
        first[r] = i
    meas["roles_present"] = sorted(first)
    meas["role_pct"] = {r: round(starts[i], 1) for r, i in sorted(first.items())}

    for r in first:
        if r not in fmt.roles:
            _fail("beat_order.palette",
                  f"beat_order: role '{r}' not in the {fmt.name} palette", 1, agg="sum")
    for r in fmt.required:
        if r not in first:
            if r in thin:
                _fail("beat_order.empty_role",
                      f"beat_order: required beat '{r}' lands only on a scene with "
                      f"{scene_words[thin[r]]} word(s) -- the beat is empty", 1, agg="sum")
            else:
                _fail("beat_order.missing",
                      f"beat_order: required beat '{r}' missing", 1, agg="sum")
        else:
            # Sum across EVERY scene carrying the role, not just the first. A role routinely spans a
            # dozen scenes, and measuring only its opener contradicted the cadence rule directly:
            # that rule ASKS for short punch lines, so a resolution opening on "So Paget's
            # century-old riddle finally resolves." (6 words) was failed while the resolution it
            # opened ran 197 words across 12 scenes. The defect this gate exists to catch is a role
            # stamped onto nothing at all, which the total still catches.
            _total = sum(scene_words[i] for i, rr in enumerate(roles)
                         if (rr or "").strip().lower() == r)
            if _total < fmt.min_required_role_words:
                _fail("beat_order.empty_role",
                      f"beat_order: required beat '{r}' carries only {_total} words in total -- "
                      "too thin to be the beat it claims to be", 1, agg="sum")
    for r, i in thin.items():
        if r not in first and r not in fmt.required:
            review.append(f"beat_order: optional beat '{r}' lands only on a near-empty scene")

    if "false_belief" in first and "reversal" in first and first["false_belief"] >= first["reversal"]:
        _fail("beat_order.false_belief",
              "beat_order: false_belief does not precede reversal -- nothing to overturn")
    if "personal_bridge" not in first:
        review.append("personal_bridge: absent -- the science may stay emotionally distant")
    if "mechanism" in first and "resolution" in first and first["resolution"] <= first["mechanism"]:
        _fail("beat_order.resolution_order", "beat_order: resolution must follow the mechanism")

    for r, i in first.items():
        band = fmt.bands.get(r)
        if not band:
            continue
        pos = starts[i]
        blo, bhi = band
        if pos < blo - 8 or pos > bhi + 8:
            _fail("beat_order.band", f"beat_order: '{r}' at {pos:.0f}%, band {blo:g}-{bhi:g}%",
                  max(blo - pos, pos - bhi), agg="sum")
        elif not (blo <= pos <= bhi):
            review.append(f"'{r}' at {pos:.0f}% is just outside its {blo:g}-{bhi:g}% band")

    # -- the central answer. NOT a jargon ban: topic_terms are free (subject clarity wins, and it is
    # our packaging standard), mechanism_terms are only measured. What is gated is the COMPLETE
    # CAUSAL ANSWER -- the phrases that make the phenomenon make sense -- which may not land before
    # the reversal has created demand for it.
    answer = _terms(script, "central_answer_terms")
    meas["central_answer_terms"] = len(answer)
    if fmt.requires.get("gate_central_answer"):
        if not answer:
            review.append("central_answer_terms not declared -- answer_position could not be checked")
        else:
            # COMPLETION, not first-appearance. Taking the earliest of any declared phrase measured
            # the wrong event: one loose match put the "answer" at 5.8% while the phrases actually
            # landed at 24%, 26% and 53%. The complete causal answer is on the table when MOST of its
            # parts have been said, so gate the point where 60% of them have appeared.
            hits = sorted(p for p in (_first_pos_pct(full, [t]) for t in answer) if p is not None)
            meas["answer_parts_delivered"] = f"{len(hits)}/{len(answer)}"

            # THE DECIDABLE HALF. answer_position measures where the model's OWN DECLARED phrases
            # land, and nothing tied those phrases to the explanation. So first check the declaration
            # actually describes the mechanism beats: overlap of the answer terms' content words with
            # the mechanism/second_revelation/resolution scenes. Measured 50% / 91% / 100% on the
            # three fixtures that declare terms, so a floor of 1/3 sits below everything real and only
            # catches a declaration that is not describing this script's explanation at all.
            expl = " ".join(ln for ln, r in zip(lines, roles)
                            if (r or "").strip().lower()
                            in ("mechanism", "second_revelation", "resolution"))
            expl_stems = {_stem_tok(w) for w in _words(expl)}
            tot = cov = 0
            for t in answer:
                cw = [_stem_tok(w) for w in _words(t) if w not in _PHRASE_STOP]
                tot += len(cw)
                cov += sum(1 for w in cw
                           if any(m.startswith(w) or w.startswith(m) for m in expl_stems))
            overlap = (cov / tot) if tot else 0.0
            meas["answer_terms_in_mechanism"] = round(overlap, 2)
            if tot and overlap < 0.34:
                _fail("answer_position.declaration",
                      f"answer_position: only {overlap:.0%} of the declared answer wording appears in "
                      "the mechanism beats -- the declaration does not describe this script's "
                      "explanation, so its measured position means nothing", 0.34 - overlap)

            if not hits:
                _fail("answer_position.absent",
                      "answer_position: no declared central-answer phrase appears at all -- "
                      "the declaration was decorative")
            elif len(hits) < max(2, round(len(answer) * 0.6)):
                _fail("answer_position.partial",
                      f"answer_position: only {len(hits)}/{len(answer)} declared answer parts "
                      "were actually delivered -- the opening promised more than it paid",
                      max(2, round(len(answer) * 0.6)) - len(hits))
            else:
                pos = hits[max(0, round(len(answer) * 0.6) - 1)]
                meas["answer_position_pct"] = round(pos, 1)
                rev_pct = starts[first["reversal"]] if "reversal" in first else None
                # FAIL only when the answer is complete before the reversal -- that is unambiguous.
                # Anything subtler is a judgement a string cannot make: this script's false belief
                # ("some cells break off and float away") describes the same physical event as the
                # true answer, and no keyword test separates the wrong picture from the right one.
                if rev_pct is not None and pos < rev_pct:
                    _fail("answer_position.early",
                          f"answer_position: causal answer complete at {pos:.0f}%, before the "
                          f"reversal at {rev_pct:.0f}% -- nothing was withheld", rev_pct - pos)
                elif pos < 30.0:
                    review.append(f"answer_position: causal answer complete at {pos:.0f}% -- check it "
                                  "reads as a reveal rather than an early explanation")
                else:
                    # THE UNDECIDABLE HALF, surfaced rather than ticked. A script can explain the whole
                    # thing in plain English at 8% and then restate it as jargon at 75%: the declared
                    # phrases land late, so this gate reads 71% and passes. Detecting that the early
                    # paraphrase IS the answer is semantic -- the gaming case deliberately shares
                    # almost no vocabulary with the late restatement, so no keyword test separates
                    # them. Per this module's doctrine that is a REVIEW and must never be auto-passed.
                    review.append(
                        f"answer_position: {pos:.0f}% is where the DECLARED phrases land, which is a "
                        "claim about wording, not proof the explanation was withheld -- read the "
                        "pre-reversal beats and confirm they do not already explain it in plainer words")
                # A decidable proxy for that review: if the beats BEFORE the reversal are denser in
                # causal connectives than the mechanism beats, the explaining is happening early
                # whatever the declared vocabulary says. Quiet on all three fixtures (0.00/100w
                # pre-reversal vs 0.71-0.83 after), so it fires on the inversion, not on normal prose.
                if rev_pct is not None and "reversal" in first:
                    pre = " ".join(lines[:first["reversal"]])
                    pre_w, exp_w = len(_words(pre)), len(_words(expl))
                    if pre_w >= 40 and exp_w >= 40:
                        dp = 100.0 * len(_CAUSAL.findall(pre)) / pre_w
                        dm = 100.0 * len(_CAUSAL.findall(expl)) / exp_w
                        meas["causal_density_pre_vs_mech"] = (round(dp, 2), round(dm, 2))
                        if dp > dm:
                            review.append(
                                f"answer_position: the beats before the reversal carry MORE causal "
                                f"explanation ({dp:.2f}/100w) than the mechanism beats ({dm:.2f}/100w)"
                                " -- the real explaining may already be done before the reveal")

    # definitional tell -- "a process called X" in the opening quarter names the answer as a label
    head_txt = " ".join(lines[:max(1, len(lines) // 4)])
    if _DEFINITIONAL.search(head_txt):
        _fail("definitional_tell", "definitional_tell: answer labelled in the first quarter")

    return _out()


def guard(before, after, fmt=None) -> dict:
    """Return `after` only if it broke no gate that `before` passed; otherwise keep `before`.

    Five post-passes rewrite narration after generation (_dedupe_narration, _ensure_hook_names_subject,
    factcheck_script, _revise_for_axis, enforce_conceit). _revise_for_axis already keeps a revision
    when the LLM grade improves -- but analyze_grade_vs_outcome.py measured that grade against real
    retention at rho=+0.07 (p=0.812, n=14), so a rewrite can raise `hook` by six points while deleting
    the false_belief beat and today it would be kept. Structural preservation outranks a grade that
    does not predict anything.

    Compared on failure CODES, never on failure MESSAGES. The first version set-diffed the rendered
    strings, and every string embeds its own measurement -- "only 5% of sentences run to 15+ words"
    versus "only 20% ...". Improving a failing gate therefore produced a string the `before` set did
    not contain, which read as a brand-new failure and reverted the improvement. Both halves of that
    reproduced: a rewrite moving long_frac 5% -> 20% (strictly toward the 25% floor) was discarded,
    and so was a _dedupe_narration pass cutting agenda hits 4 -> 2. That was not a corner case --
    every one of the 10 real scripts currently fails cadence, so on the evidence-led lane a failing
    draft is the NORMAL state, and essentially every post-pass rewrite was being silently reverted.
    The guard meant to protect structure was quietly freezing the first draft instead.

    So: revert only when a gate that `before` was passing is now broken, or when a gate both fail is
    measurably FURTHER outside its band. "Still failing, but closer" is kept -- that is progress.
    """
    try:
        b, a = check(before, fmt), check(after, fmt)
    except Exception:
        return after                                   # never let the guard itself break a render
    bd = b.get("failure_distance") or {}
    ad = a.get("failure_distance") or {}
    if set(ad) - set(bd):
        return before                                  # broke a gate that `before` was passing
    for code, d in ad.items():
        if d > bd.get(code, 0.0) + 1e-9:
            return before                              # same gate, measurably worse
    return after


# ---------------------------------------------------------------------------------------- selftest
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "story")


def selftest(verbose: bool = True) -> int:
    """Run every fixture against its declared expectation. Zero API calls, zero dollars.

    The acceptance bar is deliberately two-sided: strong scripts must PASS, weak ones must FAIL, and
    the two non-mystery explainers must NOT be penalised -- they select default_explainer and are
    judged against ITS gates. A gate that cannot fail known-bad is not evidence; one that fails
    known-good is worse, because it would push every topic into a mystery it does not have.
    """
    if not os.path.isdir(_FIXTURES):
        print(f"no fixtures at {_FIXTURES}")
        return 1
    bad = 0
    for fn in sorted(os.listdir(_FIXTURES)):
        if not fn.endswith(".json"):
            continue
        fx = json.load(open(os.path.join(_FIXTURES, fn)))
        fmt = get(fx.get("format") or "default_explainer")
        res = check(fx, fmt)
        exp = fx.get("expect") or {}
        ok = True
        if "pass" in exp and bool(exp["pass"]) != res["passed"]:
            ok = False
        for want in exp.get("fail") or []:
            if not any(f.startswith(want) for f in res["failures"]):
                ok = False
        bad += 0 if ok else 1
        if verbose:
            mark = "OK  " if ok else "FAIL"
            print(f"  {mark} {fn:34s} [{fmt.name:18s}] passed={str(res['passed']):5s} "
                  f"med={res['measurements'].get('median_sentence_words')} "
                  f"fails={len(res['failures'])} review={len(res['requires_review'])}")
            if not ok:
                for f in res["failures"]:
                    print(f"        - {f}")
    print(("selftest OK" if not bad else f"selftest FAILED ({bad} fixture(s))"))
    return 0 if not bad else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(selftest() if "--selftest" in sys.argv else selftest())
