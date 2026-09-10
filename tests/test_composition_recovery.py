"""Recovery reads the saved research and gap JSON before granting one bounded attempt."""
import io
import json
import tarfile

import pytest

import app as studio
import research_coverage as coverage
from test_durable_execution_phase6 import MemoryBlob
from test_evidence_coverage import Judge, fixture, prepare
from test_scope_label_recovery import PROVENANCE_ERROR


@pytest.mark.parametrize("change", ["none", "wrong_gaps", "missing_failure", "v3_started", "unverified"])
def test_composition_recovery_reconciles_exact_saved_json(tmp_path, change):
    beats, data = fixture()
    report = prepare(beats, data, Judge())
    data["claims"][0].update(quote_verified=True, source_reachable=True)
    gaps = coverage.evidence_gaps(report, beats)
    files = {"research_dossier.json": data,
             "evidence_coverage_v2.json": {"status": "started", "identity": {"gaps": gaps}},
             "semantic_failure_story-spine.json": {"script": {"beats": beats}, "report": report}}
    if change == "wrong_gaps":
        files["evidence_coverage_v2.json"]["identity"]["gaps"] = []
    elif change == "missing_failure":
        del files["semantic_failure_story-spine.json"]
    elif change == "v3_started":
        files[f"{coverage.REPAIR_VERSION}.json"] = {"status": "started"}
    elif change == "unverified":
        data["claims"][0]["source_reachable"] = False
    archive = tmp_path / "checkpoint.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in files.items():
            raw = json.dumps(payload).encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            tar.addfile(entry, io.BytesIO(raw))
    blob = MemoryBlob(tmp_path / "blob")
    checkpoint = blob.upload(str(archive), "checkpoint.tar.gz")
    job = {"id": "job", "checkpoint": checkpoint, "error": PROVENANCE_ERROR}
    assert studio._composed_evidence_checkpoint_repairable(job, object(), blob) is (change == "none")
