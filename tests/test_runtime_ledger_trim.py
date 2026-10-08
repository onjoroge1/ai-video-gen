"""The runtime-fit claim ledger gets the same last-resort trim as the script-stage ledger.

V13 resume (2026-10-08): the restored script re-judged one sentence as unsupported and the
runtime-fit twin refused the run with no trim, although the stage before it had the trim path.
"""
import explainer_pipeline as ep


def _report(failing: int) -> dict:
    return {"passed": failing == 0, "errors": [
        {"code": "NARRATION_EXCEEDS_EVENT", "severity": "material", "scene": f"event_{i}",
         "message": f"event_{i}: unsupported"} for i in range(failing)]}


def test_trims_and_rejudges_until_the_ledger_passes(monkeypatch):
    verdicts = iter([_report(1), _report(0)])
    trims = iter([1, 1, 1])
    calls = {"validate": 0, "trim": 0, "rebind": 0}

    def fake_validate(script, dossier, costs):
        calls["validate"] += 1
        return next(verdicts)

    def fake_trim(script, report, log):
        calls["trim"] += 1
        return next(trims)

    monkeypatch.setattr(ep, "_validate_claims", fake_validate)
    monkeypatch.setattr(ep, "_trim_unsupported_sentences", fake_trim)
    monkeypatch.setattr(ep, "rederive_narration_bindings",
                        lambda *a, **k: calls.__setitem__("rebind", calls["rebind"] + 1))
    script = {"scenes": []}
    result = ep._trim_until_ledger_passes(script, _report(2), {}, [], lambda m: None)
    assert result["passed"] is True
    assert calls == {"validate": 2, "trim": 2, "rebind": 2}
    assert script["_claim_validation"] is result


def test_stops_when_nothing_can_be_trimmed(monkeypatch):
    monkeypatch.setattr(ep, "_trim_unsupported_sentences", lambda *a, **k: 0)
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no re-judge without a trim")))
    failing = _report(1)
    assert ep._trim_until_ledger_passes({"scenes": []}, failing, {}, [], lambda m: None) is failing


def test_repair_runs_before_the_trim_and_returns_the_new_script(monkeypatch):
    verdicts = iter([_report(0)])
    repaired = {"scenes": [{"narration": "supported core"}], "_script_cost_usd": 1.0}
    seen = {}

    def fake_repair(script, dossier, report, operator_direction=""):
        seen["direction"] = operator_direction
        return repaired, 0.25

    monkeypatch.setattr(ep, "repair_claim_join_failures", fake_repair)
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    monkeypatch.setattr(ep, "_trim_unsupported_sentences",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no trim after a pass")))
    script, result = ep._repair_until_ledger_passes(
        {"scenes": []}, _report(1), {}, [], operator_direction="brief", log=lambda m: None)
    assert script is repaired and result["passed"] is True
    assert script["_script_cost_usd"] == 1.25 and seen["direction"] == "brief"


def test_repair_that_does_not_converge_falls_through_to_the_trim(monkeypatch):
    monkeypatch.setattr(ep, "repair_claim_join_failures",
                        lambda script, dossier, report, operator_direction="": (dict(script), 0.1))
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: _report(1))
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    calls = {"trim": 0}

    def fake_trim(script, report, log):
        calls["trim"] += 1
        return 0

    monkeypatch.setattr(ep, "_trim_unsupported_sentences", fake_trim)
    _, result = ep._repair_until_ledger_passes({"scenes": []}, _report(1), {}, [])
    assert result["passed"] is False and calls["trim"] == 1


def test_gives_up_after_the_round_limit(monkeypatch):
    monkeypatch.setattr(ep, "_trim_unsupported_sentences", lambda *a, **k: 1)
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: _report(1))
    monkeypatch.setattr(ep, "rederive_narration_bindings", lambda *a, **k: None)
    result = ep._trim_until_ledger_passes({"scenes": []}, _report(1), {}, [], lambda m: None, rounds=3)
    assert result["passed"] is False
