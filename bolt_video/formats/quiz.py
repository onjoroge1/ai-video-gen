"""Pure creative/timing contract for the rapid-reveal quiz Short."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QuizCreativeContract:
    version: str = "rapid_reveal_v2_1"
    max_items: int = 3
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 2.4
    reveal_min_sec: float = 0.8
    reveal_max_sec: float = 1.2
    final_reveal_min_sec: float = 1.6
    final_reveal_max_sec: float = 2.4
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
    return max(2, min(maximum, int(item_count or 3)))


def round_narration(category: str, index: int, total: int) -> str:
    category = (category or "things").strip().lower()
    if index == 1:
        count = "Two" if total == 2 else "Three"
        return f"{count} {category}. Guess fast."
    if index == total:
        return "Final one. Expert."
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


def final_reveal_narration(answer: str) -> str:
    """Place the reason-to-return inside the payoff instead of adding a post-game card.

    "New quiz daily. Subscribe." stated a channel fact and then asked a favour; neither half
    gave the viewer a reason. A promise does: "tomorrow is harder" is the reason, and the
    on-screen card carries the ask, so the two channels do not repeat each other.

    Kept deliberately short. The final card's length is derived from this line and capped at
    ``final_reveal_max_sec``, so a longer line is silently clipped — measured, the older
    "Tomorrow is harder. Subscribe." wording overran the cap on any answer from "Pangolin" up.
    """
    return f"{(answer or '').strip()}! Tomorrow is harder."
