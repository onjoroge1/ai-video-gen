"""The turn by 45 seconds, ENFORCED: the read's turn quote, the single revision at score 88 when
LATE_TURN, its guards and fallback, and the storyboard repair that may not undo it. The read and the
revision run against a scripted fake client; nothing reaches a provider."""
import json

import pytest

import explainer_pipeline as ep
import opening_turn as ot
import storyboard_repair as repair
from turn_fixture import (ESCAPE, SAVED,
                          dossier_for as _dossier,
                          script_for as _script,
                          trimmed_rows as _trimmed_rows)



# ── 3. the read, the single revision and its guards ─────────────────────────────────────────

class _Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                text = outer.replies.pop(0)
                return type("R", (), {"content": [type("C", (), {"text": text})()],
                                      "usage": type("U", (), {"input_tokens": 500, "output_tokens": 100})()})()
        self.messages = _M()



def _read(score_each, turn, fix="Trim the apiary headcount so the escape lands faster."):
    return json.dumps({"clarity": score_each, "rationale": score_each, "movement": score_each,
                       "efficiency": score_each - 1, "tangibility": score_each,
                       "body_restates_opening": False, "evidence": {}, "fix": fix, "turn": turn})



NAMES = "Warwick Kerr imported queens to Brazil; Rio Claro apiary; European honey bees."


def _patch(monkeypatch, fake, ledger=(True, [])):
    monkeypatch.setattr(ep, "_claude", lambda: fake)
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)
    monkeypatch.setattr(ep, "expansion_survives_the_ledger", lambda new, ceiling, **kw: ledger)


def _revision(rows):
    return json.dumps({"scenes": [{"id": i + 1, "narration": text}
                                  for i, text in enumerate(rows.values())]})


def test_the_read_asks_for_the_turn_and_counts_to_it(monkeypatch):
    fake = _Fake([_read(9, ESCAPE)])
    _patch(monkeypatch, fake)
    lines = []
    review = ep._evaluate_opening(_script("bees_v16"), [], lines.append)
    assert review["score"] == 88 and review["words_to_first_escalation"] == 273
    assert "words_to_consequence" not in review
    # Enforced by the structural fallback (check (a)); the read's quote is reported beside it.
    assert review["turn"]["turn_words"] == 163 and review["turn"]["late"] and review["turn"]["source"] == "fallback"
    assert review["turn"]["quote_turn_words"] == 163 and review["turn"]["consequence_spoken"] is True
    assert '"turn"' in fake.calls[0]["system"] and "Turn: copy, word for word" in fake.calls[0]["messages"][0]["content"]
    assert any("273 words to first escalation" in line for line in lines)
    assert any("LATE_TURN" in line and "(report only)" in line for line in lines)


def test_an_off_scope_read_is_the_read_it_was(monkeypatch):
    fake = _Fake([_read(9, "x")])
    _patch(monkeypatch, fake)
    script = _script("bees_v16")
    script["_turn_rule"] = {"applies": False}
    review = ep._evaluate_opening(script, [], lambda m: None)
    assert "turn" not in review and fake.calls[0]["system"] == ep._OPENING_REVIEW_SYSTEM
    assert "Turn:" not in fake.calls[0]["messages"][0]["content"]


def _late_review(monkeypatch):
    fake = _Fake([_read(9, ESCAPE)])
    _patch(monkeypatch, fake)
    return ep._evaluate_opening(_script("bees_v16"), [], lambda m: None)


def test_a_late_turn_is_revised_at_score_88_and_the_trim_is_adopted(monkeypatch):
    review = _late_review(monkeypatch)
    assert review["score"] == 88
    rows = _trimmed_rows()
    fake = _Fake([_revision(rows), _read(9, ESCAPE)])
    _patch(monkeypatch, fake)
    lines = []
    script = _script("bees_v16")
    revised, _cost = ep._revise_opening_once(script, review, _dossier("bees_v16", NAMES), [], {},
                                             lines.append)
    assert revised is not script, lines
    assert revised["_opening_review"]["turn"]["turn_words"] == 104
    assert revised["_opening_review"]["revised_from"]["turn"]["turn_words"] == 163
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "THE TURN IS LATE" in prompt and "by word 103" in prompt
    sent = prompt.split("\n\nReturn ONLY JSON")[0]
    caps = [row["cap"] for row in json.loads(sent[sent.index("[{"):])]
    assert len(caps) == 4 and sum(caps) <= ot.TURN_TARGET_WORDS, "rows: frame through the turn row"
    assert len(fake.calls) == 2 and script.get("_opening_revision_attempted")
    # ONE per film: a resumed run that reads the same opening again does not buy another.
    again, cost = ep._revise_opening_once(script, review, _dossier("bees_v16", NAMES), [], {}, lines.append)
    assert again is script and cost == 0.0


def test_lates_are_not_revised_once_media_is_bought(monkeypatch):
    review = _late_review(monkeypatch)
    out, cost = ep._revise_opening_once(_script("bees_v16"), review, _dossier("bees_v16", NAMES), [],
                                        {}, lambda m: None, turn_revision=False)
    assert cost == 0.0 and out["scenes"][0]["narration"] == SAVED["bees_v16"]["scenes"][0]["narration"]


def _held(monkeypatch, rows, reread=None, ledger=(True, []), names=NAMES):
    review = _late_review(monkeypatch)
    replies = [_revision(rows)] + ([reread] if reread else [])
    fake = _Fake(replies)
    _patch(monkeypatch, fake, ledger)
    lines = []
    script = _script("bees_v16")
    out, _ = ep._revise_opening_once(script, review, _dossier("bees_v16", names), [], {}, lines.append)
    return out is script, lines, fake


def test_only_the_row_receiving_the_consequence_may_grow(monkeypatch):
    original = {s["scene_id"]: s["narration"] for s in SAVED["bees_v16"]["scenes"][:4]}
    rows = _trimmed_rows()
    rows["scene_001"] = original["scene_001"] + " The jars stay empty."
    held, lines, _ = _held(monkeypatch, rows)
    assert held and "scene 1 grew by 4 words (only the row receiving" in lines[-1]
    rows = _trimmed_rows()
    rows["scene_003"] = original["scene_003"] + " " + " ".join(["more"] * 21)
    held, lines, _ = _held(monkeypatch, rows)
    assert held and "scene 3 grew by 21 words" in lines[-1]
    # The receiving row (the false_resolution before the hinge) may grow by up to twenty words
    # to carry the consequence, as long as the turn still lands inside the limit.
    rows = _trimmed_rows()
    rows["scene_001"] = ("Imagine you're a beekeeper in Brazil, trying to fill jars from bees that "
                         "struggle in the heat. Your bees are European honey bees, built for a "
                         "temperate climate.")
    rows["scene_003"] = original["scene_003"] + " The grids came off and the queens left."
    held, lines, _ = _held(monkeypatch, rows, reread=_read(9, ESCAPE))
    assert not held, lines


def test_a_locked_phrase_may_go_only_when_it_carries_neither_solution_nor_consequence(monkeypatch):
    rows = _trimmed_rows()
    rows["scene_002"] = "In 1956 a geneticist brought African queens to Brazil."      # c01/c02: solution
    held, lines, _ = _held(monkeypatch, rows)
    assert held and "carries the solution or the consequence" in lines[-1]
    rows = _trimmed_rows()
    rows["scene_003"] = "The surviving queens went to a research apiary near Rio Claro."  # c04/c05 cut
    held, lines, _ = _held(monkeypatch, rows, reread=_read(9, ESCAPE))
    assert not held, lines


def test_the_previous_opening_stands_when_any_adoption_check_fails(monkeypatch):
    # the ledger refuses a changed scene
    held, lines, fake = _held(monkeypatch, _trimmed_rows(), ledger=(False, ["new detail"]))
    assert held and "asserts more than its ceiling" in lines[-1] and len(fake.calls) == 1
    # the identity check finds an unsourced name
    rows = _trimmed_rows()
    rows["scene_001"] = rows["scene_001"].replace("Your bees", "Maria Silva says your bees")
    rows["scene_001"] = " ".join(rows["scene_001"].split()[:39])
    held, lines, _ = _held(monkeypatch, rows)
    assert held and "Maria Silva" in lines[-1]
    # the re-measured turn is still late: only the frame's restatement was cut
    rows = {s["scene_id"]: s["narration"] for s in SAVED["bees_v16"]["scenes"][:4]}
    rows["scene_001"] = rows["scene_001"].replace(" Thinner than it should be.", "")
    held, lines, _ = _held(monkeypatch, rows, reread=_read(9, ESCAPE))
    assert held and "still ends at word 158" in lines[-1]
    # the re-read says no sentence states the consequence
    held, lines, _ = _held(monkeypatch, _trimmed_rows(), reread=_read(9, "NONE"))
    assert held and "says no sentence states the consequence" in lines[-1]
    # a re-read quoting some other sentence is a report: the fallback decides, and 104 fits
    held, lines, _ = _held(monkeypatch, _trimmed_rows(),
                           reread=_read(9, "But a new bee in the forest was only the start."))
    assert not held, lines
    # the re-read scores lower
    held, lines, _ = _held(monkeypatch, _trimmed_rows(), reread=_read(8, ESCAPE))
    assert held and "re-read scored" in lines[-1]


# ── 4. the storyboard repair cannot undo it ─────────────────────────────────────────────────

def _repair_script(hinge=""):
    script = _script("bees_v16", _story_contract={"opening_object": "the honey jars"})
    rows = _trimmed_rows()
    for scene in script["scenes"]:
        if scene["scene_id"] in rows:
            scene["narration"] = rows[scene["scene_id"]]
    if hinge:
        script["scenes"][3]["narration"] = hinge
    script["scenes"].append({"scene_id": "scene_020", "beat_id": "close", "causal_role": "tool",
                             "narration": "Look again at the honey jars."})
    return script


def _counts(script):
    return [len(s["narration"].split()) for s in script["scenes"]]


def test_a_consequence_repair_that_pushes_the_turn_past_116_is_refused():
    script = _repair_script(hinge="But the forest does not read the plan.")
    edit = repair.plan(script, {"validation": {"errors": [
        "OPENING_CONSEQUENCE_UNSPOKEN: no scene before the mechanism binds it"]}})
    turn = edit["turn"]
    # Counted to the hinge (the enforcing fallback, shape A), not to the row the repair writes.
    assert sum(_counts(script)[:3]) == 94 and _counts(script)[3] == 8
    assert turn["mode"] == "row" and turn["before_words"] == 94 + 8
    assert turn["consequence_row_cap"] == 116 - sum(_counts(script)[:2]) - 8
    assert "THE TURN DEADLINE" in repair.prompt(script, edit)
    base = script["scenes"][2]["narration"]
    too_long = base + " " + " ".join(["then"] * 15)
    with pytest.raises(ValueError, match="pushes the opening's turn past 116"):
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": too_long}]})
    fits = base + " In October 1957 the grids came off and twenty-six queens left for the forest."
    candidate = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": fits}]})
    stamped = candidate["_opening_turn"]
    assert stamped["source"] == "fallback" and stamped["turn_words"] == 94 + 14 + 8 and not stamped["late"]
    assert stamped["hint_scene_id"] == "scene_003" and stamped["hint_turn_words"] == 108
    # and it is what the pipeline re-measures after the repair
    assert ot.remeasure(candidate)["turn_words"] == 116 and ot.remeasure(candidate)["hint_turn_words"] == 108


def test_a_soft_hinge_repair_that_pushes_the_turn_past_116_is_refused():
    long_hinge = "But one October day in 1957 the grids came off, and the queens left."
    script = _repair_script(hinge=long_hinge)
    edit = repair.plan(script, {"validation": {"errors": ["SOFT_HINGE: the hinge runs 14 words"]}})
    assert edit["turn"]["before_words"] == 94 + 14
    moved = (script["scenes"][2]["narration"] + " In October 1957 a local beekeeper removed the "
             "grids, and twenty-six African queens left for the nearby forest.")
    with pytest.raises(ValueError, match="pushes the opening's turn"):
        repair.apply_response(script, edit, {"scenes": [
            {"scene_id": "scene_003", "narration": moved}, {"scene_id": "scene_004", "narration": "Except the grids came off."}]})
    shorter = script["scenes"][2]["narration"] + " In October 1957 twenty-six queens left."
    out = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_003", "narration": shorter}, {"scene_id": "scene_004", "narration": "Except the grids came off."}]})
    assert out["_opening_turn"]["turn_words"] <= 116


def test_an_opening_already_past_the_limit_stays_repairable():
    script = _script("bees_v14", _story_contract={"opening_object": "the honey jars"})
    script["scenes"].append({"scene_id": "scene_020", "beat_id": "close", "causal_role": "tool",
                             "narration": "Look again at the honey jars."})
    edit = repair.plan(script, {"validation": {"errors": ["OPENING_CONSEQUENCE_UNSPOKEN: x"]}})
    assert edit["turn"]["before_words"] > 116 and "consequence_row_cap" not in edit["turn"]
    grown = script["scenes"][2]["narration"] + " In October 1957 the grids came off and twenty-six queens left."
    out = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": grown}]})
    assert out["_opening_turn"]["late"], "recorded as late, not made unrepairable"


def test_off_scope_repairs_carry_no_turn():
    script = _repair_script(hinge="But the forest does not read the plan.")
    script["_turn_rule"] = {"applies": False}
    edit = repair.plan(script, {"validation": {"errors": ["OPENING_CONSEQUENCE_UNSPOKEN: x"]}})
    assert "turn" not in edit




# ── shape B under the enforcing fallback ────────────────────────────────────────────────────

CARP_FIX = "Cut the second telling of the need."
CARP_NAMES = "The carp reached the Ohio and Cumberland Rivers."


def _carp_review(monkeypatch, score_each, fix=CARP_FIX):
    fake = _Fake([_read(score_each, "Flood waters rose over the pond banks and poured through "
                                    "the spillways, and the carp went with them.", fix=fix)])
    _patch(monkeypatch, fake)
    return ep._evaluate_opening(_script("asian-carp"), [], lambda m: None)


def test_a_shape_b_turn_at_the_mechanism_end_buys_no_turn_revision(monkeypatch):
    review = _carp_review(monkeypatch, 9)
    turn = review["turn"]
    assert turn["shape"] == "B" and turn["late"] and turn["turn_words"] == 219
    assert ot.turn_row_is_mechanism(SAVED["asian-carp"]["scenes"], turn)
    fake = _Fake([])
    _patch(monkeypatch, fake)
    lines = []
    script = _script("asian-carp")
    out, cost = ep._revise_opening_once(script, review, _dossier("asian-carp"), [], {}, lines.append)
    assert out is script and cost == 0.0 and not fake.calls
    assert "cannot reach it without cutting the mechanism" in lines[0]
    assert not script.get("_opening_revision_attempted")


def test_a_score_revision_on_a_shape_b_film_is_held_only_if_the_turn_moves_later(monkeypatch):
    review = _carp_review(monkeypatch, 7)          # 68: the read's own score asks for a revision
    assert review["score"] < 80 and review["turn"]["late"]
    scenes = SAVED["asian-carp"]["scenes"]
    first = scenes[0]["narration"]
    shorter = first.replace(" That is the quiet promise.", "") if "That is the quiet promise." in first \
        else " ".join(first.split()[:-3])
    assert shorter != first
    reply = json.dumps({"scenes": [{"id": 1, "narration": shorter}]})
    fake = _Fake([reply, _read(7, "NONE", fix="")])
    _patch(monkeypatch, fake)
    lines = []
    out, _ = ep._revise_opening_once(_script("asian-carp"), review, _dossier("asian-carp", CARP_NAMES),
                                     [], {}, lines.append)
    assert out is not None and "THE TURN IS LATE" not in fake.calls[0]["messages"][0]["content"]
    # the re-read heard no consequence where the first read did: held
    assert "says no sentence states the consequence" in lines[-1]
    fake = _Fake([reply, _read(7, "x", fix="")])
    _patch(monkeypatch, fake)
    lines = []
    out, _ = ep._revise_opening_once(_script("asian-carp"), review, _dossier("asian-carp", CARP_NAMES),
                                     [], {}, lines.append)
    assert out["_opening_review"]["turn"]["turn_words"] < review["turn"]["turn_words"], lines
    assert out["_opening_review"]["turn"]["late"], "still late by the fallback, and adopted: it moved earlier"
