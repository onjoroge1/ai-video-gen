"""What a winning first sentence actually does, derived from a corpus rather than asserted.

An earlier version of this file scored four patterns taken from a practitioner write-up about
viral hooks: contradiction, specificity, timeframe, and leaving a question open. Our hooks then
scored 55-70 and the operator still rejected them, correctly. Scoring the right axes badly is
one thing; scoring the wrong axes is another.

So this was rebuilt against seven first minutes from the channel style the operator wants (the
"why don't we eat X" explainers). Four independent readings of that corpus -- linguistic,
attentional, comparative and screenwriting -- converged on the same account, which is why it is
worth trusting:

  "Here's a strange fact to start with. The animal we're talking about today can produce up to
   860 volts. YOUR home electrical outlet runs at 110 to 240."
  "200 years ago, whale oil was everywhere. YOUR lamp ran on it. YOUR candles were made from it."
  "Look at the back of YOUR hand. Whatever shade YOUR skin is, one thing is certain. It isn't green."
  "All right, picture this. YOU'RE alone in the woods and 30 feet away there's a wolf."
  "...alligator still isn't sitting next to chicken and pork in YOUR grocery store."

Against ours:

  "Queensland's sugar bureau imported cane toads to kill beetles - then native predators died."
  "Warwick Kerr imported African bees for honey-why did 26 escaped swarms spread across the Americas?"

The difference is not polish. Theirs open ON THE LISTENER and withhold; ours open on an
institution and deliver the entire causal chain in sentence one, so there is nothing left to
find out and nobody being told. Our pipeline has measured `second_person: 0.00 per 100 words`
on every single run and that warning went unactioned for the whole project.

SIX DEVICES, scored here, the first three of which are effectively required:

  VIEWER PRESENT     a literal you/your inside the hook. 5 of 7 winners, 0 of 4 of ours.
  NO INSTITUTION     the grammatical subject is not a bureau, a ministry or a named researcher.
  OUTCOME WITHHELD   it does not state the intervention AND its named result in one sentence.
  DENIED OR WITHHELD a denial of the obvious reading ("not even the strangest part") or a
                     category standing in for the name ("the animal we're talking about today").
  YARDSTICK          a number is measured against something the viewer owns, never left bare.
  HELD CLOCK         a duration joined to something that still has not resolved.

POV framing is NOT scored as its own device. The corpus achieves it through the perceptual
imperative ("Look at", "picture this"), which is counted, and a literal "POV:" prefix would read
as cheap on a sourced history channel.
"""
from __future__ import annotations

import re

# The listener, present as a word.
_SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself|you're|you've|you'll|you'd)\b", re.I)
# An institution or a named researcher standing where the listener should be.
_INSTITUTION = re.compile(
    r"\b(bureau|government|governments|ministry|department|agency|authorities|officials|"
    r"commission|council|administration|service|institute|programme|program|board|committee|"
    r"scientists|researchers|biologists|geneticist|entomologist)\b", re.I)
# Two capitalised tokens in a row: a personal name. NOT excluded at sentence start -- that is
# exactly where ours put them ("Warwick Kerr brought African bees to Brazil..."), and an earlier
# version of this regex carried a (?<!^) guard that scored that hook as institution-free.
# A place name alone is fine ("Brazil wanted more honey"); a PERSON as the actor is not.
_PERSONAL_NAME = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
# Place names are two-word-capitalised sometimes but are not actors; allow the common ones.
_PLACE = re.compile(r"\b(South Africa|North America|South America|New Zealand|United States|"
                    r"Rio Claro|Sao Paulo|S\u00e3o Paulo|Costa Rica|Puerto Rico|New Mexico)\b")
# The verbs that put the viewer in the frame.
_IMPERATIVE = re.compile(
    r"^\s*(?:all right,?\s+|ok(?:ay)?,?\s+|so,?\s+|now,?\s+)?"
    r"(look|picture|imagine|take|watch|count|hold|keep|think|consider|try)\b", re.I)
# Denying the obvious reading, or naming the shape of what is being withheld.
_DENIAL = re.compile(
    r"\b(not even the \w+est|isn'?t (?:even )?(?:the|why|because)|that'?s not (?:quite )?(?:right|it)|"
    r"has (?:almost )?nothing to do with|was never the|not for the reason|here'?s (?:a|the) "
    r"(?:strange|odd|weird) (?:fact|thing|part)|here'?s the (?:contradiction|catch|problem|clue)|"
    r"the (?:first|real) clue|nobody|no one|never|still isn'?t|still has ?n'?t|and somehow)\b", re.I)
# A category used instead of the name.
_WITHHELD = re.compile(
    r"\b(the (?:animal|creature|species|thing|fish|insect|bird) (?:we'?re|we are|this|in|on)\b|"
    r"this one (?:animal|fish|insect|creature)|something|one of them|the thing)\b", re.I)
# A number is only useful if it is measured against something.
_COMPARISON = re.compile(
    r"\b(than|enough to|as much as|times|compared|versus|vs|against|while|whereas|but|yet|"
    r"your|the same|instead of|more than|less than|beats?)\b", re.I)
_NUMBER = re.compile(
    r"\b(\d[\d,]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion)\b", re.I)
_TIMEFRAME = re.compile(
    r"\b(\d{3,4}|within|since|for \d+|in (?:just )?\w+ (?:years?|months?|decades?)|"
    r"years? later|decades? later|still|today|to this day|ever since|and counting)\b", re.I)
# Our own failure mode: intervention verb plus its named result in one sentence.
_INTERVENTION_VERB = re.compile(
    r"\b(imported|introduced|released|brought|shipped|planted|stocked|killed|removed|"
    r"eradicated|culled|exterminated)\b", re.I)
_RESULT = re.compile(
    r"\b(then|and|so|which|causing|leading to|-|—)\b.*\b(died|spread|collapsed|destroyed|"
    r"escaped|exploded|vanished|overran|ate|poisoned|wiped|backfired|multiplied)\b", re.I)
_VAGUE = re.compile(
    r"\b(you (?:won'?t|will never) believe|changed everything|this one trick|shocking|"
    r"mind[- ]blowing|insane)\b", re.I)

DEVICES = ("viewer_present", "no_institution", "outcome_withheld",
           "denied_or_withheld", "yardstick", "held_clock")
# Weighted so the three the corpus never violates dominate.
_WEIGHTS = {"viewer_present": 28, "no_institution": 20, "outcome_withheld": 20,
            "denied_or_withheld": 14, "yardstick": 10, "held_clock": 8}


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def score_hook(hook: str, *, subject_words: set | None = None) -> dict:
    """Which corpus devices an opening carries, and a 0-100. Deterministic, no provider."""
    line = _text(hook)
    if not line:
        return {"score": 0, "patterns": {d: False for d in DEVICES},
                "notes": ["no hook"], "words": 0}
    words = len(line.split())

    viewer = bool(_SECOND_PERSON.search(line))
    named = [m for m in _PERSONAL_NAME.findall(line) if not _PLACE.search(m)]
    institution = bool(_INSTITUTION.search(line)) or bool(named)
    has_number = bool(_NUMBER.search(line))
    spoils = bool(_INTERVENTION_VERB.search(line)) and bool(_RESULT.search(line))
    found = {
        "viewer_present": viewer,
        "no_institution": not institution,
        "outcome_withheld": not spoils,
        "denied_or_withheld": bool(_DENIAL.search(line)) or bool(_WITHHELD.search(line))
                              or bool(_IMPERATIVE.search(line)),
        # A bare number with nothing to measure it against is the thing the corpus never does.
        # A hook with NO number used to pass this vacuously, which inflated a 78 that had no
        # figure in it at all. The device is "a quantity made legible", so no quantity is not a
        # pass: the corpus puts a sourced number in almost every opening.
        "yardstick": has_number and bool(_COMPARISON.search(line)),
        "held_clock": bool(_TIMEFRAME.search(line)),
    }
    score = sum(w for d, w in _WEIGHTS.items() if found[d])

    notes = []
    if not viewer:
        notes.append("the listener is not in it: no 'you' or 'your'. Every winning opening puts "
                     "the viewer's body, home or position in the first breath")
    if institution:
        notes.append("an institution or a named researcher is the subject; the corpus never opens "
                     "on one, because nobody has met them")
    if spoils:
        notes.append("it states the intervention AND its result, so the film has nothing left "
                     "to tell")
    if not found["denied_or_withheld"]:
        notes.append("nothing is withheld or denied: name a category instead of the species, or "
                     "kill the obvious explanation first")
    if not has_number:
        notes.append("no sourced quantity: the corpus puts a figure in almost every opening "
                     "('860 volts', '2,000 pounds', '6,000 kinds of mammals')")
    elif not found["yardstick"]:
        notes.append("a bare number with nothing to measure it against ('860 volts' needs 'your "
                     "home outlet runs at 110')")
    if _VAGUE.search(line):
        score = max(0, score - 20)
        notes.append(f"clickbait filler: {_VAGUE.search(line).group(0)!r}")
    if words > 18:
        score = max(0, score - 10)
        notes.append(f"{words} words; the budget is 18")
    return {"score": score, "patterns": found, "notes": notes, "words": words,
            "has_number": has_number}


HOOK_RULES = (
    "THE HOOK is the first sentence the viewer hears, at most 18 words, and it is spoken TO ONE "
    "PERSON. Our films have opened on institutions for three videos running and the pipeline has "
    "measured second-person address at zero on every one of them.\n"
    "Three things it MUST do:\n"
    "  1. PUT THE LISTENER IN IT. Use 'you' or 'your' literally. Their body, their home, their "
    "kitchen, their country, or a position you ask them to imagine. 'Your lamp ran on it.' "
    "'Look at the back of your hand.' 'You're alone in the woods.'\n"
    "  2. NO INSTITUTION OR NAMED RESEARCHER AS THE SUBJECT. Never open on 'Queensland's sugar "
    "bureau', 'Warwick Kerr' or 'the government'. Nobody has met them. The viewer is the subject.\n"
    "  3. WITHHOLD THE OUTCOME. Do not state the intervention and its result in the same "
    "sentence. 'Brazil imported bees and twenty-six queens escaped' is the whole film in one "
    "line; there is nothing left to watch for.\n"
    "Then at least one of:\n"
    "  DENY THE OBVIOUS READING, or name the shape of what you are not saying yet: 'that's not "
    "even the strangest part', 'the animal we're talking about today', 'most people assume that's "
    "because... but that's not quite right'.\n"
    "  MEASURE A NUMBER AGAINST SOMETHING THE VIEWER OWNS. Never a bare figure: '860 volts' lands "
    "only beside 'your home outlet runs at 110 to 240'.\n"
    "  HOLD A CLOCK OPEN: a duration joined to something that still has not resolved -- 'sixty "
    "years later it still isn't in your grocery store'.\n"
    "If the ledger gives you ONE PAIR OF HANDS, use them instead of a country. The bee dossier "
    "carries 'in October 1957, a local beekeeper noticed the queen excluders and removed them' -- "
    "that is the whole disaster in one gesture, and the hook we shipped said 'Brazil'. A person "
    "doing a small thing beats an institution doing a large one, as long as a claim puts them "
    "there.\n"
    "Every number, date and name in the hook must come from a cited claim; an invented one is "
    "refused by a later gate, and a duration you COMPUTED from two sourced dates (1957 to 1990 "
    "becoming 'thirty-three years') counts as invented. No clickbait filler.\n")
