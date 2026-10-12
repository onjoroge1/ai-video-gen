"""Radium Girls (2026-10-12): an approved sheet keeps its roles, and claim-free myth lines fold
into the first sourced beat instead of being labelled setup and intervention."""
import explainer_pipeline as ep


def _beat(n, text, claims=(), role="", caused_by=None):
    return {"n": n, "beat": text, "causal_role": role, "caused_by": n - 1 if caused_by is None else caused_by,
            "event": {"text": text if claims else "", "claim_refs": list(claims)},
            "claim_refs": [{"claim_id": c} for c in claims]}


def test_claim_free_opening_lines_fold_into_the_first_sourced_beat():
    plan = {"hook": "You'd think radium was feared from the very start.", "mechanism_beat": 5}
    beats = [_beat(1, "You'd think radium was feared from the very start."),
             _beat(2, "Picture the job: steady pay and glowing numbers."),
             _beat(3, "From 1917 women were hired to paint dials.", ["c10"], "setup"),
             _beat(4, "They were told radium was good for them.", ["c18"], "false_resolution"),
             _beat(5, "Radium behaves like calcium.", ["c23"], "mechanism")]
    out = ep._fold_opening_lines(plan, beats)
    assert [b["n"] for b in out] == [1, 2, 3]
    assert out[0]["causal_role"] == "setup" and out[0]["beat"].startswith("Picture the job")
    assert "You'd think" not in out[0]["beat"], "the hook line is prepended anyway; never twice"
    assert out[0]["opening_lines"] == ["Picture the job: steady pay and glowing numbers."]
    assert plan["mechanism_beat"] == 3 and out[2]["caused_by"] == 2


def test_a_sheet_that_opens_on_a_sourced_beat_is_unchanged():
    plan = {"hook": "h", "mechanism_beat": 2}
    beats = [_beat(1, "From 1917 women were hired.", ["c10"], "setup"),
             _beat(2, "Radium behaves like calcium.", ["c23"], "mechanism")]
    assert ep._fold_opening_lines(plan, beats) is beats and plan["mechanism_beat"] == 2


def test_the_labeller_is_skipped_only_for_an_approved_sheet_with_every_role_set():
    import inspect
    source = inspect.getsource(ep._generate_script_chunked)
    assert 'if _approved and all(_s(b.get("causal_role")) for b in beats):' in source
    assert "operator-approved roles kept; labelling skipped" in source
