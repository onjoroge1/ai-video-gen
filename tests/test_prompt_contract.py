"""The prompts must not contradict themselves, checked here rather than discovered by a render.

Four times now an invariant has been stated at two sites, the sites have drifted, and the model has
resolved the conflict by picking the wrong one: two mechanism deadlines (twelve renders), the hook
asked to hedge and to name an actor (three of four drafts hedged), F3 permitting an empty event
while the spine required one (the Hanoi mechanism), and the chapter marker written by two
functions and validated by a third ($1.12 of animated markers).
"""
import pytest

import explainer_pipeline as ep
import prompt_contract as pc
import story_fact_model as sfm


class _Abort(Exception):
    pass


def _prompt(monkeypatch, **kwargs) -> str:
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            raise _Abort

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(_Abort):
        ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", 14, **kwargs)
    return seen["prompt"]


@pytest.mark.parametrize("causal_lane", (True, False))
def test_the_assembled_beat_sheet_prompt_is_self_consistent(monkeypatch, causal_lane):
    issues = pc.lint(_prompt(monkeypatch, causal_lane=causal_lane))
    assert not issues, pc.report(issues)


def test_the_linter_catches_two_disagreeing_mechanism_deadlines():
    """The one that cost twelve renders."""
    issues = pc.lint("its pct MUST be under 20 ... Mechanism deadline: 35% of spoken runtime")
    assert [i["code"] for i in issues] == ["CONFLICTING_VALUES"]


def test_the_linter_catches_a_required_role_told_its_event_may_be_empty():
    """F3, before the carve-out. The planner obeyed it and the spine failed for the mechanism."""
    issues = pc.lint('event.text ... A beat that asserts no history gets event.text = "" '
                     'and no claim_refs.')
    assert [i["code"] for i in issues] == ["ROLE_MAY_BE_EVENT_FREE"]
    assert set(issues[0]["detail"]) == set(sfm.REQUIRED_SPINE_ROLES)


def test_the_linter_catches_a_schema_that_pins_a_forbidden_cast():
    """Found live on this linter's first run against the real prompt."""
    issues = pc.lint('{"human_subject":"Alex"} ... CAST: this story has NO recurring characters '
                     'and NO named host.')
    assert [i["code"] for i in issues] == ["SCHEMA_REQUIRES_FORBIDDEN_CAST"]


def test_the_linter_catches_a_retired_hook_instruction_even_as_a_quotation():
    """Naming the phrasing you forbid still puts that phrasing in the context."""
    issues = pc.lint("Never describe the shape, not the topic.")
    assert [i["code"] for i in issues] == ["RETIRED_INSTRUCTION_PRESENT"]


def test_a_clean_prompt_reports_nothing():
    assert pc.lint("Write a story. Its pct MUST be under 20.") == []
    assert pc.report([]) == "No contradictions found."
