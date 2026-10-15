"""New films get the description template from the pipeline itself, and the uploader applies it
to a job's description.txt. Stubbed provider; no network."""
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

import description_template as dt  # noqa: E402
import explainer_pipeline as ep  # noqa: E402
import test_description_template as fixtures  # noqa: E402
import upload_job  # noqa: E402

DESCRIPTION_REPLY = {
    "summary": "Killer bees began as a breeding experiment in Brazil.\n\nThe film follows the escape.",
    "chapters": [{"scene": 1, "title": "The import"}, {"scene": 2, "title": "The escape"},
                 {"scene": 3, "title": "The march north"}],
    "in_this_video": ["a retired bullet"], "questions_answered": ["A retired question?"],
    "hashtags": ["KillerBees", "BeeHistory"],
    "tags": ["killer bees explained", "africanized bees"]}
PEOPLE_REPLY = {"entries": [
    {"name": "Warwick Kerr", "line": "Brought African queens to Brazil in 1956."},
    {"name": "Rio Claro", "line": "Where twenty-six queens escaped a year later."},
    {"name": "Texas", "line": "Reached by 1985."}]}


def _provider(monkeypatch, calls):
    def create(**kwargs):
        calls.append(kwargs)
        reply = PEOPLE_REPLY if kwargs.get("model") == dt.PEOPLE_MODEL else DESCRIPTION_REPLY
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(reply))],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200))
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_the_pipeline_writes_the_template_with_research_people_and_promise(monkeypatch, tmp_path):
    calls, costs = [], []
    _provider(monkeypatch, calls)
    script = fixtures._script()
    research = dt.film_research(script, fixtures.TRANSCRIPT)
    path = ep.generate_description("Title", "Hook.", fixtures.TRANSCRIPT, str(tmp_path),
                                   cost_sink=costs, question="q", video_format="landscape",
                                   scene_narr=[s["narration"] for s in fixtures.SCENES],
                                   scene_durs=[12.0, 12.0, 12.0], research=research)
    text = open(path, encoding="utf-8").read().strip()
    order = [text.index(m) for m in ("Killer bees began", dt.promise_line("checked"), "⏱️ CHAPTERS",
                                     dt.RESEARCH_HEADER, dt.PEOPLE_HEADER, "Subscribe for clear",
                                     "#KillerBees", "🤖 Created with AI assistance")]
    assert order == sorted(order)
    assert "IN THIS VIDEO" not in text and "QUESTIONS" not in text and "Tags:" not in text
    assert "↳ In 1957, 26 African queens escaped" in text
    assert "Texas — Reached by 1985." not in text, "the fact check dropped the wrong year"
    assert "unused.example" not in text
    # One description call, one People & Places call on the cheap model, both costed.
    assert [c["model"] for c in calls] == [ep.ANTHROPIC_MODEL, dt.PEOPLE_MODEL]
    assert calls[1]["thinking"] == {"type": "disabled"}
    assert len(costs) == 2 and costs[1] < costs[0]
    assert json.load(open(tmp_path / ep.PIPELINE_TAGS_FILE))["tags"] == ["killer bees explained",
                                                                        "africanized bees"]
    report = json.load(open(tmp_path / "people_places.json"))
    assert report["dropped"][0]["line"].startswith("Texas")


def test_a_social_description_is_summary_hashtags_and_disclosure(monkeypatch, tmp_path):
    calls = []
    _provider(monkeypatch, calls)
    path = ep.generate_description("Title", "Hook.", "transcript", str(tmp_path),
                                   video_format="social")
    text = open(path, encoding="utf-8").read()
    assert "RESEARCH" not in text and "PEOPLE" not in text and "Tags:" not in text
    assert "#KillerBees" in text and len(calls) == 1


def test_upload_job_reads_pipeline_tags_and_falls_back_to_an_old_tags_line(tmp_path):
    (tmp_path / "description.txt").write_text("Hook.\n\nTags: a, b\n\n🤖 AI.\n")
    assert upload_job.pipeline_tags_of(str(tmp_path)) == ["a", "b"]
    (tmp_path / "pipeline_tags.json").write_text(json.dumps({"tags": ["x", "y"]}))
    assert upload_job.pipeline_tags_of(str(tmp_path)) == ["x", "y"]


def test_upload_job_applies_the_template_to_an_old_jobs_description(tmp_path):
    (tmp_path / "_state.json").write_text(json.dumps({"script": fixtures._script()}))
    (tmp_path / "transcript.txt").write_text(fixtures.TRANSCRIPT)
    calls = []

    def complete(system, user):
        calls.append(user)
        return json.dumps(PEOPLE_REPLY)
    body = upload_job.template_description(
        str(tmp_path), upload_job.upload_description(fixtures.LIVE, "world"), complete=complete,
        log=lambda *_: None)
    assert len(calls) == 1
    assert dt.RESEARCH_HEADER in body and dt.PEOPLE_HEADER in body and "Tags:" not in body
    assert "IN THIS VIDEO" not in body and "Short version: https://youtube.com/shorts/abc123" in body
    assert dt.utf8_len(body) <= dt.MAX_BYTES - upload_job.SHORT_LINE_ROOM + 1
    report = json.load(open(tmp_path / "description_template.json"))
    assert report["promise_kind"] == "checked" and report["people_listed"] == 2


def test_upload_job_without_research_only_strips_the_retired_sections(tmp_path):
    def no_call(system, user):
        raise AssertionError("no research, no People & Places call")
    body = upload_job.template_description(str(tmp_path), fixtures.LIVE, complete=no_call,
                                           log=lambda *_: None)
    assert "IN THIS VIDEO" not in body and "📚 SOURCES" in body and "Tags:" not in body
