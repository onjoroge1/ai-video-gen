"""Failed focused research remains inspectable without spending or making it public."""
import json

import anyio
import httpx
import pytest

import app as studio
import private_access


@pytest.mark.parametrize("present", [True, False])
def test_supplement_download_restores_failed_checkpoint_privately(tmp_path, monkeypatch, present):
    monkeypatch.setenv("APP_PASSWORD", "test-studio-secret")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_SESSION_SECRET", "test-session-secret")
    monkeypatch.setattr(studio, "explainer_jobs", {})
    monkeypatch.setattr(studio, "_durable_execution_required", lambda: True)
    restored = []
    supplement = {"claims": [{"claim_id": "unverified", "source_url": "https://example.edu/source"}],
                  "claim_verification": {"fetched": 0, "urls": 1},
                  "validation": {"passed": False}}
    row = {"id": "failed-job", "status": "error", "spent_cost_usd": 2.21,
           "checkpoint": {"sha256": "a" * 64}, "request": {}, "result": {}}

    class Store:
        def get_job(self, job_id):
            assert job_id == row["id"]
            return row

        def finished_get(self, job_id):
            return None

    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs["worker_id"] == "read-only"
            self.output_dir = kwargs["output_dir"]

        def restore_checkpoint(self, checkpoint):
            from pathlib import Path
            restored.append(checkpoint)
            root = Path(self.output_dir)
            # The original dossier must never be mistaken for the failed supplement.
            (root / "research_dossier.json").write_text('{"original": true}')
            if present:
                (root / "research_supplement.json").write_text(json.dumps(supplement))

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(studio.durable_execution, "DurableRuntime", Runtime)

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            path = "/api/explainer/research-supplement/failed-job"
            assert (await client.get(path)).status_code == 401
            assert not restored
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session("admin"))
            response = await client.get(path)
            assert response.status_code == (200 if present else 404)
            if present:
                assert response.json() == supplement
                assert "attachment" in response.headers["content-disposition"]
            assert row["status"] == "error"
            assert row["spent_cost_usd"] == 2.21
            assert restored == [row["checkpoint"]]

    try:
        anyio.run(run)
    finally:
        import shutil
        for job in studio.explainer_jobs.values():
            shutil.rmtree(job.get("_materialized_dir", ""), ignore_errors=True)
