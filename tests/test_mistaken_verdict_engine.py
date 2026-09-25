"""The mistaken_verdict engine and the Nature channel, checked against each other and the corpus.

Every earlier engine was written from imagination and corrected by its first reference. This one
was written FROM its reference (the Oviraptor Short) and the fixture is committed beside it, so
the sequence, the function map, the score row and the channel screen are all pinned to the same
story. A second, filmed reference is what will show what this one got wrong.
"""
import pytest

import causal_story as cs
import event_functions as ef
import illustrated_score
import reference_corpus as rc
import story_engines as se
import topic_fit as tf


# ── engine ─────────────────────────────────────────────────────────────────────────────────────

def test_the_engine_is_registered_and_described_to_the_selector():
    engine = se.get(se.MISTAKEN_VERDICT)
    assert engine["name"] == "The Mistaken Verdict"
    assert engine["closing"] == cs.VERDICT
    assert cs.INTERVENTION not in engine["sequence"], "nobody intervenes in a mistaken verdict"
    assert "NOBODY intervenes" in engine["premise"]
    assert "mistaken_verdict" in se.catalogue()
    assert se.resolve_id("mistaken_verdict") == se.MISTAKEN_VERDICT


def test_the_engine_needs_seven_beats_and_one_escalation():
    engine = se.get(se.MISTAKEN_VERDICT)
    assert engine["min_escalations"] == 1
    assert se.minimum_beats(engine) == 7
    # The principle IS the reveal: a 20% deadline would refuse every story of this shape.
    assert se.mechanism_deadline_pct(engine, 0.20) == se.REVEAL_DEADLINE_PCT


def test_the_function_map_covers_exactly_the_roles_the_engine_requires():
    mapping = ef.map_for(se.MISTAKEN_VERDICT)
    assert mapping is not None
    engine = se.get(se.MISTAKEN_VERDICT)
    mapped_roles = {mapping.role_for(function) for function in mapping.required}
    assert mapped_roles == set(engine["required"]), (mapped_roles, engine["required"])
    assert mapping.derived == (), "every beat of a mistaken verdict is citable; nothing is derived"
    for function in mapping.required:
        assert function in ef.EVENT_FUNCTIONS
        assert function in ef.WHAT_EACH_FUNCTION_IS, f"{function} has no definition for the planner"
    assert mapping.role_for(ef.PARALLEL_CASE) == "generalization"
    assert mapping.role_for(ef.CONTEXT) == "context"


def test_every_engine_has_a_score_row():
    """A new engine without a mood row is scored by the generic default by accident."""
    assert illustrated_score._engines_without_a_score() == []


# ── the reference fixture ──────────────────────────────────────────────────────────────────────

def _oviraptor():
    refs = [r for r in rc.by_engine(se.MISTAKEN_VERDICT) if r.name == "oviraptor_egg_thief_short"]
    assert refs, "fixture missing"
    return refs[0]


def test_the_oviraptor_short_is_the_engines_first_reference():
    assert rc.coverage()[se.MISTAKEN_VERDICT] >= 1
    ref = _oviraptor()
    assert ref.has_measurements
    assert ref.gating_metrics()["mechanism_pct_of_runtime"] < se.REVEAL_DEADLINE_PCT


def test_the_oviraptor_short_validates_under_its_own_engine():
    ref = _oviraptor()
    result = cs.validate_causal_story(ref.story, se.get(se.MISTAKEN_VERDICT))
    assert result["passed"], [e["message"] for e in result["errors"]]
    roles = [step["role"] for step in result["steps"] if not step["continues"]]
    assert roles == ["setup", "false_resolution", "hinge", "mechanism", "escalation",
                     "reversal", "verdict"]


def test_the_fixture_uses_the_maps_functions_in_the_maps_roles():
    ref = _oviraptor()
    mapping = ef.map_for(se.MISTAKEN_VERDICT)
    for step in ref.story["steps"]:
        assert mapping.role_for(step["event_function"]) == step["role"], step["step_id"]


def test_one_reference_means_loose_adherence_not_imitation():
    """With one reference, 'balanced' would mean 'imitate this Short'. The corpus rule holds."""
    assert rc.adherence_for_engine(se.MISTAKEN_VERDICT) == "loose"


# ── the channel ────────────────────────────────────────────────────────────────────────────────

def test_the_nature_channel_is_defined_beside_the_other_two():
    assert list(tf.CHANNELS) == [tf.WORLD, tf.HISTORY, tf.NATURE]
    spec = tf.CHANNELS[tf.NATURE]
    assert spec["name"] == "Bolt Explains Nature"
    assert "terrible parent" in spec["promise"]
    assert "READ as neglect, cruelty, theft or abandonment" in spec["requires"]
    assert "NO human intervention" in spec["requires"]
    assert "belong to WORLD" in spec["excludes"]


def test_every_nature_candidate_hints_one_of_the_channels_two_engines():
    topics = tf.TOPIC_CANDIDATES[tf.NATURE]
    assert len(topics) >= 8
    assert all(t["engine_hint"] in (se.MISTAKEN_VERDICT, se.STRANGE_BEHAVIOUR) for t in topics)
    # The penguin has no recorded accusation and must not be hinted as a verdict story.
    penguin = next(t for t in topics if "penguin" in t["question"])
    assert penguin["engine_hint"] == se.STRANGE_BEHAVIOUR
    assert all(t["status"] == "research_candidate" for t in topics)
    assert "Oviraptor" in topics[0]["question"]
    catalogue = tf.editorial_catalogue()
    nature = next(c for c in catalogue["channels"] if c["id"] == tf.NATURE)
    assert nature["topics"][0]["reference_count"] >= 1


def test_the_screen_knows_the_third_channel_and_keeps_the_animal_tie_rule():
    assert "three documentary channels" in tf._SYSTEM
    assert "ANIMALS WIN TIES" in tf._SYSTEM
    assert "NATURE TAKES ONLY WHAT ANIMALS DO" in tf._SYSTEM
    prompt = tf._prompt("Why does the giant Pacific octopus stop eating once she lays her eggs?",
                        tf.signals("x"))
    assert "world|history|nature|neither" in prompt
    assert "ONE recorded reading" in prompt and "LOOKS like one" in prompt
    assert "Never attribute an accusation nobody recorded" in tf._SYSTEM


# ── the sibling engine: strange_behaviour ──────────────────────────────────────────────────────

def test_strange_behaviour_carries_no_recorded_verdict_and_keeps_the_early_deadline():
    """Split from mistaken_verdict on the emperor penguin draft, whose 'the lists call her the
    worst mother' line was not supported when the lists were read. The shape must not require an
    accusation, and must not let one be invented to satisfy it."""
    engine = se.get(se.STRANGE_BEHAVIOUR)
    assert engine["name"] == "The Strange Behaviour"
    assert cs.FALSE_RESOLUTION not in engine["sequence"], "nothing on the record settled the case"
    assert cs.INTERVENTION not in engine["sequence"]
    assert engine["closing"] == cs.VERDICT and engine["min_escalations"] == 1
    assert "none is invented" in engine["premise"]
    # Stated early, after the behaviour and the constraint: 30%, half the reveal engines' 60%.
    assert se.mechanism_deadline_pct(engine, 0.20) == 0.30
    assert se.minimum_beats(engine) == 6


def test_a_verdict_close_inherits_a_cause_like_a_tool_close():
    """The first penguin script to reach narration failed ORPHAN_STEP on its verdict."""
    import story_compiler as sc

    def beat(bid, role, function, caused_by=""):
        return {"beat_id": bid, "role": role, "causal_role": role, "event_function": function,
                "event": {"text": f"{bid} text", "claim_refs": [f"c_{bid}"]},
                "caused_by": caused_by, "chapter": 1, "scope": "primary_story"}
    beats = [beat("e1", "setup", ef.BEHAVIOUR_OBSERVED), beat("e2", "hinge", ef.CONSTRAINT_FOUND, "e1"),
             beat("e3", "mechanism", ef.FUNCTION_SHOWN, "e2"), beat("e4", "escalation", ef.EVIDENCE_MOUNTS, "e3"),
             beat("e5", "reversal", ef.OUTCOME_FOR_YOUNG, "e4")]
    out = sc.presentation_beats(beats, se.STRANGE_BEHAVIOUR)
    close = out[-1]
    assert close["role"] == "verdict" and close["caused_by"] == "e5"
    assert all(b["caused_by"] for b in out[1:]), [b["beat_id"] for b in out if not b["caused_by"]]


def test_strange_behaviour_function_map_matches_its_roles_and_its_close_is_a_device():
    """The first live episode died when the planner sourced a verdict: a close restates, it does
    not assert, and the fact model lets a verdict cite nothing. So the close is not a function."""
    mapping = ef.map_for(se.STRANGE_BEHAVIOUR)
    engine = se.get(se.STRANGE_BEHAVIOUR)
    assert {mapping.role_for(f) for f in mapping.required} == set(engine["required"]) - {engine["closing"]}
    assert "verdict" not in mapping.to_role.values()
    assert mapping.derived == ()
    assert ef.BEHAVIOUR_OBSERVED in mapping.required and ef.FUNCTION_SHOWN in mapping.required
    assert ef.VERDICT_RECORDED not in mapping.to_role, "a verdict function would invite inventing one"
    for f in mapping.required:
        assert f in ef.EVENT_FUNCTIONS and f in ef.WHAT_EACH_FUNCTION_IS
    assert "narration device" in mapping.role_meanings["verdict"]


def test_the_compiler_appends_the_engines_closing_device_not_always_a_tool():
    """Every mapped engine used to get a `tool` close; the Nature engines close on a verdict."""
    import story_compiler as sc

    def beat(bid, role, function, caused_by=""):
        return {"beat_id": bid, "role": role, "causal_role": role, "event_function": function,
                "event": {"text": f"{bid} text", "claim_refs": [f"c_{bid}"]},
                "caused_by": caused_by, "chapter": 1, "scope": "primary_story"}
    beats = [beat("e1", "setup", ef.BEHAVIOUR_OBSERVED),
             beat("e2", "hinge", ef.CONSTRAINT_FOUND, "e1"),
             beat("e3", "mechanism", ef.FUNCTION_SHOWN, "e2"),
             beat("e4", "escalation", ef.EVIDENCE_MOUNTS, "e3"),
             beat("e5", "reversal", ef.OUTCOME_FOR_YOUNG, "e4")]
    out = sc.presentation_beats(beats, se.STRANGE_BEHAVIOUR)
    roles = [b["role"] for b in out]
    assert roles[-1] == "verdict" and roles.count("verdict") == 1
    assert roles.count("hinge") == 1, "the planner's constraint IS the hinge; no device beside it"
    close = out[-1]
    assert close.get("presentation_device") == "verdict" and close["event"]["claim_refs"] == []
    assert "attribute no verdict to anyone" in close["beat"]


def test_a_failing_repeat_of_a_repeatable_role_is_pruned_while_another_holder_stands():
    """The penguin episode died with three supported escalations because a fourth was narrowed
    past its function. A role is required; no particular repeat of it is."""
    import story_fact_model as sfm

    def beat(bid, role, function):
        return {"beat_id": bid, "role": role, "causal_role": role, "event_function": function,
                "event": {"text": f"{bid} text", "claim_refs": ["c1"]}, "scope": "primary_story"}
    beats = [beat("e1", "setup", ef.BEHAVIOUR_OBSERVED), beat("e4", "escalation", ef.EVIDENCE_MOUNTS),
             beat("e5", "escalation", ef.EVIDENCE_MOUNTS), beat("e7", "escalation", ef.EVIDENCE_MOUNTS),
             beat("e8", "reversal", ef.OUTCOME_FOR_YOUNG)]
    kept, pruned = sfm.prune_unsupported_optional(beats, {"e7"}, se.STRANGE_BEHAVIOUR)
    assert [b["beat_id"] for b in kept] == ["e1", "e4", "e5", "e8"]
    assert pruned[0]["beat_id"] == "e7" and "repeat" in pruned[0]["reason"]
    # When every holder fails, nothing is pruned and the role is reported missing as before.
    kept, pruned = sfm.prune_unsupported_optional(beats, {"e4", "e5", "e7"}, se.STRANGE_BEHAVIOUR)
    assert [b["beat_id"] for b in kept] == ["e1", "e4", "e5", "e7", "e8"] and pruned == []
    # A singleton required role is never pruned while it is the only holder.
    kept, pruned = sfm.prune_unsupported_optional(beats, {"e8"}, se.STRANGE_BEHAVIOUR)
    assert any(b["beat_id"] == "e8" for b in kept) and pruned == []
    # ...but a failing SECOND copy of a singleton is: the fifth penguin sheet filed the crop
    # secretion as a reversal beside the real one, and the mislabelled copy blocked the run.
    with_dup = beats + [beat("e7x", "reversal", ef.OUTCOME_FOR_YOUNG)]
    kept, pruned = sfm.prune_unsupported_optional(with_dup, {"e7x"}, se.STRANGE_BEHAVIOUR)
    assert [b["beat_id"] for b in kept] == ["e1", "e4", "e5", "e7", "e8"]
    assert pruned[0]["beat_id"] == "e7x" and "repeat" in pruned[0]["reason"]


def test_the_nature_channel_admits_both_shapes_and_forbids_invented_reputations():
    spec = tf.CHANNELS[tf.NATURE]
    assert "MISTAKEN VERDICT" in spec["requires"] and "STRANGE BEHAVIOUR" in spec["requires"]
    assert "INVENTED REPUTATIONS" in spec["excludes"]
    import explainer_pipeline as ep
    system = ep._causal_topic_system(tf.NATURE)
    assert "ONE OF TWO SHAPES" in system and "NEVER invent a reputation" in system


def test_the_nature_channel_restricts_the_engines_the_selector_may_offer():
    """A selector choosing among all eight engines can hand a penguin a bounty engine."""
    import explainer_pipeline as ep

    assert tf.engines_for_channel(tf.NATURE) == (se.MISTAKEN_VERDICT, se.STRANGE_BEHAVIOUR)
    assert tf.engines_for_channel(tf.WORLD) is None and tf.engines_for_channel("") is None
    assert set(ep._feasible_engines(180, channel=tf.NATURE)) == {se.MISTAKEN_VERDICT, se.STRANGE_BEHAVIOUR}
    assert len(ep._feasible_engines(180, channel=tf.WORLD)) == len(se.ENGINES)
    # The run sets the context variable; the selector reads it when no channel is passed.
    token = ep._TOPIC_CHANNEL.set(tf.NATURE)
    try:
        assert set(ep._feasible_engines(240)) == {se.MISTAKEN_VERDICT, se.STRANGE_BEHAVIOUR}
    finally:
        ep._TOPIC_CHANNEL.reset(token)
    assert len(ep._feasible_engines(240)) == len(se.ENGINES)


def test_a_wrong_engine_from_the_model_falls_back_inside_the_channel(monkeypatch):
    """The model answers 'backfiring_solution' for a Nature question; the selector must not take it."""
    import explainer_pipeline as ep
    from types import SimpleNamespace

    reply = SimpleNamespace(content=[SimpleNamespace(text='{"engine":"backfiring_solution","why":"x"}')],
                            usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **k: reply)))
    token = ep._TOPIC_CHANNEL.set(tf.NATURE)
    try:
        chosen = ep._select_story_engine("Why does the emperor penguin leave her only egg?", 180)
    finally:
        ep._TOPIC_CHANNEL.reset(token)
    assert chosen in (se.MISTAKEN_VERDICT, se.STRANGE_BEHAVIOUR)


def test_the_penguin_story_validates_under_strange_behaviour():
    """The Nature channel's first Short, compiled by hand to the sibling engine."""
    import json
    from pathlib import Path
    payload = json.loads(Path("spec/emperor_penguin_story.json").read_text())["story"]
    assert payload["engine"] == se.STRANGE_BEHAVIOUR
    result = cs.validate_causal_story(payload, se.get(se.STRANGE_BEHAVIOUR))
    assert result["passed"], [e["message"] for e in result["errors"]]
    mapping = ef.map_for(se.STRANGE_BEHAVIOUR)
    for step in payload["steps"]:
        if step["role"] == "verdict":
            assert step["event_function"] == "", "the close is a device, not a sourced fact"
            continue
        assert mapping.role_for(step["event_function"]) == step["role"], step["step_id"]


def test_the_nature_topic_brief_demands_a_recorded_verdict_not_an_intervention():
    import explainer_pipeline as ep

    system = ep._causal_topic_system(tf.NATURE)
    assert "A RECORDED VERDICT" in system
    assert "CORRECTING EVIDENCE" in system
    assert "NAME THE RIGHT SPECIES" in system
    assert "NO HUMAN PROGRAMME" in system
    assert "ONE intervention, bounded in time and place" not in system
    assert "the recorded verdict" in system          # the JSON field the generator must fill


@pytest.mark.parametrize("channel", [tf.WORLD, tf.HISTORY])
def test_the_older_channels_keep_their_intervention_rule(channel):
    import explainer_pipeline as ep

    assert "ONE intervention, bounded in time and place" in ep._causal_topic_system(channel)
