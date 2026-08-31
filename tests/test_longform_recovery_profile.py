"""Scope locks for the Standard long-form recovery profile.

The recovery is deliberately a policy change inside the ordinary landscape explainer. Social owns
quiz/simulation, controlled pilots remain fail-closed, and Evidence Mystery keeps its sourced gate.
"""

import explainer_pipeline as ep


def test_default_standard_landscape_uses_the_stable_profile(monkeypatch):
    monkeypatch.delenv("LONGFORM_PIPELINE_MODE", raising=False)

    assert ep._stable_standard_longform(
        "landscape", "standard_explainer", controlled_pilot=False)


def test_recovery_profile_cannot_capture_neighboring_flows(monkeypatch):
    monkeypatch.delenv("LONGFORM_PIPELINE_MODE", raising=False)

    assert not ep._stable_standard_longform(
        "social", "standard_explainer", controlled_pilot=False), "quiz/simulation are social"
    assert not ep._stable_standard_longform(
        "landscape", "standard_explainer", controlled_pilot=True), "pilots stay fail-closed"
    assert not ep._stable_standard_longform(
        "landscape", "evidence_led_mystery", controlled_pilot=False), "mystery stays sourced"


def test_experimental_override_restores_the_existing_fail_closed_lane(monkeypatch):
    monkeypatch.setenv("LONGFORM_PIPELINE_MODE", "experimental")

    assert not ep._stable_standard_longform(
        "landscape", "standard_explainer", controlled_pilot=False)


def test_research_is_best_effort_only_in_the_stable_profile(monkeypatch):
    monkeypatch.delenv("LONGFORM_RESEARCH_MODE", raising=False)
    assert ep._ordinary_research_mode(True) == "best_effort"
    assert ep._ordinary_research_mode(False) == "required"

    monkeypatch.setenv("LONGFORM_RESEARCH_MODE", "off")
    assert ep._ordinary_research_mode(True) == "off"
    assert ep._ordinary_research_mode(False) == "required"


def test_invalid_research_mode_fails_safe_to_best_effort(monkeypatch):
    monkeypatch.setenv("LONGFORM_RESEARCH_MODE", "surprise-me")

    assert ep._ordinary_research_mode(True) == "best_effort"
