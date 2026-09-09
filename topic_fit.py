"""Does this question have a story in it, asked before any research is bought.

Measured cost of not asking: "Why don't Americans eat hippo meat?" spent $3.20 across four runs
and never produced a spine. The failure was not the engine and not the budget. The question has no
story in it -- it asks about an ABSENCE with a dozen parallel causes, and research answered all of
them, returning 21 verified claims split between a 1910 congressional episode and modern African
conservation. The planner then built one spine from two stories, which is not a thing that can be
done.

What fits is read off the reference corpus rather than invented. Every reference is one documented
episode whose outcome inverted its intent:

    DC emancipation   freed the slaves -- and paid the owners
    Haiti             freed themselves -- then were billed for it by France
    Hanoi             paid to kill rats -- bred rats
    Romanovs          the richest family on earth -- shot in a cellar
    Pompeii           the richest soil in the region, because of what killed them

So the screen asks three things, and a question has to answer all three:

    1. does it name ONE episode, bounded in time and place
    2. is there an INTENT -- something someone was trying to achieve
    3. does the OUTCOME invert that intent, rather than merely falling short

The third is the one that rejects most near-misses. "The programme failed" is not an inversion;
"the programme produced more of what it was meant to remove" is.

Structure is judged deterministically and cheaply; the inversion is a semantic question and gets a
small model call. The deterministic half never refuses on its own -- it has been wrong twice in
this codebase already -- it supplies signals to the call that rules.
"""
from __future__ import annotations

import json
import os
import re

FITS, NEEDS_NARROWING, NO_STORY = "fits", "needs_narrowing", "no_story"

# "Why don't Americans eat hippo meat", "why isn't there a cure for X". A question about something
# that never happened has no chain of events to follow, because nothing happened.
_ABSENCE = re.compile(
    r"^\s*why\s+(?:don'?t|doesn'?t|didn'?t|aren'?t|isn'?t|hasn'?t|haven'?t|can'?t|won'?t|"
    r"do\s+we\s+not|does\s+\w+\s+not|is\s+there\s+no|are\s+there\s+no)\b", re.I)
# A year, a century, or a decade. An episode almost always carries one; a standing condition does not.
_TIME_ANCHOR = re.compile(r"\b(1[0-9]\d\d|20\d\d|\d{1,2}(?:st|nd|rd|th)\s+century|\d{4}s)\b", re.I)


def signals(question: str) -> dict:
    """Free, and advisory only. These describe the question's shape, not its worth."""
    text = (question or "").strip()
    return {"absence_framing": bool(_ABSENCE.search(text)),
            "time_anchor": bool(_TIME_ANCHOR.search(text)),
            "words": len(text.split())}


_SYSTEM = (
    "You screen questions for a documentary series. Every episode the series has made is ONE "
    "documented historical episode whose outcome inverted its intent: a city paid a bounty per rat "
    "tail and residents farmed rats; a law freed enslaved people in Washington DC and compensated "
    "their owners; Haiti won its freedom and was then billed for it by France. Answer only about "
    "the question you are given. Return only JSON.")


def _prompt(question: str, found: dict) -> str:
    return (
        f'QUESTION: "{question}"\n\n'
        f"Deterministic signals (advisory, may be wrong): asks about something that did NOT happen "
        f"= {found['absence_framing']}; names a date or period = {found['time_anchor']}.\n\n"
        "Answer three things about the question, in order:\n"
        "1. EPISODE — does it point at one specific documented episode, bounded in time and "
        "place? A standing condition with many parallel causes is not an episode.\n"
        "2. INTENT — was somebody trying to achieve something? Name it in a few words.\n"
        "3. INVERSION — did the outcome turn that intent into its opposite? Falling short is NOT "
        "an inversion: a plan that simply failed, or a thing that never happened, has no turn in "
        "it. Producing MORE of what was meant to be removed is an inversion.\n\n"
        'Return ONLY JSON: {"episode":"the episode in a short phrase, or empty","intent":"",'
        '"inversion":"how the outcome inverted the intent, or empty",'
        '"verdict":"fits|needs_narrowing|no_story",'
        '"reason":"one sentence a person can act on",'
        '"narrower_question":"if needs_narrowing, the question that names the episode; else empty"}\n'
        "Use needs_narrowing when a real episode is buried inside a broader question, and give the "
        "narrower question. Use no_story when nothing in the topic inverts.")


def screen(question: str, *, judge=None, cost_sink=None) -> dict:
    """Screen one question. Returns a verdict; refusing is the caller's decision.

    `judge(prompt, system=...)` returns the model's raw text. Unreachable or unparseable means
    UNKNOWN, not rejection: a screen that fails closed on an outage refuses good questions for
    reasons that have nothing to do with them.
    """
    found = signals(question)
    if judge is None:
        return {"verdict": "unknown", "reason": "no judge available; not screened",
                "signals": found, "screened": False}
    try:
        raw = judge(_prompt(question, found), system=_SYSTEM)
        data = json.loads(re.search(r"\{.*\}", str(raw), re.S).group(0))
    except Exception as exc:                                # noqa: BLE001 - advisory by design
        return {"verdict": "unknown", "signals": found, "screened": False,
                "reason": f"screen unavailable ({type(exc).__name__}); not screened"}
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in (FITS, NEEDS_NARROWING, NO_STORY):
        verdict = "unknown"
    return {"verdict": verdict, "screened": True, "signals": found,
            "episode": str(data.get("episode", "")).strip(),
            "intent": str(data.get("intent", "")).strip(),
            "inversion": str(data.get("inversion", "")).strip(),
            "narrower_question": str(data.get("narrower_question", "")).strip(),
            "reason": str(data.get("reason", "")).strip()}


def blocks(result: dict) -> bool:
    """Only a confident no_story stops a run, and only when the screen is enforced.

    `needs_narrowing` does not block: the episode is real and the operator may know exactly which
    one they mean. `unknown` never blocks -- an outage is not a verdict about a question.
    """
    return bool(result.get("screened")) and result.get("verdict") == NO_STORY and enforced()


def enforced() -> bool:
    """TOPIC_FIT=off to screen without refusing. On by default: the point is to spend nothing."""
    return os.environ.get("TOPIC_FIT", "on").strip().lower() not in ("0", "off", "false")


def report(question: str, result: dict) -> str:
    if not result.get("screened"):
        return f"[topic] {result.get('reason', 'not screened')}"
    lines = [f"[topic] {result['verdict'].upper()}: {result.get('reason', '')}"]
    if result.get("episode"):
        lines.append(f"        episode:   {result['episode']}")
    if result.get("inversion"):
        lines.append(f"        inversion: {result['inversion']}")
    elif result["verdict"] != FITS:
        lines.append("        inversion: none found — the series is built on outcomes that turn, "
                     "and a topic without a turn has no spine to compile")
    if result.get("narrower_question"):
        lines.append(f'        try:       "{result["narrower_question"]}"')
    return "\n".join(lines)
