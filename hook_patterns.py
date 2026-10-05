"""What makes an opening line hold a scroller, measured rather than asserted.

Our three delivered films all use ONE construction: [actor] did [X] to achieve [Y], then [bad
thing]. It carries a contradiction, which is the strongest of the known patterns, but it also
states the purpose AND the result, so the question the video exists to answer is already closed
in its first sentence. The wolves hook does not even manage the contradiction: "Government
hunters killed Yellowstone's last wolves" is a fact with no tension in it at all.

Four patterns, from an analysis of viral openings, filtered to the ones that suit a sourced
documentary channel:

  CONTRADICTION   unresolved tension between two halves. Present in roughly a third of top
                  performers and the single strongest signal.
  SPECIFICITY     a weirdly exact number, place or name reads as lived rather than summarised.
                  "Twenty-six queens" beats "some bees".
  TIMEFRAME       an explicit clock ("within two years", "still, seventy years later") creates
                  a curiosity loop and a sense of scale. Absent from all three of our films.
  OPEN QUESTION   the hook poses, it does not conclude. A hook that states both the purpose and
                  the outcome has answered itself.

The fourth is in tension with the cold open, which deliberately SHOWS the damage early because
viewers were leaving at 41 seconds waiting for a consequence. They reconcile: the cold open
carries the visual payoff, the hook carries the verbal question. What the hook must stop doing
is explaining WHY, because that is the whole film.

POV framing ("POV: you just released a toad") is deliberately NOT scored. It performs well on
short social formats and would read as cheap on a sourced history channel.
"""
from __future__ import annotations

import re

# A pivot between two opposed halves.
_PIVOT = re.compile(r"\b(but|yet|then|instead|until|however|still|despite|though|although)\b", re.I)
# Persistence and negation carry tension without a pivot word: "they never stopped spreading"
# is as unresolved as "but they spread". Syntactic only — see the limitation note in score_hook.
_PERSIST = re.compile(r"\b(never|no longer|nothing|could not|couldn'?t|would not|wouldn'?t|"
                      r"has not|hasn'?t|did not|didn'?t|not one|none of)\b", re.I)
# Purpose: the hook explaining what the actor was trying to achieve.
_PURPOSE = re.compile(r"\b(to (?:kill|stop|protect|control|save|make|boost|fix|solve|eradicate|"
                      r"increase|improve|remove|prevent|cure|raise|breed)|so that|in order to|"
                      r"meant to|intended to|hoping to|for more)\b", re.I)
# An explicit clock.
_TIMEFRAME = re.compile(r"\b(\d{4}|within|in (?:just )?(?:a|one|two|three|four|five|six|seven|eight|"
                        r"nine|ten|twelve|eighteen|twenty|thirty|forty|fifty|sixty|seventy|\d+)\s*"
                        r"(?:years?|months?|weeks?|days?|decades?)|years? later|months? later|"
                        r"decades? later|still|today|to this day|ever since|by then|overnight|"
                        r"a century later)\b", re.I)
_NUMBER = re.compile(r"\b(\d[\d,]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                     r"twenty[- ]?\w*|thirty|forty|fifty|sixty|hundred|thousand|million|billion)\b", re.I)
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}")
_VAGUE = re.compile(r"\b(some|several|many|a few|various|certain|things|stuff|people|it went wrong|"
                    r"something|changed everything|you (?:won'?t|will never) believe)\b", re.I)

PATTERNS = ("contradiction", "specificity", "timeframe", "open_question")


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def score_hook(hook: str, *, subject_words: set | None = None) -> dict:
    """Which patterns an opening line carries, and a 0-100 from their weights.

    Deterministic and provider-free, so it costs nothing to reject a weak hook before anything
    is written against it.
    """
    line = _text(hook)
    if not line:
        return {"score": 0, "patterns": {p: False for p in PATTERNS}, "notes": ["no hook"],
                "words": 0}
    words = len(line.split())
    # Proper nouns, ignoring the sentence-initial capital.
    propers = _PROPER.findall(" " + line[1:] if line else "")
    has_number = bool(_NUMBER.search(line))
    contradiction = bool(_PIVOT.search(line)) or bool(_PERSIST.search(line))
    # A comma-joined two-clause line with a purpose in the first half also reads as a turn.
    if not contradiction and _PURPOSE.search(line) and ("," in line or "—" in line):
        contradiction = True
    specificity = has_number or len(propers) >= 1
    timeframe = bool(_TIMEFRAME.search(line))
    # Answered itself: states what they were trying to do AND how it turned out.
    resolved = bool(_PURPOSE.search(line)) and contradiction
    open_question = not resolved
    found = {"contradiction": contradiction, "specificity": specificity,
             "timeframe": timeframe, "open_question": open_question}
    weights = {"contradiction": 30, "specificity": 25, "timeframe": 25, "open_question": 20}
    score = sum(w for p, w in weights.items() if found[p])
    notes = []
    # KNOWN LIMIT: contradiction is detected SYNTACTICALLY. "Yellowstone shot its last wolf in
    # 1926. Seventy years later the rivers had moved." carries real tension — wolves and rivers
    # are unrelated in a naive model — and nothing here can see it, because the surprise is
    # semantic. This scorer is a floor, not a ceiling; a hook can be good and score 70.
    if not contradiction:
        notes.append("no tension: the line states a fact and leaves nothing unresolved")
    if not specificity:
        notes.append("no number, date or name: it reads as a summary rather than something lived")
    if not timeframe:
        notes.append("no clock: add how fast or how long ('within two years', 'seventy years on')")
    if resolved:
        notes.append("answers itself: it gives both the purpose and the outcome, so the question "
                     "the film exists to answer is already closed")
    if _VAGUE.search(line):
        score = max(0, score - 15)
        notes.append(f"vague filler: {_VAGUE.search(line).group(0)!r}")
    if words > 18:
        score = max(0, score - 10)
        notes.append(f"{words} words; the budget is 18")
    return {"score": score, "patterns": found, "notes": notes, "words": words,
            "proper_nouns": len(propers), "has_number": has_number}


HOOK_RULES = (
    "THE HOOK is one sentence of at most 18 words and it must carry at least three of these four:\n"
    "  CONTRADICTION  two halves in unresolved tension. This is the strongest single signal.\n"
    "  SPECIFICITY    an exact number, year, place or name. 'Twenty-six queens' not 'some bees'.\n"
    "  TIMEFRAME      an explicit clock: 'within two years', 'seventy years later', 'still'.\n"
    "  OPEN QUESTION  it poses, it does not conclude.\n"
    "Do NOT state both what they were trying to achieve AND how it turned out: that closes the "
    "question the film exists to answer. Name the decision and the scale of what followed, and "
    "let the film explain WHY. 'Brazil imported African bees to make more honey, and twenty-six "
    "queens escaped' answers itself; 'Twenty-six queens escaped a Brazilian lab in 1957, and they "
    "never stopped spreading' does not.\n"
    "No vague filler ('something', 'changed everything', 'you won't believe').\n")
