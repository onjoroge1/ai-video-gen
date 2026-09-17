"""The illustrated lane must be a first-class row in Finished Videos, like the quiz lane.

Before this, every illustrated render was archived with ``format="explainer"``. The library's
only lane label is that string, so an illustrated story was indistinguishable from a cinematic
explainer: no filter, no badge, and a search for "illustrated" returned nothing. Quizzes have
always had ``short-quiz``. These tests pin the same treatment for the illustrated lane, plus the
lane facts the library needs to describe a render without opening the MP4.
"""
import json
from pathlib import Path

import anyio
import httpx
from fastapi import FastAPI

import app as studio
import finished_api


def _fmt(**overrides) -> str:
    """Call the production function. Never reimplement it here — a copied ternary tests the copy."""
    kwargs = dict(visual_style="cinematic", video_format="landscape",
                  short_template="explainer", directed_spec=False, directed_full_film=False)
    kwargs.update(overrides)
    return studio.finished_library_format(**kwargs)


def test_illustrated_render_gets_its_own_library_format():
    assert _fmt(visual_style="illustrated_story") == studio.ILLUSTRATED_FINISHED_FORMAT
    assert studio.ILLUSTRATED_FINISHED_FORMAT == "illustrated-story"
    # Neighbouring lanes are untouched, including the branch-order that decides them.
    assert _fmt() == "explainer"
    assert _fmt(video_format="social", short_template="quiz") == "short-quiz"
    assert _fmt(directed_spec=True) == "directed-v1-pilot"
    assert _fmt(directed_spec=True, directed_full_film=True) == "directed-v1-full"
    # Branch precedence, not just the happy path: a directed or social render stays in its own
    # lane even when the request also carries the illustrated visual style.
    assert _fmt(visual_style="illustrated_story", directed_spec=True) == "directed-v1-pilot"
    assert _fmt(visual_style="illustrated_story", video_format="social",
                short_template="quiz") == "short-quiz"


def test_the_archiver_uses_that_function_and_not_a_local_copy():
    """Pin the wiring, so reordering the branches cannot pass with a stale duplicate.

    The previous version of this file reproduced the archiver's ternary. That tests the copy:
    the production expression could be reordered and everything would stay green.
    """
    import inspect
    source = inspect.getsource(studio.run_explainer_task)
    assert "finished_library_format(" in source, \
        "run_explainer_task must call finished_library_format, not inline the decision"
    assert "directed-v1-pilot" not in source, \
        "the lane labels must live in finished_library_format only"


def test_library_fields_describe_the_lane_from_artifacts_the_run_already_wrote(tmp_path):
    manifest = tmp_path / "generation_manifest.json"
    manifest.write_text(json.dumps({
        "creative_lane": "illustrated_story_v1",
        "creative_profile": "ink_cut_paper_v1",
        "motion_mode": "stills",
        "illustrated_story": {"beat_count": 9, "location_count": 4},
        "music": {"status": "ready", "spec": {"mood": "wry_minor", "tempo_bpm": 96}},
    }), encoding="utf-8")
    storyboard = tmp_path / "illustrated_storyboard.json"
    storyboard.write_text(json.dumps({
        "story_engine": "backfiring_solution",
        "chapter_count": 5,
        "validation": {"passed": True, "errors": []},
    }), encoding="utf-8")

    fields = studio._illustrated_library_fields(
        {"generation_manifest_path": str(manifest), "storyboard_path": str(storyboard)},
        "illustrated_story")
    assert fields["creative_lane"] == "illustrated_story_v1"
    assert fields["creative_profile"] == "ink_cut_paper_v1"
    assert fields["story_engine"] == "backfiring_solution"
    assert fields["beat_count"] == 9 and fields["location_count"] == 4
    assert fields["chapter_count"] == 5
    assert fields["storyboard_validated"] is True
    assert fields["music_status"] == "ready"

    # A cinematic render must not grow illustrated fields.
    assert studio._illustrated_library_fields(
        {"generation_manifest_path": str(manifest)}, "cinematic") == {}


def test_a_failed_storyboard_is_reported_as_failed_not_omitted(tmp_path):
    """`False` must survive into the record; only genuinely absent facts may drop out.

    The filter that removes empty values used to be the place a validation failure could turn
    into a missing key, and a missing key reads in the UI as "no storyboard problem".
    """
    storyboard = tmp_path / "illustrated_storyboard.json"
    storyboard.write_text(json.dumps({"validation": {"passed": False, "errors": ["x"]}}),
                          encoding="utf-8")
    fields = studio._illustrated_library_fields(
        {"storyboard_path": str(storyboard)}, "illustrated_story")
    assert fields["storyboard_validated"] is False


def test_missing_or_corrupt_sidecars_never_block_archival(tmp_path):
    broken = tmp_path / "generation_manifest.json"
    broken.write_text("{not json", encoding="utf-8")
    fields = studio._illustrated_library_fields(
        {"generation_manifest_path": str(broken), "storyboard_path": str(tmp_path / "gone.json")},
        "illustrated_story")
    assert fields == {"creative_lane": "illustrated_story_v1"}


def _seed(tmp_path, rows: dict) -> None:
    index = {}
    for video_id, meta in rows.items():
        video = tmp_path / f"{video_id}.mp4"
        video.write_bytes(b"\x00" * 1024)
        index[video_id] = {**meta, "path": str(video)}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_the_lane_label_is_searchable(monkeypatch, tmp_path):
    """Searching the library by lane must find the lane.

    Both SQL list paths and the local fallback matched only title and id, so the label the
    archiver writes was the one thing you could not search for.
    """
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: False)
    monkeypatch.setattr(finished_api.artifact_store, "durable_storage_required", lambda: False)
    _seed(tmp_path, {
        "ill1": {"title": "Why the cane toad fix backfired", "format": "illustrated-story"},
        "quiz1": {"title": "Big cat shadow quiz", "format": "short-quiz"},
        "expl1": {"title": "How the internet works", "format": "explainer"},
    })
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            found = (await client.get("/api/finished", params={"q": "illustrated"})).json()
            assert [row["id"] for row in found["videos"]] == ["ill1"]
            assert found["videos"][0]["format"] == "illustrated-story"
            # The neighbouring lane still resolves by its own label.
            assert [row["id"] for row in
                    (await client.get("/api/finished", params={"q": "quiz"})).json()["videos"]
                    ] == ["quiz1"]
            # And an unfiltered list still returns everything.
            assert len((await client.get("/api/finished")).json()["videos"]) == 3

    anyio.run(run)


def test_lane_facts_survive_the_round_trip_into_the_library(monkeypatch, tmp_path):
    """Whatever the archiver puts in `meta` must be readable from /api/finished."""
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: False)
    monkeypatch.setattr(finished_api.artifact_store, "durable_storage_required", lambda: False)
    _seed(tmp_path, {"ill1": {
        "title": "Why the cane toad fix backfired",
        "format": studio.ILLUSTRATED_FINISHED_FORMAT,
        "visual_style": "illustrated_story",
        "story_engine": "backfiring_solution",
        "beat_count": 9, "location_count": 4, "storyboard_validated": True,
        "music_status": "ready", "rendered_contract_status": "REJECT",
        "rendered_contract_score": 69,
    }})
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            row = (await client.get("/api/finished")).json()["videos"][0]
            meta = row["metadata"]
            assert row["format"] == "illustrated-story"
            assert meta["visual_style"] == "illustrated_story"
            assert meta["story_engine"] == "backfiring_solution"
            assert meta["location_count"] == 4
            # The advisory rendered grade must reach the operator, not be swallowed by
            # status="done". The UI renders this next to the status pill.
            assert meta["rendered_contract_status"] == "REJECT"
            assert meta["rendered_contract_score"] == 69

    anyio.run(run)
