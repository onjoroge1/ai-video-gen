"""List films (2026-10-17): the spec's structure, picture matching by shared claims, shot lengths
under the rendered gate's ceiling, chapters and captions. No network, no ffmpeg.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import list_film as lf  # noqa: E402


def _entry(rank, job="jobs/x"):
    return {"rank": rank, "label": f"E{rank}", "job": job,
            "beats": [{"text": "A fact.", "claims": ["c01"]}, {"text": "Why?", "rhetorical": True},
                      {"text": "Another fact.", "claims": ["c02"]}]}


def _spec(**over):
    spec = {"slug": "s", "title": "Why?", "question": "Why?", "entries": [_entry(3), _entry(2), _entry(1)],
            "intro": [{"text": "You'd think so.", "rhetorical": True}], "outro": []}
    spec.update(over)
    return spec


def test_a_valid_countdown_passes():
    assert lf.validate_spec(_spec()) == []


def test_structure_errors_stop_the_build():
    assert any("count down" in e for e in lf.validate_spec(_spec(entries=[_entry(1), _entry(2), _entry(3)])))
    assert any("3-7 entries" in e for e in lf.validate_spec(_spec(entries=[_entry(2), _entry(1)])))
    bad = _spec()
    bad["entries"][0]["beats"][0] = {"text": "An unsourced fact."}
    assert any("cites claims, or is marked rhetorical" in e for e in lf.validate_spec(bad))
    bad = _spec(intro=[{"text": "A fact.", "claims": ["c01"]}])
    assert any("need the entry job" in e for e in lf.validate_spec(bad))


def test_entry_beats_inherit_the_entry_job():
    beats = dict(lf.iter_beats(_spec()))
    assert beats["#3[0]"]["job"] == "jobs/x" and "job" not in beats["intro[0]"]


def _job(tmp_path):
    job = tmp_path / "job"
    (job / "images").mkdir(parents=True)
    for name in ("scene_00.jpg", "scene_01.jpg", "scene_01_e02.jpg", "scene_02.jpg", "scene_01.jpg.verdict.json"):
        (job / "images" / name).write_bytes(b"x")
    script = {"scenes": [{"claim_refs": [{"claim_id": "c01"}]},
                         {"claim_refs": [{"claim_id": "c02"}, {"claim_id": "c03"}]},
                         {"claim_refs": [{"claim_id": "c03"}]}],
              "_research_dossier": {"claims": [{"claim_id": "c02", "claim": "Two.", "support_quote": "two"}]}}
    (job / "_state.json").write_text(json.dumps({"script": script}))
    return str(job), script


def test_pictures_come_from_the_scenes_that_cited_the_claims(tmp_path):
    job, script = _job(tmp_path)
    used = set()
    first = lf.pick_pictures(job, script, ["c02", "c03"], used, want=2)
    assert [os.path.basename(p) for p in first] == ["scene_01.jpg", "scene_01_e02.jpg"]
    again = lf.pick_pictures(job, script, ["c03"], used, want=1)
    assert [os.path.basename(p) for p in again] == ["scene_02.jpg"], "unused pictures first"


def test_claim_ceiling_carries_the_verified_quote(tmp_path):
    job, script = _job(tmp_path)
    assert lf.claim_ceiling(script, ["c02"]) == 'Two. (source: "two")'
    try:
        lf.claim_ceiling(script, ["c99"])
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown claim must stop the build")


def test_no_shot_outlasts_the_ceiling():
    shots = lf.split_shots(10.0, 18.0, ["a.jpg", "b.jpg"])
    assert all(s["end"] - s["start"] <= lf.MAX_SHOT_SEC + 1e-6 for s in shots)
    assert shots[0]["start"] == 10.0 and shots[-1]["end"] == 18.0
    assert [s["image"] for s in shots[:2]] == ["a.jpg", "b.jpg"] and shots[2]["variant"] == 1


def test_chapters_start_at_zero_and_stay_ten_seconds_apart():
    assert lf.chapters([("#4 Hippos", 31.0), ("#3 Carp", 35.0), ("#2 Toads", 95.5)]) == [
        "0:00 The question", "0:31 #4 Hippos", "1:35 #2 Toads"]


def test_captions_are_valid_srt():
    out = lf.srt([{"start": 0.0, "end": 2.5, "text": "One."}, {"start": 61.2, "end": 63.0, "text": "Two."}])
    assert out.startswith("1\n00:00:00,000 --> 00:00:02,500\nOne.\n")
    assert "00:01:01,200 --> 00:01:03,000" in out


def test_chapter_labels_keep_apostrophes():
    assert lf.chapter_label("Escobar's hippos") == "Escobar's Hippos"
