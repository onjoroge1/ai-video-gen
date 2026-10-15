"""The 45-second readiness grade has a file of its own (2026-10-14).

The gate and the final pass both wrote retention_readiness.json, so the final pass erased the
opening grade: every job folder held only the whole-film score, and the opening's had to be
recomputed from the inspection frames to be seen at all.
"""
import inspect
import json

import explainer_pipeline as ep
from retention_readiness import score_retention_readiness, write_readiness_report


def _report(sync):
    return score_retention_readiness(
        {"title": "t", "hook": "h"}, {"checks": {}},
        {"avg_still_seconds": 2.0, "min_shot_seconds": 1.6, "narration_aligned_cut_ratio": sync,
         "meaningful_cut_ratio": 1.0, "motion_sync_ratio": 1.0, "max_still_seconds": 3.0},
        [], preview={"decodable": True, "duration_sec": 48.0})


def test_the_final_pass_cannot_overwrite_the_opening_report(tmp_path):
    opening, final = _report(0.6), _report(1.0)
    assert opening["score"] != final["score"]
    write_readiness_report(opening, str(tmp_path))
    text_path, json_path = write_readiness_report(opening, str(tmp_path),
                                                  stem="retention_readiness_open45")
    assert json_path.endswith("retention_readiness_open45.json")
    assert text_path.endswith("retention_readiness_open45.txt")
    write_readiness_report(final, str(tmp_path))
    assert json.loads((tmp_path / "retention_readiness_open45.json").read_text())["score"] \
        == opening["score"]
    assert json.loads((tmp_path / "retention_readiness.json").read_text())["score"] \
        == final["score"]


def test_the_gate_writes_the_open45_report_and_keeps_the_old_one():
    source = inspect.getsource(ep.run_explainer_pipeline)
    gate = source.index("45-second Retention Readiness:")
    open45 = source.index('stem="retention_readiness_open45"')
    assert source.rindex("write_readiness_report(readiness, output_dir)", 0, gate) < open45 < gate
