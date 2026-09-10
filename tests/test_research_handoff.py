"""Saved handoff decisions are usable by a new worker and readable without spending."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import anyio
import httpx
import pytest

import app as studio
import cost_ledger
import private_access
import research_handoff as handoff
import story_planning
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_story_planning_flow import factual_fixture, EvidenceFixture


def test_ready_handoff_restores_without_rejudging_and_invalidates_changed_evidence(tmp_path, monkeypatch):
    beats, claims = factual_fixture()
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "first")
    monkeypatch.setattr(handoff, "_location", lambda: (Path(first.output_dir) / handoff.FILENAME, first))
    judge = EvidenceFixture()
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=judge)
    saved = json.loads((Path(first.output_dir) / handoff.FILENAME).read_text())
    assert saved["status"] == "ready"
    assert saved["rows"][0]["claim_ids"] == ["c1"]
    assert saved["rows"][0]["evidence"][0]["support_quote"] == claims["c1"]["support_quote"]
    second = runtime(tmp_path, store, blob, "second")
    second.restore_checkpoint(store.job["checkpoint"])
    monkeypatch.setattr(handoff, "_location", lambda: (Path(second.output_dir) / handoff.FILENAME, second))
    unavailable = Mock(side_effect=AssertionError("Saved handoff must not call a provider"))
    ledger, cache = cost_ledger.CostLedger(), {}
    replay = story_planning.prepare(beats, "backfiring_solution", claims,
                                   judge=unavailable, cost_sink=ledger, cache=cache)
    assert replay["compiled"] == result["compiled"] and unavailable.call_count == 0
    assert cache == result["cache"] and ledger.total() == pytest.approx(result["cost_usd"])
    changed = deepcopy(claims)
    changed["c1"]["support_quote"] = "A different quotation"
    assert handoff.load(handoff.identity(beats, "backfiring_solution", changed, None, "", False)) is None


def test_blocked_handoff_remains_blocked_and_unavailable_is_not_a_decision(tmp_path, monkeypatch):
    beats, claims = factual_fixture()
    monkeypatch.setattr(handoff, "_location", lambda: (tmp_path / handoff.FILENAME, Mock()))
    reject = EvidenceFixture(reject_relationship="material property")
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=reject)
    assert not result["compiled"]["passed"]
    saved_rows = json.loads((tmp_path / handoff.FILENAME).read_text())["rows"]
    blocked_ids = {r["beat_id"] for r in result["compiled"]["relationships"] if not r["passed"]}
    assert blocked_ids and all(r["status"] == "blocked" for r in saved_rows if r["beat_id"] in blocked_ids)
    replay = story_planning.prepare(beats, "backfiring_solution", claims,
                                   judge=Mock(side_effect=AssertionError("Decided rejection")))
    assert not replay["compiled"]["passed"]
    key = handoff.identity(beats, "backfiring_solution", claims, None, "", False)
    snapshot = handoff.load(key)
    snapshot["prepared"]["compiled"]["cascade"]["unavailable"] = [{"verdict": "unavailable"}]
    handoff.save(snapshot)
    assert handoff.load(key) is None


def test_reader_uses_current_checkpoint_after_a_job_resumes(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "writer")
    root = Path(worker.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(studio, "_durable_components", lambda: (store, blob))
    store.get_job = Mock(return_value=store.job)
    for status in ("blocked", "ready"):
        (root / handoff.FILENAME).write_text(json.dumps({"status": status, "rows": []}))
        worker.checkpoint("saved-story")
        assert studio._research_handoff_payload("job-1")["status"] == status
    assert store.job["spent_cost_usd"] == 0 and not store.stages


@pytest.mark.parametrize("saved_handoff", [True, False])
def test_private_table_and_json_inspect_same_snapshot_without_mutating_job(tmp_path, monkeypatch, saved_handoff):
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: False)
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_SESSION_SECRET", "test-session")
    beats, claims = factual_fixture()
    claims["c1"]["support_quote"] = "<script>alert('untrusted source')</script>"
    dossier = {"topic": "Saved topic", "claims": list(claims.values())}
    result = {"beats": beats, "compiled": {"passed": False, "engine_id": "backfiring_solution"}}
    record = handoff.record(handoff.identity(beats, "backfiring_solution", claims, {}, "Saved topic", False),
                            beats, claims, result)
    payloads = {"research": dossier,
                "spine-failure": {"script": {"beats": beats}, "research_dossier": dossier,
                                  "report": result["compiled"]},
                "research-supplement": {"claims": [dict(claims["c1"], quote_verified=False,
                                                        source_reachable=False)]}}
    if saved_handoff:
        payloads["research-handoff"] = record
    for kind, payload in payloads.items():
        (tmp_path / (kind + ".json")).write_text(json.dumps(payload))
    read = Mock(side_effect=lambda job, kind:
                (str(tmp_path / (kind + ".json")), "topic") if kind in payloads else (None, None))
    monkeypatch.setattr(studio, "_explainer_text_artifact", read)
    original = deepcopy(payloads)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url="http://test") as client:
            assert (await client.get("/api/explainer/research-handoff/job")).status_code == 401
            assert (await client.get("/agent/research/job", headers={"Accept": "text/html"})).status_code == 303
            assert read.call_count == 0
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session("admin"))
            response = await client.get("/api/explainer/research-handoff/job")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == ("blocked" if saved_handoff else "legacy_failure")
            assert data["research_supplement"]["claims"][0]["quote_verified"] is False
            page = await client.get("/agent/research/job")
            assert page.status_code == 200 and "<table>" in page.text
            assert "&lt;script&gt;" in page.text and "<script>alert" not in page.text
            assert "Focused research" in page.text and "Quote verified: False" in page.text
    anyio.run(check)
    for kind, payload in original.items():
        assert json.loads((tmp_path / (kind + ".json")).read_text()) == payload
