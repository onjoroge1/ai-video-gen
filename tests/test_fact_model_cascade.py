"""The cascade, and the golden fixture that measures claim typing when research learns to do it.

Order is the point. Structure is free and decides most bindings; entailment is paid and should only
ever see what survived. Buying an opinion on whether a mechanism claim supports "residents bred
cobras" is waste once the type system has said a mechanism claim cannot evidence an escalation.
"""
import json
from pathlib import Path

import story_fact_model as sfm

GOLDEN = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "fact_model" /
     "cobra_events_golden.json").read_text(encoding="utf-8"))


def _hand_labelled_claims():
    claims = {c["claim_id"]: dict(c) for c in GOLDEN["claims"]}
    for claim_id, kind in GOLDEN["hand_labelled_claim_kinds"].items():
        if claim_id in claims:
            claims[claim_id]["claim_kind"] = kind
    return claims


def _beats():
    return [dict(scene, role=scene["role"]) for scene in GOLDEN["scenes"]]


# --- the golden control ---------------------------------------------------------------------------

def test_the_hand_labelled_control_reproduces_its_recorded_errors():
    """The measurement that makes machine claim-typing checkable.

    When research emits claim_kind itself, run this same validation with the machine labels. Codes
    that DISAPPEAR are the interesting ones: a label that makes a real error vanish has not fixed
    the script, it has learned to pass the gate.
    """
    issues = sfm.validate_structure(
        _beats(), GOLDEN["claims_by_parallel_case"], _hand_labelled_claims())
    got: dict = {}
    for issue in issues:
        got.setdefault(issue["beat_id"], set()).add(issue["code"])

    expected = {beat: set(codes) for beat, codes in GOLDEN["expected_structural_codes"].items()}
    assert got == expected


def test_the_two_correct_bindings_stay_clean():
    """The check discriminates rather than overfiring.

    c12 is cited by eight beats and is wrong on six. Scene 4 is the hinge, which accepts mechanism
    evidence; scene 5 is the mechanism beat itself. Both are correct uses of the same claim.
    """
    issues = sfm.validate_structure(
        _beats(), GOLDEN["claims_by_parallel_case"], _hand_labelled_claims())
    flagged = {issue["beat_id"] for issue in issues}
    assert "scene_4" not in flagged
    assert "scene_5" not in flagged


# --- the cascade spends nothing on what structure already rejected --------------------------------

def test_no_judge_is_bought_for_a_structurally_rejected_beat():
    calls = []

    def judge(payload):
        calls.append(payload)
        return {"verdict": "entailed", "unsupported_details": [], "reason": ""}

    report = sfm.validate_cascade(
        _beats(), _hand_labelled_claims(), GOLDEN["claims_by_parallel_case"], judge=judge)

    judged = {payload.get("event") for payload in calls}
    for beat in GOLDEN["expected_structural_codes"]:
        scene = next(s for s in GOLDEN["scenes"] if s["beat_id"] == beat)
        text = (scene.get("event") or {}).get("text")
        if text:
            assert text not in judged, f"{beat} was judged despite failing structure"
    assert set(report["skipped_for_structure"]) == set(GOLDEN["expected_structural_codes"])


def test_fidelity_is_not_bought_when_the_event_has_no_support():
    """The ceiling must exist before anything can be measured against it."""
    seen = []

    def judge(payload):
        seen.append(payload["kind"])
        return {"verdict": "unsupported", "unsupported_details": ["x"], "reason": "no"}

    beat = {"beat_id": "b1", "role": "escalation", "scope": "primary_story",
            "event": {"text": "Residents bred cobras.", "claim_refs": ["c1"]},
            "narration": "A pest became livestock."}
    sfm.validate_cascade([beat], {"c1": {"claim": "Something else entirely."}}, judge=judge)
    assert seen == ["evidence"], "fidelity was bought for an unsupported event"


def test_a_clean_beat_reaches_both_boundaries():
    seen = []

    def judge(payload):
        seen.append(payload["kind"])
        return {"verdict": "entailed", "unsupported_details": [], "reason": ""}

    beat = {"beat_id": "b1", "role": "escalation", "scope": "primary_story",
            "event": {"text": "Residents bred cobras.", "claim_refs": ["c1"]},
            "narration": "A pest became livestock."}
    report = sfm.validate_cascade([beat], {"c1": {"claim": "Residents bred cobras.",
                                                  "claim_kind": "event"}}, judge=judge)
    assert seen == ["evidence", "fidelity"]
    assert report["passed"] is True


def test_a_discourse_beat_costs_nothing():
    """No event means nothing to evidence and nothing to exceed."""
    calls = []
    beat = {"beat_id": "b1", "role": "escalation", "event": {"text": "", "claim_refs": []},
            "narration": "And that changed everything."}
    report = sfm.validate_cascade([beat], {}, judge=lambda p: calls.append(p))
    assert calls == []
    assert report["passed"] is True


def test_an_outage_stops_the_cascade_without_becoming_a_content_failure():
    """A provider outage must not be reported as a sourcing verdict, or repaired as one."""
    def boom(_payload):
        raise RuntimeError("credit balance is too low")

    beat = {"beat_id": "b1", "role": "escalation", "scope": "primary_story",
            "event": {"text": "Residents bred cobras.", "claim_refs": ["c1"]},
            "narration": "A pest became livestock."}
    report = sfm.validate_cascade([beat], {"c1": {"claim": "Residents bred cobras."}}, judge=boom)
    assert report["evidence"] == [] and report["fidelity"] == []
    assert len(report["unavailable"]) == 1
    assert report["unavailable"][0]["stage"] == "evidence"
    assert report["passed"] is False


# --- an abstention is not a pass -------------------------------------------------------------------

def _clean_beat(**over):
    beat = {"beat_id": "b1", "role": "escalation", "scope": "primary_story",
            "event": {"text": "Residents bred cobras.", "claim_refs": ["c1"]},
            "narration": "A pest became livestock."}
    beat.update(over)
    return beat


def _ok_judge(_payload):
    return {"verdict": "entailed", "unsupported_details": [], "reason": ""}


def test_a_confident_correct_kind_is_a_clean_structural_pass():
    report = sfm.validate_cascade(
        [_clean_beat()], {"c1": {"claim": "Residents bred cobras.", "claim_kind": "event",
                                 "claim_kind_confidence": 0.95}}, judge=_ok_judge)
    assert report["structure_status"] == sfm.STRUCTURE_PASS
    assert report["indeterminate_kinds"] == []


def test_an_unknown_kind_does_not_read_as_a_clean_pass():
    """The failure mode this exists to prevent.

    A classifier that quietly degrades emits more `unknown`, CLAIM_KIND_MISMATCH falls to zero, and
    the reports look like an improvement while the paid judge silently carries the whole load.
    """
    report = sfm.validate_cascade(
        [_clean_beat()], {"c1": {"claim": "Residents bred cobras.", "claim_kind": "unknown"}},
        judge=_ok_judge)
    assert report["structure_status"] == sfm.STRUCTURE_PASS_WITH_UNKNOWN_KIND
    assert report["beats_with_indeterminate_kinds"] == ["b1"]
    row = report["indeterminate_kinds"][0]
    assert row["kind_gate"] == "indeterminate"
    assert row["requires_semantic_validation"] is True


def test_a_doubted_kind_is_indeterminate_not_enforced():
    report = sfm.validate_cascade(
        [_clean_beat()], {"c1": {"claim": "Residents bred cobras.", "claim_kind": "mechanism",
                                 "claim_kind_confidence": 0.2}}, judge=_ok_judge)
    assert report["structure_status"] == sfm.STRUCTURE_PASS_WITH_UNKNOWN_KIND
    assert report["structural"] == [], "a doubted label should not enforce a mismatch"


def test_an_abstention_does_not_block_a_legitimate_event():
    """Indeterminate must not become a way to fail good work either."""
    report = sfm.validate_cascade(
        [_clean_beat()], {"c1": {"claim": "Residents bred cobras.", "claim_kind": "unknown"}},
        judge=_ok_judge)
    assert report["passed"] is True
    assert report["skipped_for_structure"] == []


def test_a_real_mismatch_still_outranks_an_abstention():
    report = sfm.validate_cascade(
        [_clean_beat()], {"c1": {"claim": "x", "claim_kind": "mechanism",
                                 "claim_kind_confidence": 0.99}}, judge=_ok_judge)
    assert report["structure_status"] == sfm.STRUCTURE_FAIL


# --- the hinge must move something ------------------------------------------------------------------

def test_a_hinge_whose_state_does_not_change_is_caught():
    """The stronger invariant behind the wording detector.

    A model can write "The lesson was suddenly obvious: incentives always beat intentions" and match
    no forbidden phrase. What it cannot do is claim a turn while leaving the situation identical.
    """
    beat = {"beat_id": "h", "role": "hinge",
            "event": {"text": "The count never fell.", "claim_refs": ["c1"]},
            "changes_state": {"from": "the bounty is working", "to": "the bounty is working"}}
    codes = {i["code"] for i in sfm.validate_structure([beat])}
    assert "HINGE_CHANGES_NOTHING" in codes


def test_a_hinge_that_moves_the_model_is_fine():
    beat = {"beat_id": "h", "role": "hinge",
            "event": {"text": "The count never fell.", "claim_refs": ["c1"]},
            "changes_state": {"from": "the bounty is working",
                              "to": "the bounty is paying for the wrong thing"}}
    codes = {i["code"] for i in sfm.validate_structure([beat])}
    assert "HINGE_CHANGES_NOTHING" not in codes


def test_the_hook_is_judged_against_the_story_not_against_beat_one():
    """Measured on the Hanoi render: a true, cited hook was reported as an unsupported claim.

    finalize_narration prepends the spoken hook to scene 1, so the fidelity boundary compared a
    promise about the whole video with the single event that scene carried -- one about sewers.
    "French officials paid a bounty for every dead rat, then watched Hanoi breed more rats" is
    sourced twice over and mentions neither sewers nor anything in that beat.
    """
    import longform_research as lr

    hook = "Officials paid a bounty per rat tail, then watched the city breed more rats."
    script = {"hook": hook, "scenes": [
        {"scene_id": "event_01", "causal_role": "setup",
         "narration": f"{hook} Hanoi's proud new sewers became a rat paradise.",
         "event": {"text": "Hanoi's new sewers created ideal habitat for rats.",
                   "claim_refs": ["c04"]}},
        {"scene_id": "event_02", "causal_role": "intervention",
         "narration": "So officials paid a bounty per rat tail.",
         "event": {"text": "Authorities announced a bounty paid per rat tail.",
                   "claim_refs": ["c08"]}},
        {"scene_id": "event_03", "causal_role": "reversal",
         "narration": "On the outskirts, people bred rats to earn it.",
         "event": {"text": "People bred rats on the outskirts to earn the bounty.",
                   "claim_refs": ["c14"]}}]}
    dossier = {"claims": [
        {"claim_id": "c04", "claim": "The sewers created ideal rat habitat.", "verified": True},
        {"claim_id": "c08", "claim": "A bounty was paid per rat tail.", "verified": True},
        {"claim_id": "c14", "claim": "People bred rats to earn the bounty.", "verified": True}]}

    judged = []

    def judge(payload, **kwargs):
        judged.append(payload)
        return {"verdict": "entailed", "supported_core": "", "unsupported_details": []}

    report = lr.validate_story_fact_model(script, dossier, judge=judge, cache={}, cost_sink=[])
    assert not [e for e in report["errors"] if e["code"] == "HOOK_EXCEEDS_STORY"]
    fidelity = [p for p in judged if p.get("kind") == "fidelity"]

    # Scene 1 was measured WITHOUT the hook glued to it.
    scene_one = [p for p in fidelity if "proud new sewers" in p["narration"]]
    assert scene_one and hook not in scene_one[0]["narration"], \
        "the hook must not be judged as an assertion about the sewers beat"

    # And it WAS measured, against the union of the events the spine establishes.
    hook_check = [p for p in fidelity if p["narration"] == hook]
    assert hook_check, "the hook is judged, not merely excused"
    assert "bred rats" in hook_check[0]["event"] and "sewers" in hook_check[0]["event"]


def test_a_hook_that_promises_more_than_the_story_delivers_still_fails():
    """Lifting the hook out of beat one must not become a way of exempting it."""
    import longform_research as lr

    hook = "The bounty was cancelled and the rats vanished overnight."
    script = {"hook": hook, "scenes": [
        {"scene_id": "event_01", "causal_role": "setup", "narration": f"{hook} The sewers filled.",
         "event": {"text": "Hanoi's new sewers created ideal habitat for rats.",
                   "claim_refs": ["c04"]}}]}
    dossier = {"claims": [{"claim_id": "c04", "claim": "The sewers created rat habitat.",
                           "verified": True}]}

    def judge(payload, **kwargs):
        if payload.get("narration") == hook:
            return {"verdict": "unsupported", "supported_core": "",
                    "unsupported_details": ["the cancellation", "the rats vanishing"]}
        return {"verdict": "entailed", "supported_core": "", "unsupported_details": []}

    report = lr.validate_story_fact_model(script, dossier, judge=judge, cache={}, cost_sink=[])
    codes = [e["code"] for e in report["errors"]]
    assert "HOOK_EXCEEDS_STORY" in codes and not report["passed"]


def test_the_hook_ceiling_excludes_events_that_failed_their_own_evidence():
    """A hook cannot be justified by a beat the evidence boundary already rejected."""
    import longform_research as lr

    hook = "People bred rats to earn the bounty."
    script = {"hook": hook, "scenes": [
        {"scene_id": "event_01", "causal_role": "setup", "narration": f"{hook} The sewers filled.",
         "event": {"text": "People bred rats on the outskirts.", "claim_refs": ["c14"]}}]}
    dossier = {"claims": [{"claim_id": "c14", "claim": "Unrelated.", "verified": True}]}
    seen = []

    def judge(payload, **kwargs):
        seen.append(payload)
        if payload.get("kind") == "evidence":
            return {"verdict": "unsupported", "supported_core": "", "unsupported_details": ["all"]}
        return {"verdict": "entailed", "supported_core": "", "unsupported_details": []}

    report = lr.validate_story_fact_model(script, dossier, judge=judge, cache={}, cost_sink=[])
    # The only event failed its evidence, so it cannot appear in the hook's ceiling. With nothing
    # left, the hook is reported as exceeding the story rather than quietly excused.
    assert not [p for p in seen if p.get("narration") == hook and "bred rats" in p["event"]], \
        "an unsupported event must not raise the hook's ceiling"
    assert "HOOK_EXCEEDS_STORY" in [e["code"] for e in report["errors"]]


def test_the_hook_may_draw_on_the_claims_behind_the_supported_events():
    """The events state the proxy; the story a viewer is promised starts with the announcement.

    Measured: a hook saying officials "paid Hanoi residents for rats" was flagged for implying
    whole rats, because the mechanism event says the reward was paid for a severed tail. The
    announcement -- "a bounty on every dead rat" -- is a separate verified claim, and the judge's
    own supported_core handed the same sentence back. Bounded by the spine: only claims cited by
    events that passed.
    """
    import longform_research as lr

    hook = "Officials paid Hanoi residents for rats, then residents bred rats to get paid."
    script = {"hook": hook, "scenes": [
        {"scene_id": "event_04", "causal_role": "intervention",
         "narration": f"{hook} A bounty appeared.",
         "event": {"text": "The reward was paid for a severed rat tail.", "claim_refs": ["c08"]}}]}
    dossier = {"claims": [{"claim_id": "c08", "verified": True,
                           "claim": "In April 1902 the authorities announced a bounty on every "
                                    "dead rat."}]}
    seen = []

    def judge(payload, **kwargs):
        seen.append(payload)
        return {"verdict": "entailed", "supported_core": "", "unsupported_details": []}

    lr.validate_story_fact_model(script, dossier, judge=judge, cache={}, cost_sink=[])
    ceiling = next(p["event"] for p in seen
                   if p.get("kind") == "fidelity" and p["narration"] == hook)
    assert "severed rat tail" in ceiling, "the event is still the backbone of the ceiling"
    assert "bounty on every dead rat" in ceiling, "and the claim behind it is available too"


def test_the_engine_reaches_the_post_script_validation_too():
    """The spine gate knew the engine and this path did not, so it fell back to a contract written
    for another engine: CLAIM_KIND_MISMATCH on a removed_keystone mechanism citing a context claim,
    which is what that engine's mechanism IS. And because that code is not repairable, the whole
    claim repair bailed and seven ordinary narration overshoots went unrepaired behind it."""
    import longform_research as lr

    script = {"_story_engine": "removed_keystone", "hook": "", "scenes": [
        {"scene_id": "event_04", "causal_role": "mechanism",
         "narration": "The cats had also been eating the rabbits.",
         "event": {"text": "Cats preyed on the island's rabbits as well as its seabirds.",
                   "claim_refs": ["c01"]}}]}
    dossier = {"claims": [{"claim_id": "c01", "verified": True, "claim_kind": "context",
                           "claim_kind_confidence": 0.95,
                           "claim": "Cats on the island preyed on rabbits and seabirds."}]}

    def judge(payload, **kwargs):
        return {"verdict": "entailed", "supported_core": "", "unsupported_details": []}

    report = lr.validate_story_fact_model(script, dossier, judge=judge, cache={}, cost_sink=[])
    assert "CLAIM_KIND_MISMATCH" not in [e["code"] for e in report["errors"]]
