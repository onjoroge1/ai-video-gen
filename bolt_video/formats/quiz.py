"""Pure creative/timing contract for the rapid-reveal quiz Short."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QuizCreativeContract:
    # Bumped from v2_3 for the retention experiment: same three-round mechanics and timing, new
    # narration voice and a closing card that asks for a score instead of a replay. The string is
    # stored on every render, so it is what lets the next batch be segmented against the v2_3
    # baseline in analytics — an experiment whose arms cannot be told apart afterwards is not one.
    version: str = "rapid_reveal_v2_4"
    # Audience data favored the three-payoff arc: removing the fourth round restores a clean
    # warm-up -> hard -> final-boss escalation. The 2.4-second search window is the proven
    # three-round pace and keeps the default Short near eleven seconds without rushing play.
    max_items: int = 3
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 2.4
    reveal_min_sec: float = 0.8
    reveal_max_sec: float = 1.2
    final_reveal_min_sec: float = 1.6
    # Raised from 2.4s. The closing card is sized from its narration, so the old cap silently
    # clipped any CTA longer than "Tomorrow is harder." — the ending had to be terse because
    # the renderer said so, and it landed abrupt. 3.4s fits an ask *and* a reason at the
    # longest realistic answer word, and gives the payoff room to resolve instead of stopping.
    final_reveal_max_sec: float = 3.6
    progressive_clues: bool = True
    standalone_intro_sec: float = 0.0
    standalone_outro_sec: float = 0.0
    subscribe_teaser_sec: float = 0.0

    def estimated_duration(self, item_count: int, reveal_sec: float = 1.0,
                           final_reveal_sec: float = 1.8) -> float:
        n = clamp_quiz_items(item_count, self.max_items)
        reveal = min(self.reveal_max_sec, max(self.reveal_min_sec, reveal_sec))
        final_reveal = min(self.final_reveal_max_sec,
                           max(self.final_reveal_min_sec, final_reveal_sec))
        return round(n * self.guess_window_sec + max(0, n - 1) * reveal + final_reveal, 2)


QUIZ_V2 = QuizCreativeContract()


def clamp_quiz_items(item_count: int, maximum: int = QUIZ_V2.max_items) -> int:
    return max(2, min(maximum, int(item_count or maximum)))


_COUNT_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


# Measured TTS on this phrasing runs ~16.5 characters per second. Every line that plays over a
# countdown is budgeted at a deliberately slower 15.0, so a projection trips before a real render
# collides with the reveal behind it. The tests import this rather than restating it: the guard
# and the copy it guards were two independent literals, which is one drift away from a silently
# clipped line.
_NARRATION_CHARS_PER_SEC = 15.0


def narration_fits(line: str, window_sec: float) -> bool:
    """Whether a spoken line is projected to fit inside the card it plays over."""
    return len(line) / _NARRATION_CHARS_PER_SEC <= window_sec


def _category_noun(category: str) -> str:
    """The shortest honest name for the thing being guessed.

    The opener now spends its budget on a threat as well as a count, and the category is a free
    parameter interpolated into it: "wild animals" and "ocean animals" are each six characters
    longer than the noun actually carrying the meaning. Taking the last word stays truthful —
    ocean animals are animals — and buys back exactly the room the threat needs.
    """
    words = (category or "things").strip().lower().split()
    return words[-1] if words else "things"


def round_narration(category: str, index: int, total: int) -> str:
    """Narrate the viewer's position in the game, not the mechanics of it.

    The old ladder — "Three animals hiding." / "Round 2. Harder." / "Last one. Nobody gets it." —
    described the format to the viewer. It is accurate and it asks nothing of them. Retention sat
    at 35-46% stayed-to-watch with average percentage viewed above 100%, which says the people who
    stay are happy and the people who leave go early, before any of these lines has paid off.

    So the opener carries a reason to reach round three instead of a description of round one:
    naming the count sets a finish line the viewer can see, and threatening the last round gives
    them something to stay for. The middle round stops announcing its own difficulty and asks for
    attention instead, and the final round is the promise from the opener landing.

    Each line still plays over its own 2.4s countdown, so the opener is built longest-first and
    degrades: a category long enough to push the threat past the window drops the threat rather
    than talking over the first answer. "Last one's diabolical." is one character past the budget
    on the shortest category, which is why it is not the first candidate.
    """
    noun = _category_noun(category)
    count = _COUNT_WORDS.get(total, str(total))
    if index == 1:
        for line in (f"{count} {noun}. Last one's brutal.",
                     f"{count} {noun}. Last one's evil.",
                     f"{count} {noun} hiding."):
            if narration_fits(line, QUIZ_V2.guess_window_sec):
                return line
        return f"{count} {noun}."
    if index == total:
        return "Nah... final boss."
    return "Okay... lock in."


_CLUE_ZOOMS = {
    "medium": (1.85, 1.35, 1.0),
    "hard": (2.10, 1.45, 1.0),
    "expert": (2.35, 1.55, 1.0),
}


def clue_zoom(difficulty: str, stage: int) -> float:
    """Progressively reveal more of the clue over the three timer stages."""
    ladder = _CLUE_ZOOMS.get((difficulty or "hard").strip().lower(), _CLUE_ZOOMS["hard"])
    return ladder[max(0, min(2, int(stage)))]


def tier_label(index: int, total: int) -> str:
    """The on-screen name for a round's difficulty.

    MEDIUM/HARD/EXPERT are the generator's vocabulary, not the viewer's. They describe the item to
    us and say nothing to the person watching — three neutral nouns in a row, where the ladder is
    supposed to feel like a story getting harder. These name the viewer's position in that story
    instead, so the escalation is something they read rather than something we assert.

    The colour still comes from the difficulty, so the green/amber/red climb survives.
    """
    if index <= 1:
        return "WARM-UP"
    if index >= total:
        return "FINAL BOSS"
    if index == 2 and total >= 4:
        return "TOO EASY?"
    return "NO HINTS"


def final_reveal_narration(answer: str) -> str:
    """Spend the closing line on the signal that is not already saturated.

    "Missed one? Go again." asked for the replay, and it worked — average percentage viewed sits
    above 100%. That is precisely the argument against keeping it. The loop is already won, so the
    longest slot in the Short was buying more of a metric with nothing left to give, while
    comments, the one engagement signal this format has never once asked for, stayed flat.

    So the ask moves rather than doubles up. "Be honest" presumes the viewer dropped one, which is
    true for most people on an expert final round, and turns a score into something worth
    admitting instead of a number they keep to themselves. Dropping the words does not cost the
    replay: the closing beat still dissolves into the opening frame, so going again stays free
    whether or not anybody says so.

    "Subscribe" leaves the voice track entirely. The card carries "ROUND 2 · FOLLOW" instead,
    which promises the viewer something rather than assigning them a chore.

    Measured against ``final_reveal_max_sec``: the longest realistic answer projects to ~2.8s
    inside the 3.6s card at the conservative rate this module budgets with.
    """
    return f"{(answer or '').strip()}! Be honest... what'd you get?"


# The bottom rung is the one most people land on and the one they are least likely to type
# unprompted; the top rung is a status claim. Naming both is what turns "drop your score" from a
# request into a multiple-choice question with an answer worth picking.
_SCORE_EMOJI_BOTTOM = "\U0001F62D"
_SCORE_EMOJI_MIDDLE = "\U0001F928"
_SCORE_EMOJI_NEAR_TOP = "\U0001F525"
_SCORE_EMOJI_TOP = "\U0001F410"


def score_tiers(total: int) -> list[tuple[str, str]]:
    """The score ladder the closing card offers the viewer to choose from.

    The emoji are the payload here — "0/3 1/3 2/3 3/3" on its own says nothing and reads as a
    scoreboard for a game already over. They carry no glyph in the display face, so this is drawn
    through the colour-emoji pass; rendered through the normal text path every one of them
    disappears silently and the card still looks deliberate.

    Built from the round count rather than hardcoded, so a longer quiz cannot offer a ladder that
    stops short of a perfect score.
    """
    n = max(1, int(total or 1))
    tiers = []
    for score in range(n + 1):
        if score == n:
            emoji = _SCORE_EMOJI_TOP
        elif score == n - 1:
            emoji = _SCORE_EMOJI_NEAR_TOP
        elif score == 0:
            emoji = _SCORE_EMOJI_BOTTOM
        else:
            emoji = _SCORE_EMOJI_MIDDLE
        tiers.append((f"{score}/{n}", emoji))
    return tiers


# The screen reacts where the narrator does not. Round one's answer is a single word, so its card
# has most of a second with nothing left to say, and a line the voice track never acknowledges is
# funnier than one it delivers — the joke is that nobody on the audio side noticed.
FIRST_REVEAL_REACTION = ("IF YOU MISSED THAT", "\U0001F480")

# The closing card asks for the comment; the voice asks the question that earns it. Splitting them
# is the point — spoken "subscribe" is a chore, where a promised round two is an offer, and the
# spoken slot is worth more spent on "what'd you get?" than on repeating what is already on screen.
#
# Arrows are deliberately absent: the display face has no glyph for "↓" or "→" and PIL does not
# fall back, so both would be drawn as nothing. The middot does exist and carries the same beat.
CLOSING_BANNER = ("DROP YOUR ", "SCORE")
CLOSING_FOOTER = "ROUND 2 · FOLLOW"
