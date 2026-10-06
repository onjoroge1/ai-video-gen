"""Regression tests for the flow audit of the delivered bee film (2026-10-06).

Each test names the measured failure it guards against. The delivered film ran 103 seconds
against a 300-second request, scored Script 59, Packaging 44, and three later attempts died on
the evidence-state gate; six parallel investigators traced every one of those to a specific
line, and these tests hold the lines.
"""
import json
import os
from types import SimpleNamespace

import pytest

import explainer_pipeline as ep
import hook_patterns as hp
import longform_evidence as le
import longform_research as lr

# tests/ is not a package; borrow the phase-3 fixture by path.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "_phase3", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_longform_evidence_phase3.py"))
_phase3 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_phase3)
_evidence_script = _phase3._script


# --- the evidence-state gate -------------------------------------------------------------------

def test_the_plan_records_what_the_writer_was_asked_for():
    plan = le.compile_evidence_plan(_evidence_script())
    for scene in plan["scenes"]:
        assert "states_requested" in scene
        fixture_scene = _evidence_script()["scenes"][scene["scene_index"]]
        words = len(le._text(fixture_scene.get("narration")).split())
        assert scene["states_requested"] == le.states_required_for_words(words)


def test_the_opening_ceiling_cannot_sit_below_the_writers_ask():
    """Three attempts died with 7 and 8 states against a ceiling of 6, after the prompt asked
    for 7 and 8 and said there was no upper band. The writer did what it was told."""
    plan = le.compile_evidence_plan(_evidence_script())
    scene = next(s for s in plan["scenes"] if s["opening"])
    seven = [dict(scene["states"][0], state_id=f"x{i}", asset_id=f"a{i}") for i in range(7)]
    scene["states"] = seven
    scene["state_capacity"] = 9
    scene["states_requested"] = 7
    report = le.validate_evidence_plan(plan)
    assert "opening_state_count" not in {e["code"] for e in report["errors"]}, (
        "seven states were asked for and seven were refused")
    # A legacy plan with no recorded ask keeps the old ceiling, so nothing loosens by accident.
    scene["states_requested"] = 0
    report = le.validate_evidence_plan(plan)
    codes = {e["code"] for e in report["errors"]}
    assert "opening_state_count" in codes
    message = next(e["message"] for e in report["errors"] if e["code"] == "opening_state_count")
    assert "7 evidence states" in message and "capacity 9" in message, (
        "the message must carry the numbers; two identical sentences named no scene for a day")


def test_the_evidence_plan_gate_persists_a_diagnostic_before_raising():
    """The one pre-spend gate that left no file; three failures were reconstructed by luck."""
    source = open(ep.__file__, encoding="utf-8").read()
    block = source[source.index('"Evidence-state plan failed before TTS/image spend: "') - 1200:]
    block = block[:block.index('"Evidence-state plan failed before TTS/image spend: "') + 400]
    assert 'stage="evidence-plan"' in block
    assert "_persist_semantic_failure(" in block
    assert "scene {item.get('scene')}" in block
    # ...and it must run BEFORE the raise, or it is dead code that still satisfies the strings.
    assert block.index("_persist_semantic_failure(") < block.index(
        '"Evidence-state plan failed before TTS/image spend: "')


# --- the runtime sink ------------------------------------------------------------------------

def _repair_fixture(original_words: int):
    narration = " ".join(["Officials", "paid", "a", "bounty", "per", "rat", "tail", "and", "the",
                          "city's", "sewers", "slowly", "filled", "with", "rats"][:original_words])
    script = {"hook": "A hook.",
              "scenes": [{"scene_id": "event_01", "beat_id": "event_01", "evidence_id": "e01",
                          "narration": narration + ".",
                          "event": {"text": "Officials paid a bounty per rat tail."},
                          "claim_refs": [{"claim_id": "c08", "evidence_id": "e01",
                                          "narration_phrase": narration + "."}]}]}
    dossier = {"claims": [{"claim_id": "c08", "claim": "A bounty was paid per rat tail."}]}
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_01",
                          "severity": "material",
                          "message": "asserts more than its event",
                          "unsupported_details": ["the sewers filled"]}]}
    return script, dossier, report


def _repair_provider(monkeypatch, repaired_narration: str, claim_id: str = "c08"):
    # The claim_id must be one the dossier allows, or the repair silently returns the original
    # script -- which once made a "held" test pass for the wrong reason.
    body = json.dumps({"scenes": [{"scene": 1, "evidence_id": "e01",
                                   "narration": repaired_narration,
                                   "claim_refs": [{"claim_id": claim_id, "evidence_id": "e01",
                                                   "narration_phrase": repaired_narration}]}]})
    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=body)],
                               usage=SimpleNamespace(input_tokens=300, output_tokens=40))
    monkeypatch.setattr(ep, "_claude",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_a_repair_that_cuts_a_scene_to_its_event_sentence_is_held(monkeypatch):
    """566 words went into the claim repair and 222 came out: thirteen scenes rewritten to their
    one-sentence events. The repair prompt said "Preserve ... length". The trim and the fact-check
    both refuse a cut over a third; this was the one rewriting stage that did not."""
    script, dossier, report = _repair_fixture(15)
    _repair_provider(monkeypatch, "Officials paid a bounty per rat tail.")
    repaired, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert cost > 0, "the call was made and is billed"
    assert repaired["scenes"][0]["narration"] == script["scenes"][0]["narration"]
    held = repaired.get("_repair_held")
    assert held and held[0]["before"] == 15 and held[0]["after"] == 7


def test_a_repair_of_similar_length_is_still_applied(monkeypatch):
    script, dossier, report = _repair_fixture(15)
    fixed = "Officials paid a bounty per rat tail and the city's sewers kept filling with rats."
    _repair_provider(monkeypatch, fixed)
    repaired, _ = ep.repair_claim_join_failures(script, dossier, report)
    assert repaired["scenes"][0]["narration"] == fixed
    assert not repaired.get("_repair_held")


def test_the_repair_ignores_soft_findings(monkeypatch):
    """The trim already skipped soft findings; the rewrite did not, and the two disagreed."""
    script, dossier, report = _repair_fixture(15)
    report["errors"][0]["severity"] = "soft"
    _repair_provider(monkeypatch, "Officials paid a bounty.")
    repaired, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert cost == 0.0 and repaired is script


# --- packaging -------------------------------------------------------------------------------

def test_api_safe_tags_match_what_the_uploader_accepts():
    tags = ["26 queen bee mistake", "European bees disappeared Africanized bees",
            "entomology", "Entomology", 'bad "quote" tag', "killer bees explained"]
    out = ep.api_safe_tags(tags)
    assert out == ["26 queen bee mistake", "entomology", "bad quote tag", "killer bees explained"]
    assert all(len(t) <= ep.TAG_MAX_CHARS for t in out)


def _description_provider(monkeypatch):
    def create(**kwargs):
        body = json.dumps({
            "summary": "What went wrong, plainly.\n\nThe film follows it.",
            "chapters": [{"scene": 1, "title": "The import"}, {"scene": 4, "title": "The escape"},
                         {"scene": 8, "title": "The spread"}, {"scene": 12, "title": "Today"}],
            "in_this_video": ["why the bees escaped", "how far they spread"],
            "questions_answered": ["Why are Africanized bees dangerous?"],
            "hashtags": ["KillerBees", "BeeHistory"],
            "tags": ["killer bees explained", "a tag that is far too long to survive the api"]})
        return SimpleNamespace(content=[SimpleNamespace(text=body)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=10))
    monkeypatch.setattr(ep, "_claude",
                        lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_a_short_long_form_film_still_ships_sources_and_chapters(monkeypatch, tmp_path):
    """The 102.6s film lost CHAPTERS, IN THIS VIDEO, QUESTIONS and SOURCES to `total >= 120`
    while five cited URLs sat in description_sources(). Packaging scored 44."""
    _description_provider(monkeypatch)
    durs = [7.9] * 13
    path = ep.generate_description("Title", "Hook.", "transcript", str(tmp_path),
                                   question="q", video_format="landscape",
                                   scene_narr=["narration"] * 13, scene_durs=durs,
                                   sources=[("okstate.edu", "https://okstate.edu/x")])
    text = open(path, encoding="utf-8").read()
    assert "SOURCES" in text and "okstate.edu" in text
    assert "CHAPTERS" in text, "13 scenes 7.9s apart give more than three chapter slots"
    assert "IN THIS VIDEO" in text
    assert "far too long to survive" not in text, "the Tags line is API-safe"


def test_a_two_scene_film_keeps_its_sources_without_chapters(monkeypatch, tmp_path):
    _description_provider(monkeypatch)
    path = ep.generate_description("Title", "Hook.", "transcript", str(tmp_path),
                                   question="q", video_format="landscape",
                                   scene_narr=["a", "b"], scene_durs=[5.0, 5.0],
                                   sources=[("ncbi", "https://ncbi.nlm.nih.gov/x")])
    text = open(path, encoding="utf-8").read()
    assert "SOURCES" in text
    assert "CHAPTERS" not in text, "two starts five seconds apart are not three YouTube chapters"


# --- the hook ----------------------------------------------------------------------------------

def test_but_joins_an_intervention_to_its_outcome():
    """"Brazil imported African bees, but their queens escaped" is the whole film in one line
    and was scored as withholding it."""
    graded = hp.score_hook("Brazil imported African bees for honey, but their queens escaped.")
    assert graded["patterns"]["outcome_withheld"] is False


def test_the_hook_ceiling_is_the_dossier_not_only_the_surviving_beats():
    """"You cannot tell Africanized bees from European bees by sight" is a verified claim that no
    compiled beat carried; it scored 68 and was refused as HOOK_EXCEEDS_STORY."""
    seen = []

    def judge(payload):
        seen.append(payload)
        return {"verdict": "entailed", "reason": "stub"}

    script = {"hook": "You cannot tell them apart by sight.",
              "scenes": [{"beat_id": "event_1", "causal_role": "setup", "narration": "Bees arrived.",
                          "event": {"text": "African honey bees arrived in Brazil.",
                                    "claim_refs": ["c1"]}}]}
    dossier = {"claims": [
        {"claim_id": "c1", "claim": "African honey bees were imported into Brazil in 1956."},
        {"claim_id": "c2", "claim": "Africanized and European honey bees cannot be told apart by eye."}]}
    lr.validate_story_fact_model(script, dossier, judge=judge, cache={})
    hook_ceilings = [p.get("event", "") for p in seen
                     if p.get("kind") == "fidelity" and "rhetorical address" in p.get("event", "")]
    assert hook_ceilings, "the hook was never judged"
    assert "cannot be told apart by eye" in hook_ceilings[0], (
        "a dossier claim no beat cites must still be inside the hook's ceiling")


# --- review findings on commit 5d14bad ---------------------------------------------------------

def test_a_held_scene_one_does_not_rederive_the_hook(monkeypatch):
    """Three reviewers independently: when scene 1's rewrite is held, the hook block read the
    UNCHANGED opener and installed the refused hook or the cold open as the hook. The delivered
    film opened on Warwick Kerr for exactly this reason."""
    hook = "Officials paid a cent per rat tail and bred more rats."
    cold = "Your city's sewers filled with rats that nobody ever counted."
    body = ("Hanoi's new sewers created ideal habitat for rats, and the colonial administration "
            "offered a bounty for every tail that was handed in at the municipal office.")
    script = {"hook": hook, "_cold_open": cold,
              "scenes": [{"scene_id": "event_01", "beat_id": "event_01", "evidence_id": "e01",
                          "narration": f"{hook} {cold} {body}",
                          "event": {"text": "Hanoi's new sewers created ideal habitat for rats."},
                          "claim_refs": [{"claim_id": "c04", "evidence_id": "e01",
                                          "narration_phrase": body}]}]}
    dossier = {"claims": [{"claim_id": "c04", "claim": "The sewers created rat habitat."}]}
    report = {"errors": [{"code": "HOOK_EXCEEDS_STORY", "scene": "hook",
                          "message": "promises more", "unsupported_details": ["a cent per tail"]}]}
    _repair_provider(monkeypatch, "Hanoi's sewers made habitat for rats.", claim_id="c04")
    repaired, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert cost > 0
    assert repaired.get("_repair_held"), "the collapsed body must be HELD, not silently refused"
    assert repaired["scenes"][0]["narration"] == script["scenes"][0]["narration"], "held"
    assert repaired["hook"] == hook, "the hook must not be re-derived from an unrepaired opener"


def test_dropping_only_the_refused_hook_is_not_compression(monkeypatch):
    """Scene 1 carries hook + cold open; a repair that removes just the refused hook is a 20%
    cut of the scene but a 0% cut of the body the event governs, and must be applied."""
    hook = "Officials paid a cent per rat tail and bred more rats."
    cold = "Your city's sewers filled with rats that nobody ever counted."
    body = ("Hanoi's new sewers created ideal habitat for rats, and the colonial administration "
            "offered a bounty for every tail handed in at the municipal office.")
    script = {"hook": hook, "_cold_open": cold,
              "scenes": [{"scene_id": "event_01", "beat_id": "event_01", "evidence_id": "e01",
                          "narration": f"{hook} {cold} {body}",
                          "event": {"text": "Hanoi's new sewers created ideal habitat for rats."},
                          "claim_refs": [{"claim_id": "c04", "evidence_id": "e01",
                                          "narration_phrase": body}]}]}
    dossier = {"claims": [{"claim_id": "c04", "claim": "The sewers created rat habitat."}]}
    report = {"errors": [{"code": "HOOK_EXCEEDS_STORY", "scene": "hook",
                          "message": "promises more", "unsupported_details": ["a cent per tail"]}]}
    _repair_provider(monkeypatch, f"{cold} {body}", claim_id="c04")
    repaired, _ = ep.repair_claim_join_failures(script, dossier, report)
    assert repaired["scenes"][0]["narration"] == f"{cold} {body}"
    assert not repaired.get("_repair_held")


def test_the_slot_plan_speaks_the_schemas_vocabulary():
    """Asked for "escalation: 13 event(s)" the planner labelled the steps `context` and the film
    compiled to seven scenes. The rows now name the event_function the schema accepts."""
    import story_compiler as sc
    import story_template as st
    plan = st.role_counts("removed_keystone", 300)
    prompt = sc.factual_plan_prompt("q", 300, 20, "removed_keystone", slot_plan=plan)
    assert "population_responds" in prompt and "hidden_link" in prompt
    assert "escalation: 13 event(s)" not in prompt, "role names are not what the schema accepts"
    assert f"Return EXACTLY {sum(plan.values())} factual events" in prompt


def test_a_derived_role_is_the_compilers_and_is_not_asked_for():
    """backfiring_solution derives its mechanism; no event_function produces one, and the same
    prompt forbids supplying it. Asking for one forced a wrong label or a short count."""
    import story_compiler as sc
    import story_template as st
    plan = st.role_counts("backfiring_solution", 300)
    assert plan.get("mechanism", 0) == 0
    assert sum(plan.values()) + 3 == st.target_scene_count(300), "hinge + tool + derived mechanism"
    prompt = sc.factual_plan_prompt("q", 300, 20, "backfiring_solution", slot_plan=plan)
    assert "mechanism: 1 event" not in prompt
    assert f"Return EXACTLY {sum(plan.values())} factual events" in prompt


def test_the_ask_is_measured_on_the_words_the_writer_counted():
    """A 49-word opening scene asked for 7 and the writer returned 8; a repair cut it to 40 and
    the recomputed ask said 6 -- a false number in the diagnostic and a ceiling below the ask."""
    script = _evidence_script()
    scene = script["scenes"][0]
    scene["_words_as_written"] = 49
    plan = le.compile_evidence_plan(script)
    assert plan["scenes"][0]["states_requested"] == le.states_required_for_words(49)


def test_an_opening_scene_is_trimmed_to_the_ceiling_the_validator_applies():
    """The writer is told there is no upper band; the validator has one. Compile now trims an
    opening scene to that ceiling, so the gate can only fail on the floor."""
    script = _evidence_script()
    scene = script["scenes"][0]
    base = dict(scene["visual_beats"][0]) if isinstance(scene.get("visual_beats", [None])[0], dict) \
        else {"anchor_phrase": "x"}
    scene["visual_beats"] = [dict(base, anchor_phrase=f"beat {i}") for i in range(12)]
    scene["narration"] = " ".join(["word"] * 45)
    plan = le.compile_evidence_plan(script)
    report = le.validate_evidence_plan(plan)
    assert "opening_state_count" not in {e["code"] for e in report["errors"]}


def test_the_final_hook_contract_applies_only_to_a_spoken_hook():
    """Default and social lanes carry a description hook nobody hears; scoring it against the
    spoken-opening contract degraded every such run for a line that never shipped."""
    source = open(ep.__file__, encoding="utf-8").read()
    idx = source.index("import hook_patterns as _hp_final")
    assert 'if script.get("_compiled_story"):' in source[idx - 400:idx]


def test_publish_blockers_are_reported_apart_from_quality_degradation():
    source = open(ep.__file__, encoding="utf-8").read()
    assert '"publish_blockers": publish_blockers,' in source
    idx = source.index('publish_blockers.append("rendered contract says publishable: false"')
    assert 'reasons.append("rendered contract says publishable' not in source
