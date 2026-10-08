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

# The listener, present as a word. One regex for the whole pipeline, owned by causal_story.
from causal_story import SECOND_PERSON as _SECOND_PERSON  # noqa: E402
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
# ONE NORMALISER FOR "26" AND "twenty-six". score_hook only asks whether a number is PRESENT;
# the close gate (causal_story._check_close) asks whether the SAME number comes back, so digits,
# compound number words ("twenty-six", "twenty six", "two thousand") and scale words fold to one
# value here, and nowhere else. 1 is excluded on purpose: "one" is a determiner in most hooks
# ("one of them", "her only egg"), and a close forced to say "one" would be matching a word, not
# returning a figure.
_UNITS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|[a-z]+(?:-[a-z]+)?", re.I)


def planted_numbers(text: str) -> set:
    """Every number >= 2 the text speaks, as values: {'twenty-six queens', '26 queens'} -> {26}."""
    values, current, has_number = set(), 0, False
    def _flush():
        nonlocal current, has_number
        if has_number and current >= 2:
            values.add(current)
        current, has_number = 0, False
    for token in _NUMBER_TOKEN.findall(_text(text).replace("—", " ").replace("–", " ")):
        lower = token.lower()
        if lower[0].isdigit():
            _flush()
            try:
                value = float(lower.replace(",", ""))
            except ValueError:
                continue
            if value >= 2 and value == int(value):
                values.add(int(value))
            continue
        parts = lower.split("-")
        handled = False
        for part in parts:
            if part in _UNITS or part in _TENS:
                current += _UNITS.get(part) or _TENS.get(part)
                has_number, handled = True, True
            elif part in _SCALES:
                current = (current or 1) * _SCALES[part]
                has_number, handled = True, True
            elif part == "and" and has_number:
                handled = True
        if not handled:
            _flush()
    _flush()
    return values


_NEGATION = re.compile(r"\b(?:no|without|never had|nor)\s+(?:a\s+|an\s+|any\s+)?([a-z][a-z-]{2,})", re.I)


def negation_nouns(text: str) -> set:
    """The nouns a negation list denies: 'no electricity, no fans, no ice' -> {electricity, fans, ice}."""
    return {m.lower() for m in _NEGATION.findall(_text(text))}


_TIMEFRAME = re.compile(
    r"\b(\d{3,4}|within|since|for \d+|in (?:just )?\w+ (?:years?|months?|decades?)|"
    r"years? later|decades? later|still|today|to this day|ever since|and counting)\b", re.I)
# Our own failure mode: intervention verb plus its named result in one sentence.
_INTERVENTION_VERB = re.compile(
    r"\b(imported|introduced|released|brought|shipped|planted|stocked|killed|removed|"
    r"eradicated|culled|exterminated)\b", re.I)
# "but", "yet" and "until" join an intervention to its outcome as surely as "then" does:
# "Brazil imported African bees, BUT their queens escaped" states the whole film and was scored
# as withholding it.
_RESULT = re.compile(
    r"\b(then|and|so|which|causing|leading to|but|yet|until|-|—)\b.*\b(died|spread|collapsed|destroyed|"
    r"escaped|exploded|vanished|overran|ate|poisoned|wiped|backfired|multiplied)\b", re.I)
_VAGUE = re.compile(
    r"\b(you (?:won'?t|will never) believe|changed everything|this one trick|shocking|"
    r"mind[- ]blowing|insane)\b", re.I)

# Surnames the research names, registered once per run by the pipeline. The two-token regex above
# catches "Warwick Kerr" and nothing else: "You watch Kerr import African bees for Brazilian
# honey" scored 68 with no_institution PASSING (killer bees 2026-10-06, attempt 3), and a lone
# surname is still a named researcher nobody has met. A surname is only known from the dossier,
# so this is a registry, not a regex: "Brazil's" must not read as a person.
_PEOPLE: set[str] = set()
# Capitalised words that start a two-token match but are not a given name.
_NOT_A_GIVEN_NAME = frozenset({
    "the", "in", "on", "at", "by", "for", "a", "an", "and", "but", "when", "after", "before",
    "feral", "greater", "south", "north", "east", "west", "new", "united", "bee", "bees",
    "african", "africanized", "european", "brazilian", "american", "central", "northern",
    "southern", "eastern", "western", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december", "dr", "mr", "mrs", "ms",
    # Sentence openers. "Where European bees..." read as a person named Where European and
    # stopped V14 at the opening identity check (2026-10-08), after the script was paid for.
    "where", "why", "how", "what", "who", "which", "there", "here", "this", "that", "these",
    "those", "then", "so", "now", "imagine", "picture", "suppose", "except", "until", "while",
    "if", "as", "every", "each", "some", "your", "you", "it", "its", "they", "their", "we",
    "our", "one", "two", "no", "not", "nothing", "nobody", "once", "since", "because", "with",
    "without", "from", "into", "over", "under", "across", "through", "only", "even", "still",
})


def register_people(dossier) -> set:
    """Learn the surnames the research names, so a lone 'Kerr' scores as the person it is.

    Reads two-token capitalised names out of the dossier's claim texts (or a plain list of
    claim strings), drops place names and the capitalised adjectives that start a false match
    ("The Africanized", "South African", "Feral Africanized"), and keeps the SURNAME. Replaces
    the previous registry: one run, one dossier.
    """
    claims = dossier.get("claims") if isinstance(dossier, dict) else dossier
    texts = []
    for item in claims or []:
        texts.append(str(item.get("claim") or "") if isinstance(item, dict) else str(item or ""))
    found = set()
    for text in texts:
        for match in _PERSONAL_NAME.findall(text):
            if _PLACE.search(match):
                continue
            first, last = match.split()
            if first.lower() in _NOT_A_GIVEN_NAME or last.lower() in _NOT_A_GIVEN_NAME:
                continue
            found.add(last)
    _PEOPLE.clear()
    _PEOPLE.update(found)
    return set(found)


def _registered_people_in(line: str) -> list:
    return [name for name in sorted(_PEOPLE)
            if re.search(r"\b" + re.escape(name) + r"(?:'s)?\b", line)]


# A FRAME puts the viewer in a role: "Imagine you're a beekeeper in Brazil", "You are a farmer
# in Queensland", "Suppose you keep bees". The three corpus devices cannot tell that from a
# flash-forward ("Imagine you backing away from twenty-six escaping queens" scored 100 on them,
# V11 2026-10-07), so the ladder scorer also asks for the role and refuses an event verb.
_FRAME_ROLE = re.compile(
    r"\b(?:imagine|picture|suppose|say)\s+(?:that\s+)?(?:you'?re|you are|you)\s+(?:a|an|the|one of)\b|"
    r"\byou'?re\s+(?:a|an|the|one of)\b|\byou are\s+(?:a|an|the|one of)\b|"
    r"\byou (?:keep|run|farm|own|work|live)\b", re.I)
_FRAME_EVENT = re.compile(
    r"\b(?:escaped|escaping|imported|released|spread|collapsed|died|destroyed|exploded|"
    r"backfired|killed|removed|lifted|noticed)\b", re.I)


def frame_names_role(line: str) -> bool:
    """Does this sentence give the viewer a role to occupy, without narrating an event?"""
    line = _text(line)
    return bool(_FRAME_ROLE.search(line)) and not _FRAME_EVENT.search(line)


DEVICES = ("viewer_present", "no_institution", "outcome_withheld",
           "denied_or_withheld", "yardstick", "held_clock")
# Weighted so the three the corpus never violates dominate.
_WEIGHTS = {"viewer_present": 28, "no_institution": 20, "outcome_withheld": 20,
            "denied_or_withheld": 14, "yardstick": 10, "held_clock": 8}


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def score_hook(hook: str, *, subject_words: set | None = None, ladder: bool = False) -> dict:
    """Which corpus devices an opening carries, and a 0-100. Deterministic, no provider.

    `ladder`: the sentence is the FRAME of a human-first opening ("Imagine you're a beekeeper in
    Brazil"), not the whole promise. Only the three devices the frame can carry are scored, on
    the same weights re-normalised to 100, and the quantity, yardstick and clock notes are not
    issued: under the ladder the facts arrive where the story reaches them (operator brief,
    2026-10-07), and the number bonus is what pulled "26" and "1956" into sentence one.
    """
    line = _text(hook)
    if not line:
        return {"score": 0, "patterns": {d: False for d in DEVICES},
                "notes": ["no hook"], "words": 0}
    words = len(line.split())

    viewer = bool(_SECOND_PERSON.search(line))
    named = [m for m in _PERSONAL_NAME.findall(line) if not _PLACE.search(m)]
    named += _registered_people_in(line)
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
    if ladder:
        # Equal thirds, so a frame missing ANY of the three required devices lands under the 70
        # contract (67): on the corpus weights a Kerr frame with the viewer in it scored 71. And
        # a frame that names no role -- or narrates an event -- is capped under the contract
        # however many devices it carries.
        frame = ("viewer_present", "no_institution", "outcome_withheld")
        found["frame_role"] = frame_names_role(line)
        score = round(100 * sum(1 for d in frame if found[d]) / len(frame))
        if not found["frame_role"]:
            score = min(score, 50)
    else:
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
    if not found["denied_or_withheld"] and not ladder:
        notes.append("nothing is withheld or denied: name a category instead of the species, or "
                     "kill the obvious explanation first")
    if ladder:
        if not found.get("frame_role"):
            notes.append("the frame gives the viewer no role to occupy, or narrates an event: it "
                         "should read like 'Imagine you're a beekeeper in Brazil' -- a person with a "
                         "practical problem, nothing that has happened yet")
    elif not has_number:
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


# THE HUMAN-FIRST OPENING (operator brief, 2026-10-07). One source of text for the planner and
# the writer. The beats are PLANNING beats, not sentences: a line of narration or a single picture
# may carry two, and the writer combines them as the telling needs.
OPENING_RULES = (
    "THE OPENING. The hook field is NOT a summary of the story; it is the frame: \"Imagine you're a "
    "beekeeper in Brazil, trying to fill jars from bees that struggle in the heat.\" The film opens "
    "inside one person's practical problem, in the second person by default, and reaches the first unintended "
    "consequence before the body of the story begins. Plan it as five beats in `opening`:\n"
    "  frame -- the role the viewer occupies; a role the ledger's events involve. Second person is "
    "the default, not a rule; if the story is told better from beside the person, say so in "
    "opening.voice.\n"
    "  problem -- what this person needs and what prevents it, tangible: something felt, seen or "
    "counted. Cite the claims that establish the obstacle. A factual statement inside a 'you' "
    "sentence ('your bees are European bees') is still a factual statement and must be cited.\n"
    "  solution -- the decision someone makes, and its rationale as the source gives it. The viewer "
    "should UNDERSTAND why the decision was made; they do not have to agree with it. The person "
    "who decides may be named when a claim names them; the viewer's role stays the vantage point.\n"
    "  transition -- the move to where the story turns: the place and the arrangement the claims "
    "describe.\n"
    "  consequence -- the first unintended consequence as the sourced event, including the ordinary "
    "act that caused it. If the ledger gives the actor's reason, include it; if it does not, say "
    "nothing about why and list it in opening.missing_claims. Never supply a motive the sources "
    "do not.\n"
    "  question -- optional: the one question the rest of the film answers, asked once.\n"
    "  callback -- what the close returns to: the opening object (the jars) OR the original human "
    "need (a harvest that pays), whichever the story can honestly pay off.\n"
    "Let the facts enter as the story needs them; a date, a place or a count belongs wherever the "
    "story reaches it, and nothing requires or forbids one in the first sentence. Reach the "
    "consequence as efficiently as the story allows -- there is no fixed length.\n"
    "THE BODY BEGINS AFTER THE CONSEQUENCE. The events you plan for the body continue the story "
    "from the consequence onward. Do not plan the problem, the decision or the escape again as "
    "body events; the opening has spent them. The first body event is what happened next.\n"
    "WHERE TO STAND: choose the viewer's vantage from what the ledger involves, preferring in this "
    "order: the person with the need the plan was meant to serve; the person who made the "
    "ordinary mistake, when a claim says what they saw or knew; a sensation everyone has had that "
    "the story turns on; a belief the viewer already holds that the ledger corrects. Scientists, "
    "officials and named people appear in the story as the facts place them. The hook field is "
    "the frame sentence itself.\n")

OPENING_WRITER_RULES = (
    "THIS BATCH OPENS THE FILM. The plan's opening beats -- frame, problem, solution, transition, "
    "consequence -- are yours to combine: a sentence may carry two, a picture may carry one. Begin "
    "with the frame as planned (it is the hook and is prepended for you; do not write it again). "
    "Make the need tangible early. Give the decision its rationale as the sources give it; the "
    "viewer should understand it. Where the plan lists a missing claim, leave that thing unsaid. "
    "Do not repeat a clause across beats, and do not announce what is coming. Visuals for the "
    "opening show the viewer's vantage from inside it -- hands, tools, the thing they need -- not "
    "the place from outside; required objects are things a paper cut-out can be. The problem lives "
    "in the setup row; the solution and the transition in the intervention row (and the "
    "false_resolution row where there is one); the consequence in the first escalation or hinge "
    "row that follows.")

OPENING_BODY_RULE = (
    "THE BODY PICKS UP WHERE THE OPENING STOPPED: after the consequence. Nothing in these rows "
    "re-tells the problem, the decision or the escape; refer back with an article or a pronoun "
    "(\"those queens\", \"the screens\") and move on.")

# The rules for a FRAME sentence on its own, for the hook-only rewrite under the ladder. The
# rewrite used to send HOOK_RULES (a named actor, a number measured against something the viewer
# owns, a clock held open) and then score the result as a frame -- asking for one thing and
# grading another (flow validation 2026-10-07, item 6). These are the frame's own rules, in the
# order the reference film uses them: the viewer's body first, the role second.
FRAME_RULES = (
    "THE FRAME is the first sentence the viewer hears. It puts the viewer in the role the problem "
    "belongs to, in the second person: \"Imagine you're a beekeeper in Brazil, trying to fill jars "
    "from bees that struggle in the heat.\" It names no institution and no researcher as its "
    "subject, and it narrates nothing that has happened yet -- no import, no escape, no result. "
    "Prefer what the viewer feels, risks or needs over their job title: \"You wake up, and the "
    "air is already trying to kill you\" lands before \"you are an Egyptian builder\" would. A "
    "number or a date belongs here only if the role cannot be felt without it. At most 18 words.")

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
    "  DENY THE OBVIOUS READING. Kill the explanation the viewer already has, and supply nothing "
    "in its place yet: 'that's not even the strangest part', 'most people assume that's because "
    "they were engineered, but that's not quite right', 'nobody checked'. NAME the subject "
    "plainly while you do it: denying a wrong cause is not the same as hedging what the film is "
    "about, and a vague abstraction standing in for the concrete title subject fails a separate "
    "rule.\n"
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
