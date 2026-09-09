import copy
import io
import json
import tarfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import anyio
import httpx
import pytest

import agent_actions
import app as studio
import durable_execution as durable
from longform_research import is_legacy_scope_label_failure, scope_label_dossier_repaired
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
from test_durable_execution_phase6 import MemoryBlob
from test_longform_research_phase2 import _dossier


ERROR = ("Research dossier failed before scripting [9 quotable excerpts available; "
         "scope_inflationx1]: A local or regional source is stated as a global claim.")
RECOVERY = "scope_label_recovery_v1"
CHECKPOINT_SHA = "a" * 64
ECOSYSTEM_ERROR = ("STORY_SPINE_UNSUPPORTED\nwho was eating whom before anyone intervened\n"
                   "[CLAIM_KIND_MISMATCH] beat event_01 is a setup beat citing c01, "
                   "which is a mechanism claim; a setup beat may cite event, context, outcome")
INTRODUCTION_ERROR = ("STORY_SPINE_UNSUPPORTED\nwho was eating whom before anyone intervened\n"
                      "the species deliberately removed or introduced\n"
                      "[ROLE_CONTRACT_FAILED] event_01 no longer performs setup")


def dossier():
    data = _dossier(claim="COMPARABLE CASE (worldwide): A regional gauge rose two meters.")
    data["validation"] = {"passed": False, "errors": [
        {"code": "scope_inflation", "claim_id": "c01"}]}
    return data


def test_recovery_revalidates_evidence_without_rewriting_failed_report():
    saved = dossier()
    original = copy.deepcopy(saved)
    assert is_legacy_scope_label_failure(ERROR)
    assert scope_label_dossier_repaired(saved)
    assert saved == original
    saved["claims"][0]["claim"] += " This happens worldwide."
    assert not scope_label_dossier_repaired(saved)
    saved = dossier()
    saved["claims"][0]["support_quote"] = "An invented quotation."
    assert not scope_label_dossier_repaired(saved)
    saved = dossier()
    saved["validation"]["errors"].append({"code": "unverified_source"})
    assert not scope_label_dossier_repaired(saved)
    assert not is_legacy_scope_label_failure(ERROR.replace("scope_inflationx1", "scope_inflationx2"))
    assert not is_legacy_scope_label_failure("Claim ledger failed after scripting: " + ERROR)


@pytest.mark.parametrize("valid,available", [(True, True), (False, True), (True, False)])
def test_checkpoint_review_reads_preserved_archive(tmp_path, valid, available):
    blob = MemoryBlob(tmp_path / "blob")
    saved = dossier()
    if not valid:
        saved["claims"][0]["claim"] += " It happens everywhere."
    encoded = json.dumps(saved).encode()
    archive = tmp_path / "checkpoint.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("research_dossier.json")
        member.size = len(encoded)
        tar.addfile(member, io.BytesIO(encoded))
    checkpoint = blob.upload(str(archive), "checkpoint.tar.gz") if available else {}
    job = {"id": "same-job", "checkpoint": checkpoint}
    assert studio._scope_label_checkpoint_repaired(job, object(), blob) is (valid and available)
    assert archive.exists()


@pytest.mark.parametrize("recovery_type", ["scope", "ecosystem", "introduction"])
@pytest.mark.parametrize("authorized,repaired,used,operation", [
    (True, True, False, "generic_illustrated"),
    (False, True, False, "generic_illustrated"),
    (True, False, False, "generic_illustrated"),
    (True, True, True, "generic_illustrated"),
    (True, True, False, "directed_pilot"),
])
def test_dispatch_continues_only_corrected_bound_job(monkeypatch, authorized, repaired, used, operation,
                                                   recovery_type):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    now = datetime.now(timezone.utc)
    repository.action = {
        "action_id": ACTION_ID, "operation": operation, "status": "queued",
        "job_id": "same-job", "approved_at": now - timedelta(hours=1),
        "expires_at": now - timedelta(minutes=1), "spec_sha256": "f" * 64,
        "cost_ceiling_usd": 5, "claim_token_sha256": agent_actions.token_digest(ACTION_ID),
    }
    recovery = {"scope": RECOVERY, "ecosystem": "evidence_coverage_recovery_v1",
                "introduction": "introduction_contract_recovery_v1"}[recovery_type]
    error = {"scope": ERROR, "ecosystem": ECOSYSTEM_ERROR,
             "introduction": INTRODUCTION_ERROR}[recovery_type]
    job = {"id": "same-job", "status": "error", "error": error,
           "spent_cost_usd": 0.9083, "max_cost_usd": 5,
           "checkpoint": {"sha256": CHECKPOINT_SHA},
           "result": {recovery: {"checkpoint_sha256": CHECKPOINT_SHA}} if used else {}}
    store = Mock()
    store.get_job.return_value = job
    monkeypatch.setattr(agent_actions, "repository", lambda: repository)
    monkeypatch.setattr(studio, "_durable_components", lambda: (store, object()))
    check = Mock(return_value=repaired)
    helper = {"scope": "_scope_label_checkpoint_repaired",
              "ecosystem": "_ecosystem_checkpoint_repairable",
              "introduction": "_introduction_checkpoint_repairable"}[recovery_type]
    monkeypatch.setattr(studio, helper, check)
    workers = []

    async def worker(job_id):
        workers.append(job_id)
        return {"claimed": store.rearm_infrastructure_failure.called}

    monkeypatch.setattr(studio, "_run_durable_explainer_worker", worker)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url="http://test") as client:
            response = await client.post(f"/api/agent/actions/{ACTION_ID}/dispatch",
                headers={"Authorization": f"Bearer {ACTION_ID if authorized else 'wrong'}"})
            assert response.status_code == (200 if authorized else 403)

    anyio.run(run)
    if authorized and repaired and not used and operation == "generic_illustrated":
        store.rearm_infrastructure_failure.assert_called_once_with(
            "same-job", error_fragment="scope_inflationx1" if recovery_type == "scope"
            else "STORY_SPINE_UNSUPPORTED", extra_attempts=1,
            recovery_key=recovery, expected_checkpoint_sha256=CHECKPOINT_SHA)
    else:
        store.rearm_infrastructure_failure.assert_not_called()
    assert workers == (["same-job"] if authorized else [])
    assert job["spent_cost_usd"] == 0.9083 and job["max_cost_usd"] == 5


@pytest.mark.parametrize("change", [
    {"status": "processing"}, {"reserved_cost_usd": 0.1}, {"spent_cost_usd": 5},
    {"checkpoint": {"sha256": "b" * 64}}, {"result": {RECOVERY: {"done": True}}},
    {"error": "A different failure"}, {},
])
def test_atomic_rearm_preserves_budget_and_rejects_stale_or_repeated_recovery(change):
    row = {"id": "same-job", "status": "error", "error": ERROR,
           "reserved_cost_usd": 0, "spent_cost_usd": 0.9083, "max_cost_usd": 5,
           "checkpoint": {"sha256": CHECKPOINT_SHA}, "result": {}, **change}
    cursor = Mock()
    cursor.fetchone.side_effect = [row, {**row, "status": "queued"}]

    class Store(durable.PostgresStore):
        def __init__(self):
            self.append_event = Mock()

        @contextmanager
        def _tx(self):
            yield None, cursor

        @staticmethod
        def _row(cur, value):
            return value

    store = Store()
    kwargs = dict(error_fragment="scope_inflationx1", extra_attempts=1,
                  recovery_key=RECOVERY, expected_checkpoint_sha256=CHECKPOINT_SHA)
    if change:
        with pytest.raises(durable.DurableExecutionError):
            store.rearm_infrastructure_failure("same-job", **kwargs)
        assert not any(call.args[0].lstrip().startswith("UPDATE ")
                       for call in cursor.execute.call_args_list)
    else:
        assert store.rearm_infrastructure_failure("same-job", **kwargs)["status"] == "queued"
        updates = [call.args for call in cursor.execute.call_args_list
                   if call.args[0].lstrip().startswith("UPDATE ")]
        assert len(updates) == 1
        sql, params = updates[0]
        assert "result=result ||" in sql
        assert json.loads(params[1])[RECOVERY]["checkpoint_sha256"] == CHECKPOINT_SHA
        assert "spent_cost_usd=" not in sql and "request=" not in sql and "max_cost_usd=" not in sql
