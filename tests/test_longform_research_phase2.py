import json
from types import SimpleNamespace

import explainer_pipeline as pipeline
from longform_research import validate_claim_joins, validate_research_dossier


SOURCE = "https://science.example.edu/tide-study"
QUOTE = "The regional gauge rose two meters during the ten-year observation period."


def _dossier(**claim_updates):
    claim = {
        "claim_id": "c01",
        "claim": "A regional gauge rose two meters over ten years.",
        "source_url": SOURCE,
        "support_quote": QUOTE,
        "source_type": "primary",
        "calculation": "end minus start",
        "assumptions": [],
        "geographic_scope": "regional",
        "timescale": "ten years",
        "confidence": "high",
        "allowed_exaggeration": False,
        "material": True,
    }
    claim.update(claim_updates)
    return {
        "version": 1,
        "topic": "Why did the gauge move?",
        "citation_urls": [SOURCE],
        "citation_records": [{"url": SOURCE, "cited_text": QUOTE}],
        "claims": [claim],
    }


def _script(narration="A regional gauge rose two meters over ten years.", **scene_updates):
    scene = {
        "narration": narration,
        "story_role": "mechanism",
        "evidence_id": "e01",
        "claim_refs": [{
            "claim_id": "c01",
            "narration_phrase": narration,
            "evidence_id": "e01",
        }],
    }
    scene.update(scene_updates)
    return {"scenes": [scene]}


def _codes(report):
    return {error["code"] for error in report["errors"]}


def test_complete_source_claim_narration_evidence_join_passes():
    assert validate_research_dossier(_dossier())["passed"] is True
    report = validate_claim_joins(_script(), _dossier())
    assert report["passed"] is True
    assert report["used_claim_ids"] == ["c01"]


def test_source_url_must_come_from_provider_citations():
    report = validate_research_dossier(_dossier(source_url="https://invented.example/fake"))
    assert "unverified_source" in _codes(report)


def test_support_quote_must_be_observed_for_the_same_source():
    report = validate_research_dossier(_dossier(support_quote="Invented support text."))
    assert "unverified_support_quote" in _codes(report)


def test_scope_inflated_claim_is_rejected_in_dossier():
    report = validate_research_dossier(_dossier(
        claim="This happens globally everywhere.", geographic_scope="local"))
    assert "scope_inflation" in _codes(report)


def test_comparison_label_does_not_globalize_regional_claim():
    # Regression from the paid cane-toad canary: c29's comparison label said
    # "worldwide", while the sourced assertion explicitly said "American West".
    source = "https://nas.er.usgs.gov/queries/factsheet.aspx?SpeciesID=846"
    quote = "Introduced mosquitofish have been particularly destructive in the American West"
    dossier = _dossier(
        claim_id="c29", source_url=source, support_quote=quote,
        claim="COMPARABLE CASE (worldwide): USGS reports mosquitofish have been "
              "particularly destructive in the American West.")
    dossier["citation_urls"] = [source]
    dossier["citation_records"] = [{"url": source, "cited_text": quote}]
    assert validate_research_dossier(dossier)["passed"] is True


def test_comparison_label_cannot_hide_global_assertion():
    for claim in (
        "COMPARABLE CASE (worldwide): This happens globally everywhere.",
        "COMPARABLE CASE (American West): This happens worldwide.",
        "COMPARABLE CASE (worldwide) This happens in a regional gauge.",
        "This happens worldwide: COMPARABLE CASE (American West).",
    ):
        report = validate_research_dossier(_dossier(claim=claim))
        assert "scope_inflation" in _codes(report), claim


def test_global_comparison_label_is_still_checked_when_narrated():
    narration = "COMPARABLE CASE (worldwide): A regional gauge rose two meters."
    report = validate_claim_joins(_script(narration), _dossier())
    assert "scope_inflation" in _codes(report)


def test_weak_community_source_is_rejected_even_if_cited():
    url = "https://www.reddit.com/r/science/example"
    dossier = _dossier(source_url=url)
    dossier["citation_urls"] = [url]
    assert "weak_source_domain" in _codes(validate_research_dossier(dossier))


def test_scope_inflated_narration_is_rejected():
    narration = "This local result proves the gauge rises globally."
    report = validate_claim_joins(_script(narration), _dossier(geographic_scope="local"))
    assert "scope_inflation" in _codes(report)


def test_unknown_claim_and_missing_evidence_are_rejected():
    script = _script(evidence_id="")
    script["scenes"][0]["claim_refs"][0]["claim_id"] = "c99"
    report = validate_claim_joins(script, _dossier())
    assert {"unknown_claim", "missing_evidence_join"}.issubset(_codes(report))


def test_speculation_requires_explicit_hedging():
    narration = "The coastline will collapse."
    report = validate_claim_joins(_script(narration), _dossier(confidence="speculative"))
    assert "unhedged_speculation" in _codes(report)


def test_long_timescale_cannot_be_narrated_as_instant():
    narration = "The change happens instantly."
    report = validate_claim_joins(_script(narration), _dossier(timescale="millions of years"))
    assert "timescale_contradiction" in _codes(report)


def test_factcheck_cannot_silently_break_exact_claim_phrase():
    script = _script()
    script["scenes"][0]["narration"] = "A corrected but unbound factual sentence."
    report = validate_claim_joins(script, _dossier())
    assert "claim_phrase_not_in_narration" in _codes(report)


def test_factual_scene_without_claim_reference_is_rejected():
    report = validate_claim_joins(
        _script("Because gravity changes, the tide rises.", claim_refs=[]), _dossier())
    assert "unbound_factual_scene" in _codes(report)


def test_provider_citation_extraction_ignores_urls_only_written_by_model():
    blocks = [
        SimpleNamespace(
            text='{"source_url":"https://invented.example/fake"}',
            model_dump=lambda: {"type": "text", "text": "https://invented.example/fake", "citations": []},
        ),
        SimpleNamespace(
            text="",
            model_dump=lambda: {"type": "web_search_tool_result", "content": [{"url": SOURCE}]},
        ),
        SimpleNamespace(
            text="supported statement",
            model_dump=lambda: {"type": "text", "text": "supported statement", "citations": [{
                "type": "web_search_result_location", "url": SOURCE, "cited_text": QUOTE}]},
        ),
    ]
    assert pipeline._provider_citation_urls(SimpleNamespace(content=blocks)) == [SOURCE]
    assert pipeline._provider_citation_records(SimpleNamespace(content=blocks)) == [
        {"url": SOURCE, "cited_text": ""}, {"url": SOURCE, "cited_text": QUOTE}]


def test_research_generation_uses_bounded_server_search_and_validates(monkeypatch):
    import claim_verify
    # The model response is a fixture; its cited source must be one as well.
    monkeypatch.setattr(claim_verify, "fetch_page_text", lambda url, **kwargs: QUOTE)
    dossier = _dossier()
    dossier.pop("citation_urls")
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            blocks = [
                SimpleNamespace(text=json.dumps(dossier), model_dump=lambda: {
                    "type": "text", "text": json.dumps(dossier), "citations": []}),
                SimpleNamespace(text="", model_dump=lambda: {
                    "type": "web_search_tool_result", "content": [{
                        "url": SOURCE, "cited_text": QUOTE}]}),
            ]
            return SimpleNamespace(
                content=blocks,
                usage=SimpleNamespace(
                    input_tokens=10, output_tokens=10,
                    server_tool_use=SimpleNamespace(web_search_requests=2)),
            )

    monkeypatch.setenv("SCRIPT_PROVIDER", "openai")
    monkeypatch.setattr(pipeline, "_claude", lambda: pytest.fail("research used text-only adapter"))
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: SimpleNamespace(messages=Messages()))
    result = pipeline.generate_research_dossier("Why did the gauge move?", cost_sink=[])
    assert result["validation"]["passed"] is True
    assert calls[0]["tools"][0]["type"] == "web_search_20260318"
    assert calls[0]["tools"][0]["max_uses"] == 5
    assert result["web_search_requests"] == 2
    assert result["search_cost_reservation_usd"] == 0.2


def test_a_two_era_dossier_is_named_before_the_beat_sheet_is_bought():
    """"Why don't Americans eat hippo meat?" returned 21 verified claims -- more than the Hanoi
    dossier that works -- split between a 1910 congressional episode and modern African
    conservation. The planner built one spine from both: `world_without_it` came back as a 2006
    IUCN listing for a bill that died in 1910. Nothing noticed until three runs later."""
    import longform_research as lr

    dossier = {"claims": [
        {"claim_id": "c1", "verified": True,
         "claim": "In 1910 Robert Broussard introduced the American Hippo Bill."},
        {"claim_id": "c2", "verified": True,
         "claim": "The hippo has been listed as Vulnerable on the IUCN Red List since 2006."},
        {"claim_id": "c3", "verified": True,
         "claim": "A 2008 assessment counted 115,000 hippos across Africa."}]}
    split = lr.era_split(dossier)
    assert split["spans_eras"] and len(split["clusters"]) == 2
    assert [c["from"] for c in split["clusters"]] == [1910, 2006]
    assert "two stories" in lr.era_split_report(split)


def test_a_history_written_later_is_not_era_drift():
    """The Hanoi dossier -- the one that works -- cites Vann's 2003 history of a 1902 bounty.

    Reading a publication date as a century of drift flagged the exact story this check exists to
    leave alone. A comparable case is excluded for the same reason: it is SUPPOSED to come from
    another time and place.
    """
    import longform_research as lr

    dossier = {"claims": [
        {"claim_id": "c1", "verified": True,
         "claim": "In April 1902 the colonial authorities announced a bounty on every dead rat."},
        {"claim_id": "c2", "verified": True,
         "claim": "Michael G. Vann published a peer-reviewed academic account of the episode "
                  "in 2003."},
        {"claim_id": "c3", "verified": True,
         "claim": "COMPARABLE CASE (USA, 2007): Fort Benning offered a bounty per pig tail."}]}
    split = lr.era_split(dossier)
    assert not split["spans_eras"], "one episode, one period"
    assert lr.era_split_report(split) == ""


def test_a_single_period_dossier_reports_nothing():
    import longform_research as lr
    assert not lr.era_split({"claims": []})["spans_eras"]
    assert not lr.era_split({"claims": [{"claim_id": "c1", "verified": True,
                                         "claim": "No dates here at all."}]})["spans_eras"]


def test_no_dossier_is_not_a_failure():
    """The causal lane reaches this with research off; crashing there turns absence into a fault."""
    import longform_research as lr
    for empty in (None, {}, {"claims": None}):
        assert lr.era_split(empty)["spans_eras"] is False
