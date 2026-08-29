"""Pure creative/timing contract for the rapid-reveal quiz Short."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QuizCreativeContract:
    version: str = "rapid_reveal_v2_2"
    # Four rounds at a shorter window. A generated take on this format fitted four payoffs into
    # ten seconds against our three, on a ~1.4s guess window, and read as markedly faster for it.
    # Reward frequency is what the viewer feels; 1.8s keeps the clue lookable while adding a
    # fourth payoff, and every line below had to shrink to stay inside it.
    max_items: int = 4
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 1.8
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


def round_narration(category: str, index: int, total: int) -> str:
    """Lines are hard-bounded by ``guess_window_sec`` — each plays over its own countdown, and a
    longer line collides with the reveal that follows it. The opener used to run 2.21s inside a
    2.4s window, where "Three animals are hiding in the wild. The last one fools almost everyone."
    runs 4.39s and would talk straight over the first answer.

    So the promise is split rather than dropped. The opener states the search; "this one fools
    everyone" moves to the final round, where it doubles as a re-hook at the point a viewer is
    most likely to leave, instead of being spent in the first two seconds.

    The count was ``"Two" if total == 2 else "Three"``, which was true only while the format was
    capped at three rounds. At four it made the narration contradict the video on the opening
    line — the voice promising three animals over four — and it would have done so silently,
    because nothing downstream compares the spoken count against ``len(items)``.

    Every line then had to shrink for the 1.8s window: at the measured ~16.5 characters/sec the
    old opener needed 2.4s and would have talked over the first answer. "are hiding" lost its
    verb and the final round lost "This fools", which cost the lines nothing they were carrying.
    """
    category = (category or "things").strip().lower()
    if index == 1:
        count = _COUNT_WORDS.get(total, str(total))
        return f"{count} {category} hiding."
    if index == total:
        return "Last one. Nobody gets it."
    return f"Round {index}. Harder."


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
    """Ask for the replay the loop is about to make effortless.

    The ending is where the curve falls, and "Subscribe — tomorrow's quiz is harder" worked
    against that. It asks for a standing commitment, points at a video that does not exist yet,
    and in doing so announces that this one is over — spending the longest line in the short on
    the moment we least want the viewer thinking about leaving.

    The closing beat now dissolves into the opening frame, so a replay costs the viewer nothing:
    they are already watching it. Naming that action turns the moment of peak satisfaction into
    the next view rather than an exit, and it plays to what this format already wins on —
    average percentage viewed sits above 100% because people replay it.

    "Missed one?" supplies the reason. It presumes an imperfect score, which is true for most
    viewers on an expert final round, and makes going again a way to settle it rather than a
    favour. The on-screen card still carries the subscribe ask, so the spoken and written
    channels complement each other instead of repeating.

    Measured against ``final_reveal_max_sec``: at the ~16.5 characters/sec this TTS runs, the
    longest realistic answer lands near 2.1s inside the 3.6s card — about a second shorter than
    the line it replaces, so it shortens the ending as well as changing what it says.
    """
    return f"{(answer or '').strip()}! Missed one? Go again."
