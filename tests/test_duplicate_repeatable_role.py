"""A repeated escalation that restates the mechanism is pruned, not a missing role (2026-10-02)."""
import story_fact_model as sfm


def _beat(bid, role, text, frm="", to=""):
    return {"beat_id": bid, "role": role, "event": {"text": text, "claim_refs": ["c1"]},
            "changes_state": {"from": frm, "to": to}}


def test_repeated_escalation_duplicating_mechanism_is_collapsible():
    beats = [
        _beat("b1", "setup", "Colonists carried a gentle temperate strain to the Americas in the 1600s"),
        _beat("b2", "intervention", "Brazil imported tropical queens in 1956 for a breeding program"),
        _beat("b3", "mechanism", "The escaped African bees formed hybrid populations with European honey bees",
              "European colonies", "hybrid Africanized colonies"),
        _beat("b4", "escalation", "Twenty-six African queens escaped with swarms in October 1957",
              "contained", "escaped"),
        _beat("b5", "escalation", "The African bee escapees formed hybrid populations with European honey bees",
              "European colonies", "hybrid Africanized colonies"),
        _beat("b6", "escalation", "The bees moved 200 to 300 miles a year and reached the United States in 1990",
              "Brazil", "United States"),
        _beat("b7", "reversal", "Africanized bees are now the feral honey bee from Argentina to the US southwest"),
    ]
    issues = sfm.duplicate_event_functions(beats, "removed_keystone")
    codes = [(i["code"], i["beat_id"], i.get("collapsible")) for i in issues]
    assert ("DUPLICATE_EVENT_FUNCTION", "b5", True) in codes
    assert not any(c == "DUPLICATE_ACROSS_REQUIRED_ROLES" for c, _, _ in codes)


def test_sole_escalation_duplicating_mechanism_still_blocks():
    beats = [
        _beat("b1", "setup", "Colonists carried a gentle temperate strain to the Americas in the 1600s"),
        _beat("b2", "intervention", "Brazil imported tropical queens in 1956 for a breeding program"),
        _beat("b3", "mechanism", "The escaped African bees formed hybrid populations with European honey bees",
              "European colonies", "hybrid Africanized colonies"),
        _beat("b5", "escalation", "The African bee escapees formed hybrid populations with European honey bees",
              "European colonies", "hybrid Africanized colonies"),
        _beat("b7", "reversal", "Africanized bees are now the feral honey bee from Argentina to the US southwest"),
    ]
    issues = sfm.duplicate_event_functions(beats, "removed_keystone")
    assert any(i["code"] == "DUPLICATE_ACROSS_REQUIRED_ROLES" and not i.get("collapsible") for i in issues)
