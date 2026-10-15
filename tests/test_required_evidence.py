"""A direction's REQUIRED ... EVIDENCE paragraph reaches the research request (2026-10-15).

Research is commissioned from the question alone, so the evidence a film cannot be made without --
the hippo remake's witness, Alvaro Molina -- must be carried into the request explicitly. Every
other request stays byte-identical, so cached dossiers and ledger keys are unaffected.
"""
import explainer_pipeline as ep

DIRECTION = (
    "OPENING: the witness.\n\n"
    "REQUIRED WITNESS EVIDENCE (research must return this as its own claim): what happened to\n"
    "Alvaro Molina near Puerto Triunfo -- CBS at https://www.cbsnews.com/news/x/.\n"
    "- quote the canoe sentence\n"
    "\n"
    "NO COMPARISON CASES: every beat is this story.\n")


def test_the_paragraph_is_extracted_and_flattened():
    text = ep._required_evidence(DIRECTION)
    assert text.startswith("REQUIRED WITNESS EVIDENCE") and "Alvaro Molina" in text
    assert "quote the canoe sentence" in text and "\n" not in text
    assert "NO COMPARISON CASES" not in text, "stops at the blank line"
    assert ep._required_evidence("OPENING: plain.\n\nVerify: dates.") == ""
    assert ep._required_evidence("") == ""


def test_the_request_heading_is_stripped_from_claim_text():
    dossier = {"claims": [
        {"claim_id": "c33", "claim": "REQUIRED WITNESS EVIDENCE: Álvaro Molina, 57, was out fishing."},
        {"claim_id": "c35", "claim": "REQUIRED WITNESS EVIDENCE (AMP mirror confirmation): The CBS page agrees."},
        {"claim_id": "c54", "claim": "COMPARABLE CASE (Everglades): pythons spread."},
        {"claim_id": "c01", "claim": "Escobar imported four hippos."}]}
    texts = [c["claim"] for c in ep._strip_evidence_labels(dossier)["claims"]]
    assert texts[0] == "Álvaro Molina, 57, was out fishing."
    assert texts[1] == "The CBS page agrees."
    assert texts[2].startswith("COMPARABLE CASE"), "the comparable-case marker is a pipeline convention"
    assert texts[3] == "Escobar imported four hippos."


def _captured_prompt(monkeypatch, **kwargs):
    seen = {}

    def fake_cache(question, prompt, log):
        seen["prompt"] = prompt
        return {"claims": [{"claim_id": "c01", "claim": "stub"}]}

    monkeypatch.setattr(ep, "_cached_research_dossier", fake_cache)
    ep.generate_research_dossier("Why can't Colombia stop the hippos?", duration_sec=300, **kwargs)
    return seen["prompt"]


def test_required_evidence_reaches_the_request_and_is_absent_otherwise(monkeypatch):
    plain = _captured_prompt(monkeypatch)
    assert "REQUIRED EVIDENCE" not in plain
    named = _captured_prompt(monkeypatch, required_evidence=ep._required_evidence(DIRECTION))
    assert "REQUIRED EVIDENCE named by the operator" in named and "Alvaro Molina" in named
    # same request otherwise: the paragraph is the only difference
    assert named.replace(named[named.index("REQUIRED EVIDENCE"):named.index("Ask for more")], "") == plain
