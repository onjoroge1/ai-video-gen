"""Separate sourced facts may support one event; topic overlap alone still cannot."""
from unittest.mock import Mock

import pytest

import claim_verify
import research_coverage as coverage
from test_evidence_coverage import INTRO, STUDIES, Judge, dossier, fixture, prepare

DATE = "The cane toad release was in 1935."
COMPOUND = INTRO + " " + DATE


class CompositionJudge(Judge):
    def __call__(self, payload):
        if payload["event"] == COMPOUND:
            self.calls.append(payload)
            text = " ".join(c["claim"] for c in payload["claims"])
            if INTRO in text and DATE in text:
                return {"verdict": "entailed"}
            return {"verdict": "partially_entailed", "supported_core": INTRO if INTRO in text else STUDIES,
                    "unsupported_details": ["Missing introduction fact or date"]}
        return super().__call__(payload)


def inputs(monkeypatch):
    beats, data = fixture()
    beats[1]["event"]["text"] = beats[1]["beat"] = COMPOUND
    judge = CompositionJudge()
    report = prepare(beats, data, judge)
    assert not report["passed"]
    data["claims"][0].update(quote_verified=True, source_reachable=True)
    data["claims"][4].update(quote_verified=True, source_reachable=True)
    pages = {data["claims"][0]["source_url"]: INTRO, data["claims"][4]["source_url"]: DATE}
    monkeypatch.setattr(claim_verify, "fetch_page_text", lambda url, **kw: pages[url])
    return beats, data, judge, report, pages


def test_two_source_quotes_support_one_event_without_a_new_search(monkeypatch):
    beats, data, judge, report, pages = inputs(monkeypatch)
    generate = Mock(side_effect=AssertionError("The two existing sources suffice"))
    repaired = coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    assert repaired and generate.call_count == 0
    added = repaired["dossier"]["claims"][len(data["claims"]):]
    assert len(added) == 2
    assert {c["source_url"] for c in added} == set(pages)
    for claim in added:
        assert claim["claim"] == claim["support_quote"] == pages[claim["source_url"]]
        assert claim["claim"] != COMPOUND  # No composite assertion attributed to only one page.
    assert repaired["beats"][1]["event"]["text"] == COMPOUND
    assert prepare(repaired["beats"], repaired["dossier"], judge)["passed"]


def test_supported_core_can_drop_a_date_but_preserves_intervention_purpose(monkeypatch):
    beats, data, judge, report, pages = inputs(monkeypatch)
    pages[data["claims"][4]["source_url"]] = ""
    repaired = coverage.repair_sheet("Question", beats, report, data,
                                    generate=Mock(side_effect=AssertionError("No need to source an optional date")),
                                    judge=judge)
    assert repaired
    checked = prepare(repaired["beats"], repaired["dossier"], judge)
    assert checked["passed"]
    assert checked["effective_beats"][1]["event"]["text"] == INTRO


def test_absence_of_studies_cannot_replace_the_intervention(monkeypatch):
    beats, data, judge, report, pages = inputs(monkeypatch)
    pages[data["claims"][0]["source_url"]] = STUDIES
    generate = Mock(return_value=dossier([(INTRO, "event")]))
    coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    assert generate.call_count == 1
    assert generate.call_args.kwargs["evidence_gaps"][0]["assertion_to_verify"] == COMPOUND


def test_contradictory_source_bundle_stops_before_more_research(monkeypatch):
    beats, data, _, report, _ = inputs(monkeypatch)
    generate = Mock(side_effect=AssertionError("Do not shop for evidence after a contradiction"))
    judge = Mock(return_value={"verdict": "contradicted", "reason": "Source contradicts the proposed intervention"})
    with pytest.raises(ValueError, match="contradict a required story event"):
        coverage.repair_sheet("Question", beats, report, data, generate=generate, judge=judge)
    assert generate.call_count == 0


def test_saved_verified_quote_remains_usable_when_refetch_fails(monkeypatch):
    beats, data, judge, report, _ = inputs(monkeypatch)
    for number, text in enumerate((INTRO, DATE), 6):
        data["claims"].append(dict(data["claims"][0], claim_id=f"c{number}",
                                   claim=text, support_quote=text, claim_kind="event"))
    data["citation_records"] = [{"url": c["source_url"], "cited_text": c["support_quote"]} for c in data["claims"]]
    monkeypatch.setattr(claim_verify, "fetch_page_text", lambda *a, **kw: "")
    repaired = coverage.repair_sheet("Question", beats, report, data,
                                    generate=Mock(side_effect=AssertionError("Exact saved quotes exist")), judge=judge)
    assert repaired and prepare(repaired["beats"], repaired["dossier"], judge)["passed"]
