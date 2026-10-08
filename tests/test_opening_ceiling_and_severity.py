"""The hook addresses the viewer; the ledger must not read that address as a claim.

Lane B of the clean V4 run died with eight findings. Six were fidelity rows, correctly marked
soft, and they were the six the error message printed. The two that actually refused the script
fell off the end of the list:

  COLD_OPEN_EXCEEDS_CLAIM  unsupported detail: "Brazilian"      (on a film about Brazil)
  HOOK_EXCEEDS_STORY       unsupported detail: "Your honey jar could trace back to ..."

Neither carried a severity, so both blocked unconditionally while the harmless six were waved
through. And the hook finding is a contradiction between two requirements in the same pipeline:
the opening contract REQUIRES a literal "you" or "your" -- the one device the corpus never omits
and our films never had -- and the ledger was refusing it for being undocumented. No document
records the viewer's honey jar, and none ever will.

So the hook now carries a ceiling, as the cold open already did: second-person framing is
rhetoric and is never flagged, while every name, number, date and place in it stays bound.
"""
import json
import os

import longform_research as lr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _known():
    path = os.path.join(ROOT, "jobs", "killerbees02", "research_dossier.json")
    if not os.path.exists(path):
        return "african honey bees were imported into brazil in 1956 by kerr."
    with open(path) as handle:
        return lr._known_evidence_text(json.load(handle))


def test_a_stem_of_the_films_own_subject_is_soft():
    """The cold open's SOLE objection was the word "Brazilian". It killed the run."""
    assert lr.fidelity_severity(["Brazilian"], _known(), "partially_entailed") == "soft"


def test_an_invented_year_still_blocks():
    assert lr.fidelity_severity(["The year was 1962."], _known(), "partially_entailed") == "material"


def test_the_hook_is_judged_against_a_ceiling_that_permits_addressing_the_viewer():
    """The ceiling, not the judge's mood, is what stops "your honey jar" being a claim."""
    seen = {}

    def judge(payload):
        seen.update(payload)
        return {"verdict": "entailed", "reason": "stub"}

    script = {"hook": "Your honey jar could trace back to African bees.",
              "scenes": [{"beat_id": "event_1", "causal_role": "setup",
                          "narration": "Bees arrived.",
                          "event": {"text": "African honey bees arrived in Brazil.",
                                    "claim_refs": ["c1"]}}]}
    dossier = {"claims": [{"claim_id": "c1",
                           "claim": "African honey bees were imported into Brazil in 1956."}]}
    lr.validate_story_fact_model(script, dossier, judge=judge, cache={})
    ceiling = " ".join(str(v) for v in seen.values())
    assert "rhetorical address" in ceiling, (
        "the hook reached the judge with no ceiling, so a literal 'your' reads as a claim")
    assert "Flag ONLY an invented actor" in ceiling


def test_both_opening_findings_carry_a_severity():
    """Without one they block unconditionally, whatever the finding says."""
    def judge(payload):
        if payload.get("kind") == "fidelity":
            return {"verdict": "partially_entailed", "supported_core": "core",
                    "unsupported_details": ["Brazilian"], "reason": "stub"}
        return {"verdict": "entailed", "reason": "stub"}

    script = {"hook": "Your honey jar traces back to Brazilian bees.",
              "_cold_open": "A Brazilian hive box stands open.",
              "_cold_open_claim_refs": ["c1"],
              "scenes": [{"beat_id": "event_1", "causal_role": "setup",
                          "narration": "Bees arrived.",
                          "event": {"text": "African honey bees arrived in Brazil.",
                                    "claim_refs": ["c1"]}}]}
    dossier = {"claims": [{"claim_id": "c1",
                           "claim": "African honey bees were imported into Brazil in 1956."}]}
    report = lr.validate_story_fact_model(script, dossier, judge=judge, cache={})
    opening = [e for e in report["errors"]
               if e["code"] in ("HOOK_EXCEEDS_STORY", "COLD_OPEN_EXCEEDS_CLAIM")]
    for error in opening:
        assert "severity" in error, f"{error['code']} blocks unconditionally: {error}"
