"""Contradictory instructions in one prompt, found by a test instead of by a render.

This pipeline has now paid four times to discover the same class of defect at runtime:

  - two mechanism deadlines in one prompt                       twelve renders
  - story_direction asked the hook to hedge while causal_rules  three of four drafts
    demanded a named actor, in the same prompt                  hedged the subject
  - F3 told the planner an event may be empty while the spine   the spine failed for a
    gate required the mechanism to carry one                    missing mechanism
  - the chapter marker was written by two functions and         markers animated as
    validated by a third                                        $1.12 of video

The shape is always the same: an invariant is stated at more than one site, the sites drift, and
the model resolves the conflict by picking one -- usually not the one that was measured. Nothing
about this needs a model to detect. Each invariant either has ONE authoritative site, or is
inserted from ONE normalized value at every site; both are decidable by reading the assembled
string.

This is deliberately not a general "does the prompt contradict itself" checker. It is a list of
invariants that have actually broken, checked exactly. A rule is added here when it costs
something, not when it seems plausible.
"""
from __future__ import annotations

import re

import story_fact_model as _sfm


def _single_value(prompt: str, patterns: tuple, name: str, why: str) -> list[dict]:
    """Every site that states this invariant must state the same value."""
    found: dict[str, list[str]] = {}
    for pattern in patterns:
        for match in re.finditer(pattern, prompt, re.I):
            value = next((group for group in match.groups() if group), "")
            if value:
                found.setdefault(value, []).append(match.group(0)[:70])
    if len(found) > 1:
        return [{"invariant": name, "code": "CONFLICTING_VALUES", "why": why,
                 "detail": {value: sites for value, sites in found.items()}}]
    return []


def _forbidden(prompt: str, phrases: tuple, name: str, why: str) -> list[dict]:
    hits = [phrase for phrase in phrases if phrase.lower() in prompt.lower()]
    return [{"invariant": name, "code": "RETIRED_INSTRUCTION_PRESENT", "why": why,
             "detail": hits}] if hits else []


def _stated_once(prompt: str, phrase: str, name: str, why: str) -> list[dict]:
    count = prompt.lower().count(phrase.lower())
    if count > 1:
        return [{"invariant": name, "code": "STATED_MORE_THAN_ONCE", "why": why,
                 "detail": {"phrase": phrase, "count": count}}]
    return []


def lint(prompt: str) -> list[dict]:
    """Return every contradiction found in one assembled prompt. Empty means clean."""
    prompt = prompt or ""
    issues: list[dict] = []

    # The mechanism deadline. Two of these once disagreed and the run was rejected either way.
    issues += _single_value(
        prompt,
        (r"pct MUST be under (\d+)", r"pct must be under (\d+)", r"under pct (\d+)",
         r"Mechanism deadline: (\d+)% of spoken runtime"),
        "mechanism_deadline",
        "the model obeys one deadline and is rejected by the other")

    # The hook. A retired instruction still steers if it is quoted, even to forbid it.
    issues += _forbidden(
        prompt,
        ("shape, not the topic", "where you mean the specific thing",
         "let the concrete subject arrive", "name the shape"),
        "hook_concreteness",
        "asking for an abstraction cancels the demand for a named actor")
    issues += _stated_once(prompt, "named actor", "hook_concreteness",
                           "an accreted rule is a rule the model has to reconcile")

    # Events. F3 permits an empty event; spine coverage requires one for the load-bearing roles.
    if "event.text" in prompt and 'event.text = ""' in prompt:
        carve = re.search(r"does NOT apply to the [a-z]+ load-bearing roles:\s*([a-z_,\s]+?)\.",
                          prompt, re.I)
        named = {role.strip() for role in (carve.group(1) if carve else "").split(",")
                 if role.strip()}
        missing = set(_sfm.REQUIRED_SPINE_ROLES) - named
        if missing:
            issues.append({"invariant": "event_requirement", "code": "ROLE_MAY_BE_EVENT_FREE",
                           "why": "a required role told it may omit its event will omit it, and "
                                  "the spine then fails for a role the planner was told to skip",
                           "detail": sorted(missing)})

    # The cast. The schema asks for Alex; the cast block forbids Alex.
    if "NO recurring characters" in prompt and re.search(r'"human_subject"\s*:\s*"Alex"', prompt):
        issues.append({"invariant": "cast_policy", "code": "SCHEMA_REQUIRES_FORBIDDEN_CAST",
                       "why": "the schema pins a named host the cast block forbids, so the model "
                              "must decide which of the two is real",
                       "detail": ['"human_subject":"Alex"', "CAST: ... NO named host"]})

    # The chapter marker. Written by two functions, validated by a third; they must agree it is
    # spoken at all.
    speaks = "say the number out loud" in prompt.lower()
    silent = any(phrase in prompt.lower() for phrase in
                 ("do not say the chapter", "never speak the chapter", "no spoken chapter"))
    if speaks and silent:
        issues.append({"invariant": "chapter_announcement", "code": "SPOKEN_AND_SILENT",
                       "why": "one site asks for the number out loud and another forbids it",
                       "detail": []})
    return issues


def report(issues: list[dict]) -> str:
    if not issues:
        return "No contradictions found."
    lines = [f"{len(issues)} contradiction(s):"]
    for issue in issues:
        lines.append(f"  ! [{issue['code']}] {issue['invariant']}: {issue['why']}")
        lines.append(f"      {issue['detail']}")
    return "\n".join(lines)
