"""Pure creative/timing contract for the rapid-reveal quiz Short."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QuizCreativeContract:
    version: str = "rapid_reveal_v2"
    max_items: int = 3
    first_clue_at_sec: float = 0.0
    guess_window_sec: float = 2.4
    reveal_min_sec: float = 0.8
    reveal_max_sec: float = 1.2
    standalone_intro_sec: float = 0.0
    standalone_outro_sec: float = 0.0
    subscribe_teaser_sec: float = 0.0

    def estimated_duration(self, item_count: int, reveal_sec: float = 1.0) -> float:
        n = clamp_quiz_items(item_count, self.max_items)
        reveal = min(self.reveal_max_sec, max(self.reveal_min_sec, reveal_sec))
        return round(n * (self.guess_window_sec + reveal), 2)


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
