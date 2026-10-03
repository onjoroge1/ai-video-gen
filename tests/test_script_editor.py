"""The targeted editor: defects are detected without a model and an edit is accepted only
when the gates say the defects are gone."""
import json

import explainer_pipeline as ep
import script_editor as se


def _scene(beat, text, role="escalation", continues="", event=""):
    return {"beat_id": beat, "narration": text, "causal_role": role, "continues": continues,
            "event": {"text": event or text, "claim_refs": ["c1"]}}


def _script():
    return {"hook": "Brazil imported African bees to make more honey",
            "_cold_open": "Twenty-six African queens and their swarms pour out of an apiary south of Sao Paulo",
            "scenes": [
                _scene("event_01", "Brazil imported African bees to make more honey. Twenty-six African queens and their swarms pour out of an apiary south of Sao Paulo. Colonists had carried European bees to the Americas.", role="setup"),
                _scene("event_02", "In 1956 queens arrived at a research apiary at Rio Claro for a breeding program.", role="intervention"),
                _scene("event_03", "In 1957, twenty-six African queens and their swarms escaped the experimental apiary south of Sao Paulo."),
                _scene("event_04", "As we saw, the hybrids moved two hundred miles a year. Explained like you are five."),
                _scene("event_05", "Africanized bees now defend hives from Argentina to the American southwest.", role="reversal"),
            ]}


def test_detect_defects_names_the_scene_and_the_code():
    found = {(d["scene"], d["code"]) for d in se.detect_defects(_script())}
    assert (3, se.COLD_OPEN_RESTATED) in found or (3, se.REPEAT) in found
    assert (4, se.META_PHRASE) in found and (4, se.FILLER) in found


def test_edit_is_refused_when_a_defect_survives(monkeypatch):
    script = _script()
    defects = se.detect_defects(script)

    class _Resp:
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 10})()
        content = [type("C", (), {"text": json.dumps({"scenes": [
            {"scene": d["scene"], "narration": script["scenes"][d["scene"] - 1]["narration"]}
            for d in defects]})})()]

    class _Client:
        class messages:
            @staticmethod
            def create(**_):
                return _Resp()
    monkeypatch.setattr(ep, "_claude", lambda: _Client)
    edited, cost, remaining = se.edit(script, {"claims": []}, defects, [], lambda m: None)
    assert edited is script and remaining == defects


def test_edit_is_accepted_when_the_gates_clear(monkeypatch):
    script = _script()
    defects = se.detect_defects(script)
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: {"passed": True})
    fixes = {3: "The breach came in October 1957: a visiting keeper lifted the excluder grids and the queens left with their workers.",
             4: "The hybrids moved two hundred miles a year, colony by colony, across the Brazilian interior."}

    class _Resp:
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 10})()
        content = [type("C", (), {"text": json.dumps({"scenes": [
            {"scene": i, "narration": fixes[i]} for i in sorted({d["scene"] for d in defects})]})})()]

    class _Client:
        class messages:
            @staticmethod
            def create(**_):
                return _Resp()
    monkeypatch.setattr(ep, "_claude", lambda: _Client)
    edited, cost, remaining = se.edit(script, {"claims": []}, defects, [], lambda m: None)
    assert edited is not script and remaining == []
    assert edited["scenes"][2]["narration"].startswith("The breach came")
    assert se.detect_defects(edited) == []
