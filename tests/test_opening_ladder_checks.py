"""Phase 1, B: the body continues after the consequence, real people only, one semantic read with
a single fallback-protected revision, and a close that may return to the need."""
import json
import causal_story as cs
import explainer_pipeline as ep
import story_compiler as sc
import story_engines as se
from test_story_compiler import MACQUARIE


def _steps(body_restates=False):
    rows = [("setup", "European bees struggled in Brazil's heat and the harvest came thin."),
            ("intervention", "In 1956 Kerr imported African queens to breed a bee that made honey in the heat."),
            ("hinge", "Except a visitor did not know what the screens were for."),
            ("mechanism", "Queens escaped and hybridized with the local population."),
            ("escalation", "A visiting beekeeper lifted the screens and twenty-six colonies left."),
            ("escalation", "Kerr imported African queens to breed a honey bee for the heat, remember." if body_restates
             else "The hybrid colonies grew and swarmed more often."),
            ("escalation", "Africanized bees reached Arizona by 1993."),
            ("reversal", "Brazilian beekeeping shifted to Africanized bees."),
            ("tool", "Ask what else escaped the plan besides the bees.")]
    return [{"step_id": f"s{i}", "role": r, "situation": t, "chapter": 1 + i // 3,
             "caused_by": f"s{i - 1}" if i else "", "start_sec": i * 30.0}
            for i, (r, t) in enumerate(rows)]


def _codes(steps, stamped=True):
    payload = {"runtime_sec": 300.0, "steps": steps, "opening_object": "the honey jars",
               "start_state": "low honey", "hook": {"line": "Imagine you're a beekeeper in Brazil."}}
    if stamped:
        payload["opening_contract"] = cs.OPENING_CONTRACT
    return {i["code"] for i in cs.validate_causal_story(payload, se.get("removed_keystone"))["errors"]}


def test_a_body_beat_that_retells_the_intervention_blocks_under_the_ladder():
    assert "OPENING_RESTATED" in _codes(_steps(body_restates=True))
    assert "OPENING_RESTATED" not in _codes(_steps())
    assert "OPENING_RESTATED" not in _codes(_steps(body_restates=True), stamped=False), "hook-contract films are judged as before"


def test_the_opening_span_and_the_identity_check():
    scenes = [{"causal_role": r, "narration": t} for r, t in (
        ("setup", "Imagine you're a beekeeper in Brazil. Your harvest is thin."),
        ("intervention", "In 1956 a Brazilian geneticist, Warwick Kerr, has an answer."),
        ("hinge", "Except a visitor doesn't know what the screens are for."),
        ("escalation", "Maria Silva lifts the screens and the queens leave."),
        ("escalation", "The colonies spread north."))]
    assert ep._opening_scene_span(scenes) == [0, 1, 2, 3]
    dossier = {"claims": [{"claim_id": "c01", "claim": "Brazilian geneticist Warwick Kerr imported African bees in 1956."}]}
    findings = ep._opening_identity_findings({"scenes": scenes}, dossier)
    assert [f["scene"] for f in findings] == [4] and "Maria Silva" in findings[0]["message"]
    assert ep._opening_identity_findings({"scenes": scenes}, {"claims": []}) == []


class _Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.calls.append(kwargs["messages"][0]["content"][:60])
                text = outer.replies.pop(0)
                return type("R", (), {"content": [type("C", (), {"text": text})()],
                                      "usage": type("U", (), {"input_tokens": 500, "output_tokens": 100})()})()
        self.messages = _M()


def _review(score_each, fix="Make the harvest tangible in the first sentence.", restates=False):
    return json.dumps({"clarity": score_each, "rationale": score_each, "movement": score_each,
                       "efficiency": score_each, "tangibility": score_each,
                       "body_restates_opening": restates, "evidence": {}, "fix": fix})


def _script():
    return {"hook": "Imagine you're a beekeeper in Brazil.", "_opening_contract": cs.OPENING_CONTRACT,
            "scenes": [
                {"beat_id": "e1", "causal_role": "setup", "narration": "Imagine you're a beekeeper in Brazil. Honey production is very low.",
                 "event": {"text": "Brazilian honey production was very low.", "claim_refs": ["c39"]},
                 "claim_refs": [{"claim_id": "c39", "narration_phrase": "Honey production is very low"}]},
                {"beat_id": "e2", "causal_role": "intervention", "narration": "Kerr brings African queens to Rio Claro.",
                 "event": {"text": "Kerr brought African queens to Rio Claro.", "claim_refs": ["c01"]}, "claim_refs": []},
                {"beat_id": "e3", "causal_role": "escalation", "narration": "A visitor lifts the screens and the queens leave.",
                 "event": {"text": "A visiting beekeeper removed the excluders and 26 colonies left.", "claim_refs": ["cX5"]}, "claim_refs": []},
                {"beat_id": "e4", "causal_role": "escalation", "narration": "The colonies spread north.",
                 "event": {"text": "The colonies spread north.", "claim_refs": []}, "claim_refs": []}]}


DOSSIER = {"claims": [{"claim_id": "c39", "claim": "Brazilian honey production was very low."},
                      {"claim_id": "c01", "claim": "Kerr brought African queens to Rio Claro."},
                      {"claim_id": "cX5", "claim": "A visiting beekeeper removed the excluders and 26 colonies left."}]}


def test_the_read_is_reported_and_a_good_revision_is_adopted(monkeypatch):
    fake = _Fake([_review(6), json.dumps({"scenes": [
        {"id": 1, "narration": "Imagine you're a beekeeper in Brazil; your jars stay empty. Honey production is very low."},
        {"id": 2, "narration": "Kerr brings African queens to Rio Claro."},
        {"id": 3, "narration": "A visitor lifts the screens and the queens leave."}]}), _review(8)])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    monkeypatch.setattr(ep, "expansion_survives_the_ledger", lambda new, ceiling, **kw: (True, []))
    script = _script()
    lines = []
    review = ep._evaluate_opening(script, [], lines.append)
    assert review["score"] == 60 and review["opening_scenes"] == [1, 2, 3] and "fix:" in lines[-1]
    revised, cost = ep._revise_opening_once(script, review, DOSSIER, [], {}, lines.append)
    assert revised is not script and "your jars stay empty" in revised["scenes"][0]["narration"]
    assert revised["_opening_review"]["score"] == 80 and revised["_opening_review"]["revised_from"]["score"] == 60
    assert len(fake.calls) == 3, "read, revision, re-read -- and nothing more"


def test_a_revision_that_scores_lower_or_drops_a_phrase_falls_back(monkeypatch):
    # lower re-read -> fallback
    fake = _Fake([json.dumps({"scenes": [{"id": 1, "narration": "Imagine you're a beekeeper. Honey production is very low. The sun is hot."}]}), _review(5)])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    monkeypatch.setattr(ep, "expansion_survives_the_ledger", lambda new, ceiling, **kw: (True, []))
    script = _script(); review = {"score": 60, "fix": "x"}
    out, _ = ep._revise_opening_once(script, review, DOSSIER, [], {}, lambda m: None)
    assert out is script
    # dropped sourced phrase -> fallback before any re-read
    fake = _Fake([json.dumps({"scenes": [{"id": 1, "narration": "Imagine you're a beekeeper in Brazil with thin jars."}]})])
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    out, _ = ep._revise_opening_once(_script(), {"score": 60, "fix": "x"}, DOSSIER, [], {}, lambda m: None)
    assert out["scenes"][0]["narration"].endswith("Honey production is very low.") and len(fake.calls) == 1
    # a good opening is not revised at all
    assert ep._revise_opening_once(_script(), {"score": 84, "fix": "x"}, DOSSIER, [], {}, lambda m: None)[1] == 0.0


def test_a_close_that_returns_to_the_need_has_the_setup_in_its_ceiling():
    out = sc.compile_roles(MACQUARIE, "removed_keystone")
    beats = sc.splice_derived(out["beats"], out)
    by_need = sc.presentation_beats(beats, "removed_keystone", duration_sec=300, callback_kind="need")
    by_object = sc.presentation_beats(beats, "removed_keystone", duration_sec=300, callback_kind="object")
    setup = next(b["beat_id"] for b in by_need if b["role"] == "setup")
    close_need = next(b for b in by_need if b["role"] == "tool")
    close_object = next(b for b in by_object if b["role"] == "tool")
    assert setup in close_need["context_refs"] and setup not in close_object["context_refs"]


def test_a_frame_must_name_a_role_and_not_narrate_an_event():
    import hook_patterns as hp
    good = hp.score_hook("Imagine you're a beekeeper in Brazil.", ladder=True)
    assert good["score"] == 100 and good["patterns"]["frame_role"]
    flash = hp.score_hook("Imagine you backing away from twenty-six escaping queens; that is not even the strangest part.", ladder=True)
    assert flash["score"] <= 50 and not flash["patterns"]["frame_role"]
    assert any("no role" in n for n in flash["notes"])
    assert hp.frame_names_role("You are a farmer in Queensland with a cane field.")
    assert not hp.frame_names_role("You're a beekeeper whose queens escaped in 1957.")


def test_the_body_may_not_respeak_the_openings_markers_even_in_fresh_words():
    steps = _steps()
    steps[6]["situation"] = "By then Kerr's 1956 import had become a quiet landmark for Brazil's apiaries."
    assert "OPENING_RESTATED" in _codes(steps)


def test_the_repair_tolerates_an_echoed_but_unchanged_scene():
    import storyboard_repair as repair
    script = {"hook": "h", "scenes": [{"scene_id": "s1", "narration": "one"}, {"scene_id": "s2", "narration": "two"}]}
    edit = {"errors": ["SYNTHESIS_TOO_LONG: x"], "scene_ids": ["s2"], "mechanism_index": 0, "close_index": 1,
            "opening_object": "", "original_counts": [1, 1], "opening_word_limit": 99}
    out = repair.apply_response(script, edit, {"scenes": [{"scene_id": "s1", "narration": "one"},
                                                          {"scene_id": "s2", "narration": "two, shorter"}]})
    assert out["scenes"][1]["narration"] == "two, shorter" and out["scenes"][0]["narration"] == "one"
    try:
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "s1", "narration": "ONE CHANGED"},
                                                        {"scene_id": "s2", "narration": "two, shorter"}]})
    except ValueError as exc:
        assert "permitted scene set" in str(exc)
    else:
        raise AssertionError("a changed scene outside the permitted set was accepted")
