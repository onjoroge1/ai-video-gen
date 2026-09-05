import json
import os
from pathlib import Path
import shutil
import concurrent.futures

import pytest

from durable_execution import (
    BudgetExceeded, DurableRuntime, LeaseLost, activate, canonical_hash, cleanup_orphans, current,
    enforce_budget,
)


class MemoryStore:
    def __init__(self, cap=2.0):
        self.job = {
            "id": "job-1", "max_cost_usd": cap, "spent_cost_usd": 0.0,
            "reserved_cost_usd": 0.0, "checkpoint": {}, "status": "processing",
        }
        self.stages = {}
        self.events_seen = []
        self.artifacts_seen = []

    def prepare_stage(self, job_id, key, provider, request_hash, estimate):
        if key in self.stages:
            stage = self.stages[key]
            assert stage["request_hash"] == request_hash
            return dict(stage)
        if self.job["spent_cost_usd"] + self.job["reserved_cost_usd"] + estimate > self.job["max_cost_usd"]:
            raise BudgetExceeded("cap")
        stage = {
            "job_id": job_id, "stage_key": key, "provider": provider,
            "request_hash": request_hash,
            "idempotency_key": canonical_hash([job_id, key, request_hash]),
            "status": "running", "reserved_cost_usd": estimate,
            "actual_cost_usd": 0.0, "result": {}, "artifact": {},
        }
        self.stages[key] = stage
        self.job["reserved_cost_usd"] += estimate
        return dict(stage)

    def complete_stage(self, job_id, key, *, actual_cost, result, artifact):
        return self._settle_stage(key, actual_cost, result, artifact, "completed")

    def incomplete_stage(self, job_id, key, *, actual_cost, result):
        return self._settle_stage(key, actual_cost, result, {}, "incomplete")

    def _settle_stage(self, key, actual_cost, result, artifact, status):
        stage = self.stages[key]
        if stage["status"] not in {"completed", "incomplete"}:
            self.job["reserved_cost_usd"] -= stage["reserved_cost_usd"]
            self.job["spent_cost_usd"] += actual_cost
            stage.update(status=status, actual_cost_usd=actual_cost,
                         result=result, artifact=artifact)
        elif status == "incomplete":
            stage["status"] = "incomplete"
        return dict(stage)

    def fail_stage(self, job_id, key, error, *, retryable=True):
        if self.stages[key]["status"] in {"completed", "incomplete"}:
            return
        self.stages[key]["status"] = "retry" if retryable else "failed"
        self.stages[key]["error"] = error

    def register_artifact(self, job_id, kind, stage_key, artifact, *, provisional=True):
        self.artifacts_seen.append((job_id, kind, stage_key, artifact, provisional))

    def append_event(self, job_id, event_type, data, details=None):
        self.events_seen.append((event_type, data, details or {}))

    def heartbeat(self, job_id, worker_id):
        return None

    def update_checkpoint(self, job_id, checkpoint):
        self.job["checkpoint"] = checkpoint

    def note_stage(self, job_id, key, patch):
        self.stages[key]["result"].update(patch)


class MemoryBlob:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def upload(self, local_path, remote_path):
        self.counter += 1
        target = self.root / f"{self.counter}-{Path(remote_path).name}"
        shutil.copy(local_path, target)
        from durable_execution import file_sha256
        return {
            "url": str(target), "download_url": str(target), "pathname": remote_path,
            "sha256": file_sha256(target), "size_bytes": target.stat().st_size,
            "content_type": "application/octet-stream",
        }

    def download(self, artifact, local_path):
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(artifact["url"], local_path)
        from durable_execution import file_sha256
        assert file_sha256(local_path) == artifact["sha256"]
        return local_path

    def delete(self, url):
        Path(url).unlink(missing_ok=True)


def runtime(tmp_path, store, blob, worker):
    out = tmp_path / worker
    out.mkdir()
    return DurableRuntime("job-1", worker, str(out), store, blob)


def test_completed_paid_stage_restores_on_another_worker_without_repurchase(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "worker-a")
    output_a = Path(first.output_dir) / "scene.jpg"
    calls = []

    def purchase(idempotency_key):
        calls.append(idempotency_key)
        output_a.write_bytes(b"paid-image")
        return {"provider_id": "p-1"}, 0.05

    first.paid_file(stage_key="image:scene-1", provider="openai", request={"prompt": "x"},
                    estimated_cost=0.06, output_path=str(output_a), operation=purchase)
    second = runtime(tmp_path, store, blob, "worker-b")
    output_b = Path(second.output_dir) / "scene.jpg"
    second.paid_file(
        stage_key="image:scene-1", provider="openai", request={"prompt": "x"},
        estimated_cost=0.06, output_path=str(output_b),
        operation=lambda _key: (_ for _ in ()).throw(AssertionError("repurchased")))
    assert calls and len(calls) == 1
    assert output_b.read_bytes() == b"paid-image"
    assert store.job["spent_cost_usd"] == pytest.approx(0.05)


def test_crash_window_keeps_one_reservation_and_one_documented_inflight_retry(tmp_path):
    store, blob = MemoryStore(cap=1.0), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "worker-a")
    out_a = Path(first.output_dir) / "clip.mp4"
    calls = []

    def dies_after_provider_accepts(key):
        calls.append(key)
        out_a.write_bytes(b"provider-finished-but-worker-died")
        raise ConnectionError("worker terminated before commit")

    with pytest.raises(ConnectionError):
        first.paid_file(stage_key="motion:opening", provider="fal", request={"seconds": 5},
                        estimated_cost=0.4, output_path=str(out_a),
                        operation=dies_after_provider_accepts)
    assert store.job["reserved_cost_usd"] == pytest.approx(0.4)

    second = runtime(tmp_path, store, blob, "worker-b")
    out_b = Path(second.output_dir) / "clip.mp4"

    def retry_same_stage(key):
        calls.append(key)
        out_b.write_bytes(b"recovered")
        return {"provider_request_id": "same-stage"}, 0.4

    second.paid_file(stage_key="motion:opening", provider="fal", request={"seconds": 5},
                     estimated_cost=0.4, output_path=str(out_b), operation=retry_same_stage)
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert store.job["spent_cost_usd"] == pytest.approx(0.4)
    assert store.job["reserved_cost_usd"] == pytest.approx(0.0)
    # Worst case is the committed cap plus exactly the one call accepted before the crash.
    assert store.job["spent_cost_usd"] + 0.4 <= store.job["max_cost_usd"] + 0.4


def test_budget_is_reserved_before_provider_operation(tmp_path):
    store, blob = MemoryStore(cap=0.10), MemoryBlob(tmp_path / "blob")
    rt = runtime(tmp_path, store, blob, "worker-a")
    called = False

    def operation(_key):
        nonlocal called
        called = True
        return {}, 0.2

    with pytest.raises(BudgetExceeded):
        rt.paid_file(stage_key="image:too-expensive", provider="openai", request={},
                     estimated_cost=0.20, output_path=str(Path(rt.output_dir) / "x.jpg"),
                     operation=operation)
    assert not called


def test_one_ambiguous_provider_call_is_bounded_separately_from_job_cap():
    job = {"spent_cost_usd": 1.0, "reserved_cost_usd": 0.5,
           "max_cost_usd": 5.0, "max_inflight_call_usd": 0.75}
    enforce_budget(job, 0.75, "motion:allowed")
    with pytest.raises(BudgetExceeded, match="single-call ceiling"):
        enforce_budget(job, 0.76, "motion:too-large")


def test_checkpoint_round_trip_restores_state_and_review_on_different_worker(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    first = runtime(tmp_path, store, blob, "worker-a")
    Path(first.output_dir, "_state.json").write_text(json.dumps({"script": {"title": "Mystery"}}))
    Path(first.output_dir, "human_review.json").write_text(json.dumps({"decision": "approve"}))
    paid_dir = Path(first.output_dir, "images")
    paid_dir.mkdir()
    Path(paid_dir, "scene.jpg").write_bytes(b"already stored as a paid stage")
    Path(first.output_dir, "first_minute_preview.mp4").write_bytes(b"review preview")
    checkpoint = first.checkpoint("human-review")

    second = runtime(tmp_path, store, blob, "worker-b")
    second.restore_checkpoint(checkpoint)
    assert json.loads(Path(second.output_dir, "_state.json").read_text())["script"]["title"] == "Mystery"
    assert json.loads(Path(second.output_dir, "human_review.json").read_text())["decision"] == "approve"
    assert Path(second.output_dir, "first_minute_preview.mp4").read_bytes() == b"review preview"
    assert not Path(second.output_dir, "images", "scene.jpg").exists()


def test_pipeline_thread_map_keeps_durable_runtime_visible(tmp_path):
    from explainer_pipeline import _context_map

    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    active = runtime(tmp_path, store, blob, "worker-a")
    with activate(active):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            seen = list(_context_map(executor, lambda item: (item, current()), [1, 2, 3]))
    assert [item for item, _ in seen] == [1, 2, 3]
    assert all(bound is active for _, bound in seen)


def test_heartbeat_failure_blocks_the_next_paid_call(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    active = runtime(tmp_path, store, blob, "worker-a")
    active._lease_error = RuntimeError("database unavailable")
    with pytest.raises(LeaseLost):
        active.paid_value(
            stage_key="script", provider="anthropic", request={}, estimated_cost=0.01,
            operation=lambda _key: ({"ok": True}, 0.01),
        )


def test_cleanup_removes_registered_and_untracked_orphans_without_touching_known(tmp_path):
    class CleanupStore:
        def __init__(self):
            self.removed = []

        def stale_provisional(self, **_kwargs):
            return [{"job_id": "dead", "kind": "stage", "stage_key": "x",
                     "url": "registered-orphan"}]

        def delete_artifact_record(self, job_id, kind, stage_key):
            self.removed.append((job_id, kind, stage_key))

        def known_pathnames(self, _pathnames):
            return {"jobs/known.bin"}

    class CleanupBlob:
        def __init__(self):
            self.deleted = []

        def delete(self, url):
            self.deleted.append(url)

        def older_objects(self, prefix, **_kwargs):
            if prefix == "jobs/":
                return [
                    {"pathname": "jobs/known.bin", "url": "known"},
                    {"pathname": "jobs/lost.bin", "url": "untracked"},
                ]
            return []

    store, blob = CleanupStore(), CleanupBlob()
    report = cleanup_orphans(store, blob)
    assert report == {"deleted": 1, "untracked_deleted": 1, "errors": [], "passed": True}
    assert blob.deleted == ["registered-orphan", "untracked"]
    assert store.removed == [("dead", "stage", "x")]


def test_phase6_routes_and_fail_closed_library_contract_are_wired():
    app_source = Path("app.py").read_text()
    finished_source = Path("finished_api.py").read_text()
    ui_source = Path("static/index.html").read_text()
    vercel = json.loads(Path("vercel.json").read_text())
    assert "/api/explainer/dispatch/{job_id}" in app_source
    assert "/api/internal/render-worker" in app_source
    assert "/api/cron/render-recovery" in app_source
    assert "FINISHED_STORAGE_UNAVAILABLE" in finished_source
    assert "dispatch_url" in ui_source
    assert vercel["crons"][0]["schedule"] == "* * * * *"
    assert vercel["functions"]["app.py"]["maxDuration"] == 800
