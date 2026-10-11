"""The blind judge votes three times; the contract scores the majority, not one roll.

Asian carp (2026-10-11): the same story scored 82, 86, 82 as one boolean flipped in "Evidence
accumulation and causal storytelling" -- 4 points, enough to cross the 85 upload bar.
"""
import explainer_pipeline as ep
import longform_rendered_gate as gate


def _vote(**overrides):
    base = {field: True for field in gate.BLIND_BOOL_FIELDS}
    base.update(slideshow=False, bolt_useful=False, captions_obscure_evidence=False,
                observed_evidence_sequence=["a", "b"], reason_to_continue="why")
    base.update(overrides)
    return base


def test_majority_per_field_and_a_tie_is_false():
    merged = gate.merge_blind_votes([_vote(causal_story=False), _vote(), _vote()])
    assert merged["causal_story"] is True and merged["votes"] == 3
    assert merged["vote_split"]["causal_story"] == "2/3"
    tie = gate.merge_blind_votes([_vote(causal_story=False), _vote()])
    assert tie["causal_story"] is False


def test_invalid_votes_are_ignored_and_all_invalid_reports_the_error():
    merged = gate.merge_blind_votes([{"valid": False, "judge_error": "x"}, _vote(), _vote()])
    assert merged["votes"] == 2 and merged["causal_story"] is True
    failed = gate.merge_blind_votes([{"valid": False, "judge_error": "boom"}])
    assert failed["judge_error"] == "boom"


def test_text_fields_come_from_the_vote_that_agrees_with_the_majority():
    odd = _vote(causal_story=False, evidence_accumulates=False, reason_to_continue="odd")
    merged = gate.merge_blind_votes([odd, _vote(reason_to_continue="usual"), _vote()])
    assert merged["reason_to_continue"] in ("usual", "why")


def test_the_one_flip_that_moved_the_contract_no_longer_moves_it():
    """One dissenting vote on causal_story leaves the 20-point section at full marks."""
    deterministic = {"verified_information_ratio": 0.9}
    flipped = gate.merge_blind_votes([_vote(causal_story=False), _vote(), _vote()])
    section = gate._fraction_score(20, [
        flipped.get("evidence_accumulates"), flipped.get("causal_story"),
        deterministic["verified_information_ratio"] >= 0.70,
        flipped.get("forward_question_readable"),
        len(flipped.get("observed_evidence_sequence") or []) >= 2])
    assert section == 20


def test_the_pipeline_judge_runs_the_configured_number_of_votes(monkeypatch):
    calls = []
    monkeypatch.setenv("BLIND_JUDGE_VOTES", "3")
    monkeypatch.setattr(ep, "_blind_rendered_story_judge_once",
                        lambda *a, **k: calls.append(1) or _vote(causal_story=len(calls) != 2))
    merged = ep._blind_rendered_story_judge("sheet.jpg", [])
    assert len(calls) == 3 and merged["causal_story"] is True and merged["votes"] == 3


def test_a_place_is_not_an_actor_in_the_hook():
    """'the American South' scored the Asian carp hook 67: a place read as a named person."""
    import hook_patterns as hp
    for line in ("Imagine you run a catfish farm in the American South, and your ponds keep "
                 "turning thick and green.",
                 "Imagine you live in Mexico City and the air you breathe is grey.",
                 "Imagine you farm the Great Plains and the soil starts to move.",
                 "Imagine you fish Lake Victoria and the nets come up empty."):
        assert hp.score_hook(line, ladder=True)["patterns"]["no_institution"], line
    assert not hp.score_hook("Imagine Warwick Kerr in his lab with a jar of honey.",
                             ladder=True)["patterns"]["no_institution"]
