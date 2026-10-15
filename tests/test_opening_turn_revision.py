"""The turn by 45 seconds, ENFORCED: the read's turn quote, the single revision at score 88 when
LATE_TURN, its guards and fallback, the storyboard repair that records (never refuses) a turn it
pushes late, and the read decided once before media. The read and the revision run against a
scripted fake client that fails the test on any call it was not given a reply for; nothing reaches
a provider."""
import copy
import json
import os

import pytest

import explainer_pipeline as ep
import opening_turn as ot
import storyboard_repair as repair
from turn_fixture import (ESCAPE, ROOT, SAVED,
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
                # Strict: an exhausted fake raising IndexError was swallowed as "unavailable" and
                # looked exactly like an attempt that never called (2026-10-15). pytest.fail is a
                # BaseException, so the pipeline's `except Exception` cannot hide it.
                if not outer.replies:
                    pytest.fail("unexpected provider call: the fake has no reply left")
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
    assert len(fake.calls) == 2 and "already attempted once" in lines[-1]


def test_lates_are_not_revised_once_media_is_bought(monkeypatch):
    review = _late_review(monkeypatch)
    fake = _Fake([])
    _patch(monkeypatch, fake)
    script = _script("bees_v16")
    out, cost = ep._revise_opening_once(script, review, _dossier("bees_v16", NAMES), [],
                                        {}, lambda m: None, turn_revision=False)
    assert cost == 0.0 and out["scenes"][0]["narration"] == SAVED["bees_v16"]["scenes"][0]["narration"]
    assert not fake.calls and not script.get("_opening_revision_attempted")


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
    # the re-measured turn is still late: only the frame's restatement was cut. The structural
    # fallback knows that from the narration alone, so neither the re-read nor the ledger is bought.
    rows = {s["scene_id"]: s["narration"] for s in SAVED["bees_v16"]["scenes"][:4]}
    rows["scene_001"] = rows["scene_001"].replace(" Thinner than it should be.", "")
    held, lines, fake = _held(monkeypatch, rows, reread=_read(9, ESCAPE))
    assert held and "still ends at word 158" in lines[-1]
    assert len(fake.calls) == 1, "the revision only: no re-read for a candidate that cannot land"
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


@pytest.mark.parametrize("hinge", [
    "Except in October 1957 a local beekeeper pulled the grids, and twenty-six queens flew free.",
    "Except in October 1957 a local beekeeper removed the grids, and twenty-six African queens flew free."])
def test_the_revision_may_not_grow_the_hinge_past_its_ten_words(monkeypatch, hinge):
    # _ensure_hinge_fits_budget has already run: a hinge grown here reaches the storyboard as a
    # blocking SOFT_HINGE and spends the job's one storyboard repair. Held for free, before the
    # re-read (the fake has no reply for one).
    rows = _trimmed_rows()
    rows["scene_004"] = hinge
    assert len(hinge.split()) > 10 and len(hinge.split()) - 10 <= ot.CONSEQUENCE_ROW_GROWTH_WORDS
    held, lines, fake = _held(monkeypatch, rows)
    assert held and f"the hinge (scene 4) runs {len(hinge.split())} words, past its 10-word cap" in lines[-1]
    assert len(fake.calls) == 1


def test_the_hinge_may_still_carry_the_consequence_in_ten_words(monkeypatch):
    rows = _trimmed_rows()
    rows["scene_004"] = "Except in 1957 the grids came off; twenty-six queens flew."
    assert len(rows["scene_004"].split()) == 10
    held, lines, _ = _held(monkeypatch, rows, reread=_read(9, rows["scene_004"]))
    assert not held and "turn 163 -> 104 words" in lines[-1], lines


def test_a_revision_that_cannot_land_the_turn_buys_no_ledger_check_or_re_read(monkeypatch):
    review = _late_review(monkeypatch)
    rows = {s["scene_id"]: s["narration"] for s in SAVED["bees_v16"]["scenes"][:4]}
    rows["scene_001"] = rows["scene_001"].replace(" Thinner than it should be.", "")
    fake = _Fake([_revision(rows)])
    _patch(monkeypatch, fake)
    checked = []
    monkeypatch.setattr(ep, "expansion_survives_the_ledger",
                        lambda new, ceiling, **kw: checked.append(new) or (True, []))
    lines = []
    script = _script("bees_v16")
    out, cost = ep._revise_opening_once(script, review, _dossier("bees_v16", NAMES), [], {}, lines.append)
    assert out is script and "still ends at word 158 (limit 116)" in lines[-1]
    assert len(fake.calls) == 1 and not checked and cost == 0.01


def test_the_read_and_the_revision_reach_the_cost_list(monkeypatch):
    # aux_costs is a plain list, and _charge records only to a CostLedger: the read, the revision
    # and its re-read were missing from run_result's actual_cost.
    fake = _Fake([_read(9, ESCAPE)])
    _patch(monkeypatch, fake)
    sink = []
    review = ep._evaluate_opening(_script("bees_v16"), sink, lambda m: None)
    assert sink == [0.01]
    fake = _Fake([_revision(_trimmed_rows()), _read(9, ESCAPE)])
    _patch(monkeypatch, fake)
    sink = []
    revised, cost = ep._revise_opening_once(_script("bees_v16"), review, _dossier("bees_v16", NAMES),
                                            sink, {}, lambda m: None)
    assert revised["_opening_review"].get("revised_from")
    assert sink == [0.01] and cost == 0.01, "the re-read through the sink, the revision returned"


# ── 4. the storyboard repair records the turn it moves, and never refuses for it ────────────

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


def test_a_consequence_repair_that_pushes_the_turn_past_116_is_accepted_and_recorded_late():
    script = _repair_script(hinge="But the forest does not read the plan.")
    edit = repair.plan(script, {"validation": {"errors": [
        "OPENING_CONSEQUENCE_UNSPOKEN: no scene before the mechanism binds it"]}})
    turn = edit["turn"]
    # Counted to the hinge (the enforcing fallback, shape A), not to the row the repair writes.
    assert sum(_counts(script)[:3]) == 94 and _counts(script)[3] == 8
    assert turn["mode"] == "row" and turn["before_words"] == 94 + 8
    assert turn["consequence_row_cap"] == 116 - sum(_counts(script)[:2]) - 8
    text = repair.prompt(script, edit)
    # The cap is stated, and nothing beside it tells the model to keep every word and grow.
    assert "THE TURN DEADLINE" in text and "Keep every sourced fact the scene already says." in text
    assert "Keep everything the scene already says" not in text
    # The whole instruction reaches a consequence-only repair (it stopped at "in one to three ").
    assert ("Add to the END of that scene, in one to three sentences, the ordinary act" in text
            and "Do not touch the hinge; the body never tells this again." in text)
    base = script["scenes"][2]["narration"]
    # The repair keeps the row, as the bees writer did, and adds the plan's consequence whole:
    # the turn lands past 116. Refusing it would stop the film at the hard storyboard gate, and a
    # late turn is recorded, never a block (operator decision 3).
    late = (base + " In October 1957 a local beekeeper noticed the excluders and removed them, and "
            "twenty-six African queens left with small swarms into the nearby forest.")
    candidate = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": late}]})
    stamped = candidate["_opening_turn"]
    assert stamped["late"] and stamped["turn_words"] == 94 + 24 + 8
    assert stamped["pushed_late_by_repair"] == {"before_words": 102, "after_words": 126}
    assert ot.late_turn_record(stamped)["words"] == 126
    # and the pipeline's re-measure after the repair keeps the record
    again = ot.remeasure(candidate)
    assert again["late"] and again["pushed_late_by_repair"]["after_words"] == 126
    assert ot.run_result_fields(dict(candidate, _opening_turn=again))["opening_turn"]["pushed_late_by_repair"]
    fits = base + " In October 1957 the grids came off and twenty-six queens left for the forest."
    candidate = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": fits}]})
    stamped = candidate["_opening_turn"]
    assert stamped["source"] == "fallback" and stamped["turn_words"] == 94 + 14 + 8 and not stamped["late"]
    assert "pushed_late_by_repair" not in stamped
    assert stamped["hint_scene_id"] == "scene_003" and stamped["hint_turn_words"] == 108
    # and it is what the pipeline re-measures after the repair
    assert ot.remeasure(candidate)["turn_words"] == 116 and ot.remeasure(candidate)["hint_turn_words"] == 108


def test_a_soft_hinge_repair_that_pushes_the_turn_past_116_is_accepted_and_recorded_late():
    long_hinge = "But one October day in 1957 the grids came off, and the queens left."
    script = _repair_script(hinge=long_hinge)
    edit = repair.plan(script, {"validation": {"errors": ["SOFT_HINGE: the hinge runs 14 words"]}})
    assert edit["turn"]["before_words"] == 94 + 14
    text = repair.prompt(script, edit)
    assert "MOVES to the END" in text and "Do not touch the hinge" not in text, \
        "the hinge is the scene this repair shortens"
    moved = (script["scenes"][2]["narration"] + " In October 1957 a local beekeeper removed the "
             "grids, and twenty-six African queens left for the nearby forest.")
    out = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_003", "narration": moved}, {"scene_id": "scene_004", "narration": "Except the grids came off."}]})
    assert out["_opening_turn"]["late"] and out["_opening_turn"]["pushed_late_by_repair"]["before_words"] == 108
    shorter = script["scenes"][2]["narration"] + " In October 1957 twenty-six queens left."
    out = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_003", "narration": shorter}, {"scene_id": "scene_004", "narration": "Except the grids came off."}]})
    assert out["_opening_turn"]["turn_words"] <= 116 and "pushed_late_by_repair" not in out["_opening_turn"]


def _check_b_script():
    """Writer check (b)'s bees_v16 opening, stamped with the read's NONE on it (2026-10-15)."""
    with open(os.path.join(ROOT, "fixtures", "opening_turn", "writer_check_2026-10-15_bees_v16.json"),
              encoding="utf-8") as handle:
        check_b = json.load(handle)
    script = _script("bees_v16", _story_contract={"opening_object": "the honey jars"})
    for scene, text in zip(script["scenes"], check_b["narration"]):
        scene["narration"] = text
    script["scenes"].append({"scene_id": "scene_020", "beat_id": "close", "causal_role": "tool",
                             "narration": "Look again at the honey jars."})
    script["_opening_turn"] = ot.measure_script(script, quote="NONE")
    assert ot.read_says_unspoken(script)
    return script


def test_a_consequence_repair_must_add_something_to_its_row():
    # The read's NONE expires with the narration it judged, and claim binding passes check (b)'s
    # rows, so a reply that returns the row unchanged or only trims it was accepted with the escape
    # still unsaid -- the bees_v14 failure UNSPOKEN_FROM_READ exists to block.
    script = _check_b_script()
    edit = repair.plan(script, {"validation": {"errors": [
        "OPENING_CONSEQUENCE_UNSPOKEN: the opening read finds no sentence that states it"]}})
    assert edit["consequence_scene_id"] == "scene_003" and edit["turn"]["consequence_row_cap"] == 36
    same = script["scenes"][2]["narration"]
    with pytest.raises(ValueError, match="added nothing to the consequence scene"):
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": same}]})
    trimmed = ("The surviving queens were held at a research apiary near Rio Claro, each sealed behind "
               "queen excluder grids that let workers pass but trapped the queens.")
    with pytest.raises(ValueError, match="added nothing to the consequence scene"):
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": trimmed}]})
    said = ("The surviving queens were held at a research apiary near Rio Claro behind queen excluder "
            "grids. In October 1957 the grids came off and twenty-six queens left.")
    out = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_003", "narration": said}]})
    assert not out["_opening_turn"]["late"] and out["_opening_turn"]["turn_words"] <= 116


def test_the_read_s_none_survives_a_repair_that_leaves_the_window_as_it_was():
    script = _check_b_script()
    edit = repair.plan(script, {"validation": {"errors": [
        "DANGLING_REFERENCE: scene_002 opens on 'So' and points at nothing"]}})
    assert edit["turn"]["mode"] == "quote"
    out = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_002", "narration": script["scenes"][1]["narration"]}]})
    assert out["_opening_turn"]["consequence_spoken"] is False and ot.read_says_unspoken(out)
    changed = repair.apply_response(script, edit, {"scenes": [
        {"scene_id": "scene_002", "narration": script["scenes"][1]["narration"].replace("So in", "In")}]})
    assert not ot.read_says_unspoken(changed), "new narration: the NONE judged other words"


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


# ── 5. the read, its NONE and the revision are decided once, before media ───────────────────

class _Unavailable:
    """A provider that fails every call, as a single 529 does under the durable client's
    max_retries=0: the read returns None and the turn is stamped by the fallback."""
    def __init__(self):
        self.calls = []
        outer = self

        class _M:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                raise RuntimeError("overloaded")
        self.messages = _M()


def _settle(monkeypatch, script, fake, tmp_path, resumed, media=False):
    _patch(monkeypatch, fake)
    if media:
        (tmp_path / "audio").mkdir(exist_ok=True)
        (tmp_path / "audio" / "scene_01.mp3").write_text("x")
    lines, aux = [], []
    out = ep._settle_opening_read(script, _dossier("bees_v16", NAMES), aux, str(tmp_path), resumed,
                                  lines.append)
    return out, lines, aux


def _first_pass(monkeypatch, tmp_path):
    fake = _Fake([_read(9, ESCAPE), _revision(_trimmed_rows()), _read(9, ESCAPE)])
    out, lines, aux = _settle(monkeypatch, _script("bees_v16"), fake, tmp_path, resumed=False)
    return out, fake, lines, aux


def test_a_first_pass_reads_revises_stamps_and_counts_its_spend(monkeypatch, tmp_path):
    out, fake, _lines, aux = _first_pass(monkeypatch, tmp_path)
    turn = out["_opening_turn"]
    assert len(fake.calls) == 3 and turn["revised"] and turn["turn_words"] == 104 and not turn["late"]
    assert turn["digest"] == ot.window_digest(out["scenes"])
    assert aux == [0.01, 0.01, 0.01], "the read, the re-read and the revision all reach actual_cost"


def test_a_resume_on_the_narration_it_stamped_reads_nothing_and_keeps_the_record(monkeypatch, tmp_path):
    out, _fake, _lines, _aux = _first_pass(monkeypatch, tmp_path)
    saved = copy.deepcopy(out)
    fake = _Fake([])                 # strict: any read or revision fails the test
    again, lines, aux = _settle(monkeypatch, copy.deepcopy(out), fake, tmp_path, resumed=True)
    assert not fake.calls and not aux and "checkpoint; not read again" in lines[-1]
    assert again["_opening_turn"] == saved["_opening_turn"] and again["_opening_turn"]["revised"]
    assert again["scenes"] == saved["scenes"]


def test_a_resumed_read_on_changed_narration_is_a_report_that_cannot_block_or_revise(monkeypatch, tmp_path):
    out, _fake, _lines, _aux = _first_pass(monkeypatch, tmp_path)
    resumed = copy.deepcopy(out)
    # narration changed after the stamp (no re-measure ran), and media restore into a fresh dir
    resumed["scenes"][1]["narration"] = resumed["scenes"][1]["narration"].replace("In 1956", "In 1956,")
    resumed.pop("_opening_revision_attempted")
    fake = _Fake([_read(7, "NONE")])  # scores under 80 and answers NONE; no reply for a revision
    again, lines, aux = _settle(monkeypatch, resumed, fake, tmp_path, resumed=True)
    turn = again["_opening_turn"]
    assert len(fake.calls) == 1 and aux == [0.01]
    assert any("buys no revision" in line for line in lines)
    assert turn["consequence_spoken"] is None and turn["resumed_read_none"] and turn["revised"]
    assert not ot.read_says_unspoken(again), "a NONE after media is a report, not a storyboard failure"


def test_a_continuation_after_an_unavailable_first_read_buys_no_late_revision(monkeypatch, tmp_path):
    # The first read failed, so no revision was attempted and no marker set; the fallback stamped
    # LATE. A continuation restores into a dir with no media, where has_media() is False.
    first, lines, _aux = _settle(monkeypatch, _script("bees_v16"), _Unavailable(), tmp_path, resumed=False)
    assert first["_opening_turn"]["late"] and not first.get("_opening_revision_attempted")
    fake = _Fake([])
    again, lines, aux = _settle(monkeypatch, copy.deepcopy(first), fake, tmp_path, resumed=True)
    assert not fake.calls and not aux
    assert again["scenes"] == first["scenes"] and again["_opening_turn"]["late"]


def test_a_first_pass_with_media_on_disk_buys_no_turn_revision(monkeypatch, tmp_path):
    fake = _Fake([_read(9, ESCAPE)])
    out, lines, aux = _settle(monkeypatch, _script("bees_v16"), fake, tmp_path, resumed=False, media=True)
    assert len(fake.calls) == 1 and aux == [0.01, 0.0]
    assert out["_opening_turn"]["late"] and not out["_opening_turn"]["revised"]
