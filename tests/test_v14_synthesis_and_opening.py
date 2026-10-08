"""V14 prep (2026-10-08): the synthesis is paid per beat it re-walks and handed a checklist; the
second picture of an opening scene is a new picture."""
import explainer_pipeline as ep
import longform_evidence as le
from test_longform_evidence_phase3 import _script, _beat


def _beats(n_escalations: int):
    beats = [{"n": 1, "causal_role": "setup", "event": {"text": "orchard pumps drained the wells"}},
             {"n": 2, "causal_role": "intervention", "event": {"text": "farmers imported canal water"}},
             {"n": 3, "causal_role": "hinge", "event": {"text": "except the canal silted"}},
             {"n": 4, "causal_role": "mechanism", "beat_id": "b_mech",
              "event": {"text": "silt settled because the gradient was flat"}}]
    for i in range(n_escalations):
        beats.append({"n": 5 + i, "causal_role": "escalation", "beat_id": f"b_esc{i}",
                      "event": {"text": f"escalation number {i} flooded the village meadow{i}"}})
    beats.append({"n": 5 + n_escalations, "causal_role": "escalation", "beat_id": "b_cont",
                  "beat_part": 2, "beat_part_count": 2, "event": {"text": "and kept flooding"}})
    beats.append({"n": 6 + n_escalations, "causal_role": "reversal", "event": {"text": "the wells came back"}})
    beats.append({"n": 7 + n_escalations, "causal_role": "synthesis", "beat_id": "b_syn", "event": {}})
    beats.append({"n": 8 + n_escalations, "causal_role": "tool", "event": {"text": "look at the pumps"}})
    return beats


def test_the_synthesis_budget_scales_with_the_chain(monkeypatch):
    monkeypatch.setattr(ep, "_SYNTHESIS_WORDS_PER_BEAT", 7)
    few = ep._causal_word_budgets(_beats(2), 800, "removed_keystone", "Imagine you keep an orchard.")
    many = ep._causal_word_budgets(_beats(8), 800, "removed_keystone", "Imagine you keep an orchard.")
    syn_few = few[max(k for k, _ in few.items() if _beats(2)[k - 1]["causal_role"] == "synthesis")]
    syn_many = many[max(k for k, _ in many.items() if _beats(8)[k - 1]["causal_role"] == "synthesis")]
    assert 48 <= syn_few <= 49, "6% of 800 wins when the chain is short (the fill may top it up to the scene cap)"
    assert syn_many == 63, "nine chain beats (one mechanism, eight escalations) need 7 words each"
    assert syn_many <= 70, "never above the contract's own maximum"


def test_the_synthesis_row_gets_a_checklist_and_other_rows_do_not():
    beats = _beats(3)
    synthesis = next(b for b in beats if b["causal_role"] == "synthesis")
    checklist = ep._synthesis_must_echo(beats, synthesis)
    assert [c["beat_id"] for c in checklist] == ["b_mech", "b_esc0", "b_esc1", "b_esc2"], \
        "every chain beat before it, in order, continuations excluded"
    assert all(c["echo_one_of"] for c in checklist)
    assert "silt" in checklist[0]["echo_one_of"] or "gradi" in checklist[0]["echo_one_of"]
    assert ep._synthesis_must_echo(beats, beats[0]) == []


def test_the_second_state_of_an_opening_scene_buys_its_own_picture():
    script = _script()
    first = script["scenes"][0]["visual_beats"]
    first.insert(1, _beat("a crop of the mark", "fresh wet mud below the red mark",
                          "a close crop of the red mark", source="reframe"))
    plan = le.compile_evidence_plan(script)
    states = plan["scenes"][0]["states"]
    assert states[1]["asset_strategy"] == "distinct" and not states[1]["source_asset_id"]
    promoted = [r for r in plan["repairs"] if r["code"] == "opening_reframe_promoted"]
    assert promoted and "second state" in promoted[0]["message"]
    assert plan["validation"]["passed"]


def test_a_sentence_opener_before_a_nationality_is_not_a_person():
    """V14 (2026-10-08): "Where European bees..." stopped the run as an unsourced person."""
    dossier = {"claims": [{"claim": "Warwick Kerr imported African queens to Rio Claro in 1956."}]}
    script = {"scenes": [
        {"causal_role": "setup", "narration": "Where European bees struggle, your jars stay light."},
        {"causal_role": "intervention", "narration": "So Warwick Kerr brings African queens."},
        {"causal_role": "hinge", "narration": "Except the screens come off."},
        {"causal_role": "escalation", "narration": "By spring Maria Silva counts the losses."},
    ]}
    findings = ep._opening_identity_findings(script, dossier)
    assert [f["scene"] for f in findings] == [4], "only the invented person is flagged"
    assert "Maria Silva" in findings[0]["message"]
