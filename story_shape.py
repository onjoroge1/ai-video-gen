"""The middle and the ending of a scripted film (docs/STORY_PLAYBOOK.md, operator 2026-10-17).

The opening contract is untouched: the myth line, the reveal, the witness, the question. This module
holds what comes after it.
- `writer_rules` is spoken to the chunked writer.
- `findings` is measured on a finished script. It reports to the storyboard's advisory warnings,
  and `python3 story_shape.py <job>/_state.json` prints the same findings for a hand-written script.

Measured on the Chernobyl film (886 words), whose middle viewers felt meander:
- the witness named at 4% did not return until 90%;
- four questions in the body were each answered in the next breath ("So how many, all told?");
- 12 sentences opened on "So";
- 61 numbers, about one every 14 words;
- the close gave advice ("ask what it switches off") instead of answering the title.
"""
from __future__ import annotations

import json
import re
import sys

WRITER_MIDDLE = (
    " STORY MIDDLE (operator, 2026-10-17; the opening rules above are unchanged): after the opening "
    "scene, every scene answers part of the title question and leaves a sharper version of it -- no "
    "side story that serves a different question. KEEP THE HUMAN STORY: the documented person (or the "
    "viewer's role) from the opening returns at the turn in the middle and again in the close, doing "
    "only what the sources say. At most two questions in the body, and never one the next sentence "
    "simply answers (\"So how many, all told?\"). Vary scene openings: \"So\" opens at most one scene "
    "in four (But, Still, Then, Even, Until, Only, That also join). At most one number per sentence; "
    "where the beat allows, say what the number means for a person.")
WRITER_ENDING = (
    " STORY ENDING (operator, 2026-10-17): by the start of the final third, say the answer to the title "
    "question in one plain sentence. The close returns to the opening person or object with a changed "
    "meaning and stops: no general lesson, no advice to the viewer (\"ask what it switches off\"), and "
    "no recap of your own (a synthesis row, when the sheet has one, is the only re-walk).")

MAX_BODY_QUESTIONS = 2
LESSON = re.compile(
    r"\b(ask (?:what|whether|who|yourself)|remember (?:that|to)|the lesson|next time (?:you|a)|"
    r"whenever (?:a|an|you)|when (?:a|an) \w+ promises|let that be)\b", re.I)
CONTRAST_OPEN = re.compile(r"^\s*(?:but|yet|instead|except|not|still|only|why\b)", re.I)
TURN_ROLES = {"reversal", "hinge", "false_resolution", "apparent_success"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_WORD = (r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|"
                r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion")
_NUMBER = re.compile(rf"\b(?:\d[\d,.]*|(?:{_NUMBER_WORD})(?:[- ](?:{_NUMBER_WORD}|point))*)\b", re.I)
_MONTHS = r"January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}\b|\b(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}\b"
                   rf"|\b(?:1[5-9]|20)\d\d\b")
# A capitalised name that is not a place ("at Los Alamos") or a thing ("the Elephant's Foot").
_NAME = re.compile(r"(?<![A-Za-z])(?<!\bat )(?<!\bin )(?<!\bthe )(?<!\bThe )(?<!\bof )(?<!\bfrom )(?<!\bto )"
                   r"([A-Z][a-z]+(?:\s+[A-Z][a-z'’]+)+)")
_NOT_PEOPLE = {"You'd", "So", "But", "And", "In", "On", "When", "Then", "It", "This", "That"}


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(_text(text).strip()) if s]


_NOT_FIGURES = re.compile(r"\bone (?:by one|of|another|day|night)\b|\bno one\b", re.I)


def numbers_in(sentence: str) -> int:
    """Counted figures in a sentence; dates, years and pronoun "one" are not figures."""
    return len(_NUMBER.findall(_NOT_FIGURES.sub(" ", _DATE.sub(" ", sentence))))


def opening_people(opening_narration: str) -> list[str]:
    """Surnames of the people the opening names, e.g. ['Slotin'] or ['Korneyev']."""
    out = []
    for match in _NAME.finditer(_text(opening_narration)):
        words = match.group(1).split()
        if words[0] in _NOT_PEOPLE:
            words = words[1:]
        if len(words) >= 2 and words[-1] not in out:
            out.append(words[-1])
    return out


def findings(scenes: list[dict]) -> list[dict]:
    """Advisory findings on the middle and the ending. Scene 1 (the opening) is never judged."""
    narr = [_text(s.get("narration")) for s in scenes or []]
    if len(narr) < 4:
        return []
    roles = [_text(s.get("causal_role")).lower() for s in scenes]
    words = [len(n.split()) for n in narr]
    total = max(1, sum(words))
    starts = [sum(words[:i]) / total for i in range(len(narr))]
    out = []

    body = [s for n in narr[1:] for s in _sentences(n)]
    questions = [s for s in body if s.rstrip().endswith("?")]
    if len(questions) > MAX_BODY_QUESTIONS:
        out.append({"code": "BODY_QUESTIONS", "message": (
            f"{len(questions)} questions after the opening (at most {MAX_BODY_QUESTIONS}); a question "
            f"the next sentence answers holds no tension: " + " | ".join(q[:60] for q in questions[:4]))})

    so_openers = sum(1 for n in narr[1:] if re.match(r"\s*(?:and )?so\b", n, re.I))
    cap = max(2, round(len(narr) / 4))
    if so_openers > cap:
        out.append({"code": "SO_CADENCE", "message": (
            f"{so_openers} scenes open on \"So\" (at most {cap} of {len(narr)}); vary the joints")})

    dense = [s for s in body if numbers_in(s) >= 2]
    if len(dense) > max(1, len(body) // 8):
        out.append({"code": "NUMBER_DENSE", "message": (
            f"{len(dense)} sentences carry two or more figures; one per sentence, said at human scale: "
            + " | ".join(s[:70] for s in dense[:3]))})

    people = opening_people(narr[0])
    if people:
        def seen(lo: float, hi: float) -> bool:
            return any(lo <= starts[i] < hi and any(p in narr[i] for p in people)
                       for i in range(1, len(narr)))
        missing = [where for where, lo, hi in (("the middle", 0.30, 0.80), ("the close", 0.75, 1.01))
                   if not seen(lo, hi)]
        if missing:
            out.append({"code": "HUMAN_THREAD_DROPPED", "message": (
                f"{', '.join(people)} from the opening does not return in {' or '.join(missing)}; the "
                "human story is what viewers follow")})

    middle = [i for i in range(1, len(narr)) if 0.35 <= starts[i] <= 0.65]
    if middle and not any(roles[i] in TURN_ROLES or CONTRAST_OPEN.match(narr[i]) for i in middle):
        out.append({"code": "MIDPOINT_TURN_MISSING", "message": (
            "no scene between 35% and 65% turns what the viewer believes (a reversal, a false relief "
            "or a paradox)")})

    closing = [i for i, r in enumerate(roles) if r in ("tool", "verdict", "synthesis")] or [len(narr) - 1]
    lesson = [s for i in closing for s in _sentences(narr[i]) if LESSON.search(s)]
    if lesson:
        out.append({"code": "LESSON_CLOSE", "message": (
            "the close gives advice instead of answering the title and returning to the opening: "
            + lesson[0][:90])})
    return out


def writer_rules(is_last: bool) -> str:
    return WRITER_MIDDLE + (WRITER_ENDING if is_last else "")


def main(argv: list[str]) -> int:
    script = json.load(open(argv[0]))
    script = script.get("script", script)
    found = findings(script.get("scenes") or [])
    for item in found:
        print(f"{item['code']}: {item['message']}")
    if not found:
        print("story shape: no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
