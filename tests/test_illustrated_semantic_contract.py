"""Regression coverage for the production failures found in the illustrated-flow audit."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import explainer_pipeline as ep
from longform_research import (
    quarantine_contradicted_claims,
    validate_claim_joins,
    validate_research_dossier,
)
from test_causal_lane_integration import _capture_beat_prompt, _capture_expansion_prompt
from test_longform_research_phase2 import _dossier
from durable_execution import AmbiguousProviderOutcome, BudgetExceeded, activate
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


def _script(narration, *, phrase, confidence="high", claim_text=None, quote=None):
    dossier = _dossier()
    claim = dossier["claims"][0]
    claim["confidence"] = confidence
    if claim_text is not None:
        claim["claim"] = claim_text
    if quote is not None:
        claim["support_quote"] = quote
        dossier["citation_records"][0]["cited_text"] = quote
    return ({
        "scenes": [{
            "narration": narration,
            "story_role": "escalation",
            "evidence_id": "e01",
            "claim_refs": [{
                "claim_id": "c01", "evidence_id": "e01",
                "narration_phrase": phrase,
            }],
        }]
    }, dossier)


def _codes(report):
    return {issue["code"] for issue in report["errors"]}


def test_claim_rebinding_preserves_the_complete_assertion_and_its_qualifier():
    narration = "At the city's edge, some accounts suggest farmers might have raised rats for bounties."
    script, dossier = _script(
        narration, phrase="farmers raised rats", confidence="speculative",
        claim_text="Some accounts suggest farmers might have raised rats for bounties.",
        quote="Some accounts suggest farmers might have raised rats for bounties.",
    )

    assert ep._repair_claim_phrases(script, research_dossier=dossier) == 1
    assert script["scenes"][0]["claim_refs"][0]["narration_phrase"] == narration
    assert validate_claim_joins(script, dossier)["passed"] is True


def test_an_unrelated_claim_id_cannot_license_a_different_assertion():
    narration = "The moon is made of cheese because astronauts found cheddar there."
    script, dossier = _script(narration, phrase=narration)

    report = validate_claim_joins(script, dossier)

    assert report["passed"] is False
    assert "claim_assertion_mismatch" in _codes(report)


def test_a_hedge_in_an_unrelated_sentence_cannot_license_certain_speculation():
    narration = "You might be surprised. Farmers definitely raised rats for the bounty."
    script, dossier = _script(
        narration, phrase="You might be surprised", confidence="speculative",
        claim_text="Farmers might have raised rats for the bounty.",
        quote="Farmers might have raised rats for the bounty.",
    )

    report = validate_claim_joins(script, dossier)

    assert report["passed"] is False
    assert {"claim_assertion_mismatch", "unbound_factual_assertion"} & _codes(report)


def test_negated_source_quote_cannot_support_a_positive_claim():
    dossier = _dossier()
    dossier["claims"][0]["claim"] = "The archive documents rat breeding for bounties."
    dossier["claims"][0]["support_quote"] = "The archive does not document rat breeding for bounties."
    dossier["citation_records"][0]["cited_text"] = dossier["claims"][0]["support_quote"]

    report = validate_research_dossier(dossier)

    assert report["passed"] is False
    assert "support_contradicts_claim" in _codes(report)


def test_incidental_negative_clause_does_not_invalidate_supported_fact():
    dossier = _dossier()
    quote = ("No archive proves every detail of the anecdote. However, the article describes "
             "Delhi officials paying cobra bounties.")
    dossier["claims"][0]["claim"] = "The article describes Delhi officials paying cobra bounties."
    dossier["claims"][0]["support_quote"] = quote
    dossier["citation_records"][0]["cited_text"] = quote

    report = validate_research_dossier(dossier)

    assert "support_contradicts_claim" not in _codes(report)


def test_directly_contradicted_candidate_is_quarantined_before_writing():
    dossier = _dossier()
    dossier["claims"][0]["claim"] = "The archive documents rat breeding for bounties."
    dossier["claims"][0]["support_quote"] = "The archive does not document rat breeding for bounties."

    filtered = quarantine_contradicted_claims(dossier)

    assert filtered["claims"] == []
    assert filtered["excluded_claims"][-1]["reason"] == "support_contradicts_claim"
    assert filtered["semantic_source_filter"] == {
        "version": 1, "candidate_count": 1, "retained_count": 0, "excluded_count": 1,
    }


def test_operator_block_keeps_the_end_of_an_approved_direction():
    direction = "A" * 1500 + " Distinguish the anecdote from documented history. Recurring cobra basket."

    block = ep._operator_block(direction)

    assert "Distinguish the anecdote from documented history" in block
    assert "Recurring cobra basket" in block


def test_approved_direction_reaches_real_planner_and_expansion_prompts(monkeypatch):
    direction = "Distinguish the anecdote from documented history. Recurring cobra basket."

    planner = _capture_beat_prompt(
        monkeypatch, causal_lane=True, operator_direction=direction)
    expansion = _capture_expansion_prompt(
        monkeypatch, causal_lane=True, operator_direction=direction)

    for prompt in (planner, expansion):
        assert "Distinguish the anecdote from documented history" in prompt
        assert "Recurring cobra basket" in prompt


def test_semantic_failure_persists_full_private_checkpoint(tmp_path):
    store, blob = MemoryStore(cap=5), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "diagnostic-worker")
    script, dossier = _script("A complete failed sentence.", phrase="failed sentence")
    report = {"passed": False, "errors": [{"code": "example"}]}

    with activate(worker):
        path = ep._persist_semantic_failure(
            output_dir=str(tmp_path), stage="claim-ledger", script=script,
            research_dossier=dossier, report=report,
            operator_direction="Keep the cobra caveat.")

    saved = json.loads(Path(path).read_text())
    assert saved["script"] == script
    assert saved["research_dossier"] == dossier
    assert saved["operator_direction"] == "Keep the cobra caveat."
    assert store.job["checkpoint"], "The diagnostic must survive local worker cleanup"


def test_transcription_is_a_metered_reusable_paid_stage(tmp_path, monkeypatch):
    audio = tmp_path / "scene.mp3"
    audio.write_bytes(b"audio")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(words=[SimpleNamespace(word="cobra", start=0, end=0.4)])

    monkeypatch.setattr(ep, "_openai", lambda: SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))))
    monkeypatch.setattr(ep, "_audio_dur", lambda _path: 30.0)
    store, blob = MemoryStore(cap=1), MemoryBlob(tmp_path / "blob")

    first = runtime(tmp_path, store, blob, "transcription-worker-1")
    with activate(first):
        assert ep.transcribe_words(str(audio), strict=True) == [("cobra", 0.0, 0.4)]
    spent = store.job["spent_cost_usd"]

    second = runtime(tmp_path, store, blob, "transcription-worker-2")
    with activate(second):
        assert ep.transcribe_words(str(audio), strict=True) == [("cobra", 0.0, 0.4)]

    assert len(calls) == 1
    assert spent == ep._RATE_TRANSCRIPTION_MINUTE
    assert store.job["spent_cost_usd"] == spent
    assert store.job["reserved_cost_usd"] == 0


def test_transcription_cannot_reach_provider_when_budget_cannot_cover_it(tmp_path, monkeypatch):
    audio = tmp_path / "scene.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(ep, "_audio_dur", lambda _path: 30.0)
    monkeypatch.setattr(ep, "_openai", lambda: SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(
            create=lambda **kwargs: pytest.fail("provider must not be called")))))
    store, blob = MemoryStore(cap=0), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "no-budget-worker")

    with activate(worker), pytest.raises(ep.TranscriptionUnavailable) as caught:
        ep.transcribe_words(str(audio), strict=True)

    assert isinstance(caught.value.__cause__, BudgetExceeded)
    assert store.stages == {}


def test_claim_repair_changes_only_failed_scene_and_reuses_existing_claim(monkeypatch):
    narration = "Farmers definitely raised rats for the bounty."
    script, dossier = _script(
        narration, phrase=narration, confidence="speculative",
        claim_text="Some accounts suggest farmers might have raised rats for the bounty.",
        quote="Some accounts suggest farmers might have raised rats for the bounty.",
    )
    report = validate_claim_joins(script, dossier)
    fixed = "Some accounts suggest farmers might have raised rats for the bounty."
    seen = {}

    class Messages:
        def create(self, **kwargs):
            seen["prompt"] = kwargs["messages"][0]["content"]
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps({"scenes": [{
                    "scene": 1, "narration": fixed, "evidence_id": "e01",
                    "claim_refs": [{"claim_id": "c01", "evidence_id": "e01",
                                    "narration_phrase": fixed}],
                }]}))],
                usage=SimpleNamespace(input_tokens=100, output_tokens=100),
            )

    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=Messages()))
    repaired, cost = ep.repair_claim_join_failures(
        script, dossier, report, operator_direction="Distinguish anecdote from history.")

    assert cost > 0
    assert repaired["scenes"][0]["narration"] == fixed
    assert validate_claim_joins(repaired, dossier)["passed"] is True
    assert "Distinguish anecdote from history" in seen["prompt"]


def test_durable_retry_does_not_repeat_an_ambiguous_provider_dispatch(tmp_path, monkeypatch):
    class Transient(Exception):
        pass

    calls = []
    monkeypatch.setattr(ep, "_RETRYABLE", (Transient,))
    monkeypatch.setattr(ep.time, "sleep", lambda _seconds: None)
    store, blob = MemoryStore(cap=1), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "ambiguous-worker")

    def operation():
        calls.append(True)
        raise Transient("connection ended after dispatch")

    with activate(worker), pytest.raises(AmbiguousProviderOutcome):
        ep._retry(operation, tries=4, base_delay=0, label="paid generation")

    assert len(calls) == 1
