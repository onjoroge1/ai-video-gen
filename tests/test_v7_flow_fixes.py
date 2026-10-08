"""Killer bees V7 (2026-10-06): three attempts, and the weakest one shipped.

Attempt 1 held the best script of the day (774 words, runtime contract PASS at 284 s, storyboard
PASS) and died because ONE of eight opening evidence states was rejected after two redraws.
Attempt 3 replanned a draft whose only defect was an 11-word hinge -- a replan that cost a
90-scoring hook and 240 words -- and the cold-open retry that followed swapped the hook for a
48 that named Warwick Kerr, with nothing in the log. These tests pin the four mechanisms.
"""
import explainer_pipeline as ep
import longform_research as lr


# ── replan is not the answer to a bounded edit ────────────────────────────────────────────────

def _wrapped(*messages):
    """The long-form contract's shape: every storyboard finding wrapped as engine_story_contract."""
    return {"passed": False, "score": 0,
            "errors": [{"code": "engine_story_contract", "message": m} for m in messages]}


def test_blocking_codes_read_through_the_contract_wrapper():
    v = _wrapped("SOFT_HINGE: the hinge is 11 words; it lands in 10 or fewer or it is not a turn")
    assert ep._blocking_codes(v, ["SOFT_HINGE: the hinge is 11 words"]) == ["SOFT_HINGE", "SOFT_HINGE"]
    assert ep._blocking_codes({"passed": True, "errors": []}, [{"code": "NO_CALLBACK"}]) == ["NO_CALLBACK"]


def test_an_eleven_word_hinge_alone_does_not_replan():
    hinge = ["SOFT_HINGE: the hinge is 11 words; it lands in 10 or fewer or it is not a turn"]
    assert ep._only_repairable_timing_blocks(_wrapped(*hinge), hinge)
    late = ["LATE_MECHANISM: the mechanism lands at 62s, past the 58s mark"]
    assert ep._only_repairable_timing_blocks(_wrapped(*late), late)


def test_a_real_story_defect_behind_the_wrapper_still_replans():
    hinge = ["SOFT_HINGE: the hinge is 11 words"]
    both = _wrapped(hinge[0], "NO_HINGE: no step performs the hinge")
    assert not ep._only_repairable_timing_blocks(both, hinge)
    # A failed contract that explains nothing is not a known-bounded failure.
    assert not ep._only_repairable_timing_blocks({"passed": False, "errors": []}, hinge)
    # Hook length reads the same wrapper.
    long_hook = ["LONG_HOOK: the hook is 19 words against an 18-word budget"]
    assert ep._only_hook_length_blocks(_wrapped(*long_hook), long_hook)
    assert not ep._only_hook_length_blocks(_wrapped(long_hook[0], "NO_CALLBACK: never returns"), long_hook)


# ── the hook survives a planner re-ask that was asked to fix something else ───────────────────

GOOD = "You see a local beekeeper near Rio Claro in October 1957; twenty-six queens are the part nobody checked."
WEAK = "You watch Warwick Kerr bring African bees to Brazil; the bees are not the whole surprise."


def test_cold_open_retry_cannot_downgrade_the_hook(capsys):
    current = {"hook": GOOD, "cold_open": ""}
    retry = {"hook": WEAK, "cold_open": "A dark swarm boils from a hive box."}
    out = ep._carry_better_hook(current, retry, stage="cold-open")
    assert out["hook"] == GOOD
    assert out["cold_open"] == retry["cold_open"], "the retry still wins the field it fixed"
    assert "cold-open retry proposed a weaker hook" in capsys.readouterr().out


def test_a_retry_that_improves_the_hook_keeps_its_own():
    assert ep._carry_better_hook({"hook": WEAK}, {"hook": GOOD}, stage="spine")["hook"] == GOOD
    assert ep._carry_better_hook({"hook": ""}, {"hook": WEAK}, stage="spine")["hook"] == WEAK
    assert ep._carry_better_hook({"hook": GOOD}, None, stage="spine") is None


# ── one rejected opening state does not end a run ─────────────────────────────────────────────

def _states(n, rejected=()):
    return [{"state_id": f"s{i}", "asset_id": f"a{i}",
             "asset_status": "rejected" if i in rejected else "accepted",
             "rejection_reasons": ["A person is visibly present"] if i in rejected else []}
            for i in range(n)]


def test_one_of_eight_rejected_is_dropped_from_the_plan_in_place(capsys):
    plan_states = _states(8, rejected={7})
    result = {"i": 0, "evidence_ok": False, "evidence_states": plan_states, "note": "evidence-rejected"}
    assert ep._opening_assets_policy(result, print)
    assert result["evidence_ok"] and result["img_ok"]
    assert len(plan_states) == 7 and all(s["asset_status"] == "accepted" for s in plan_states)
    assert result["evidence_dropped"][0]["state_id"] == "s7"
    assert "1 of 8 evidence state(s) rejected" in capsys.readouterr().out


def test_a_rejected_master_or_too_many_rejections_still_abort():
    master = {"i": 0, "evidence_ok": False, "evidence_states": _states(8, rejected={0})}
    assert not ep._opening_assets_policy(master, lambda m: None)
    three_of_eight = {"i": 0, "evidence_ok": False, "evidence_states": _states(8, rejected={5, 6, 7})}
    assert not ep._opening_assets_policy(three_of_eight, lambda m: None)
    # Small scenes have no slack: a 3-state scene needs all three, a 2-state scene both.
    assert not ep._opening_assets_policy({"i": 1, "evidence_ok": False, "evidence_states": _states(3, rejected={2})}, lambda m: None)
    assert not ep._opening_assets_policy({"i": 1, "evidence_ok": False, "evidence_states": _states(2, rejected={1})}, lambda m: None)
    # Nothing to decide: already fine, or no states at all.
    assert ep._opening_assets_policy({"evidence_ok": True}, lambda m: None)
    assert not ep._opening_assets_policy({"evidence_ok": False, "evidence_states": []}, lambda m: None)


# ── the spoken lead is lifted even when the hook field has moved on ───────────────────────────

def test_lead_is_lifted_verbatim_and_when_the_field_drifted():
    lead = GOOD + " European honey bees struggled in Brazil."
    assert lr._strip_spoken_lead(lead, GOOD) == ("European honey bees struggled in Brazil.", True)
    drifted = "You see a local beekeeper near Rio Claro in 1957; twenty-six queens are the part nobody checked."
    assert lr._strip_spoken_lead(lead, drifted) == ("European honey bees struggled in Brazil.", True)
    # A hook ending in "?" leaves no stray full stop behind.
    q = "Why did twenty-six queens matter?"
    assert lr._strip_spoken_lead(q + " Brazil wanted honey.", q) == ("Brazil wanted honey.", True)


def test_an_unrelated_first_sentence_is_not_lifted():
    lead = "European honey bees struggled in Brazil. Their temperate adaptation fit poorly."
    assert lr._strip_spoken_lead(lead, GOOD) == (lead, False)
    assert lr._strip_spoken_lead("", GOOD) == ("", False)
    assert lr._strip_spoken_lead(lead, "") == (lead, False)
