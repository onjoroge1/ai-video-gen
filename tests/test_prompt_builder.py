from bolt_video.prompts.builder import PromptBuilder, PromptPriority
from board_pipeline import build_tv_review_extraction_prompt


def test_prompt_sections_are_sorted_by_precedence_and_stable_within_priority():
    prompt = (PromptBuilder("test")
              .add("creative", "third", PromptPriority.CREATIVE)
              .add("facts", "second-a", PromptPriority.FACTS)
              .add("safety", "first", PromptPriority.SAFETY)
              .add("facts two", "second-b", PromptPriority.FACTS)
              .render())
    assert prompt.index("SAFETY") < prompt.index("FACTS") < prompt.index("CREATIVE")
    assert prompt.index("second-a") < prompt.index("second-b")


def test_tv_review_prompt_puts_accuracy_and_json_contract_before_format_rules():
    prompt = build_tv_review_extraction_prompt()
    assert prompt.index("SAFETY AND ACCURACY") < prompt.index("OUTPUT CONTRACT") < prompt.index("FORMAT RULES")
    assert "supplied narration" in prompt
    assert "SPOILER SCOPE" in prompt
