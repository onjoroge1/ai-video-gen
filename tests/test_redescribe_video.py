"""Re-describing a live film: the merge keeps the operator's lines, and --apply changes only the
description while every other snippet field goes back exactly as read. A fake client, no network."""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)
import redescribe_video as rd  # noqa: E402
import test_description_template as fixtures  # noqa: E402

PEOPLE = {"entries": [
    {"name": "Warwick Kerr", "line": "Brought African queens to Brazil in 1956."},
    {"name": "Rio Claro", "line": "Where twenty-six queens escaped a year later."},
]}


class _Call:
    def __init__(self, run):
        self._run = run

    def execute(self):
        return self._run()


class FakeYouTube:
    """videos().list / videos().update with YouTube's replace-the-snippet semantics."""

    def __init__(self, video, drop_on_update=()):
        self.video = copy.deepcopy(video)
        self.updates = []
        self.drop_on_update = drop_on_update

    def videos(self):
        return self

    def list(self, part, id):  # noqa: A002 - the API's own parameter name
        return _Call(lambda: {"items": [copy.deepcopy(self.video)]})

    def update(self, part, body):
        def run():
            self.updates.append((part, copy.deepcopy(body)))
            snippet = {k: v for k, v in self.video["snippet"].items() if k in rd.READ_ONLY_SNIPPET}
            snippet.update({k: v for k, v in body["snippet"].items() if k not in self.drop_on_update})
            self.video["snippet"] = snippet
            if "localizations" in body:
                self.video["localizations"] = body["localizations"]
            return {"id": body["id"]}
        return _Call(run)


def _video():
    return {"id": "VID12345678", "snippet": {
        "title": "The 26-Queen Mistake That Unleashed Killer Bees",
        "description": fixtures.LIVE,
        "tags": ["killer bees", "africanized bees", "bolt explains the world"],
        "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en-US",
        "publishedAt": "2026-10-01T00:00:00Z", "channelId": "UC1", "channelTitle": "Bolt",
        "liveBroadcastContent": "none", "thumbnails": {"default": {"url": "x"}},
        "localized": {"title": "t", "description": "d"}},
        "localizations": {"en": {"title": "The 26-Queen Mistake That Unleashed Killer Bees",
                                 "description": "old"},
                          "es": {"title": "El error", "description": "La descripción"}}}


def _propose():
    return rd.propose(fixtures.LIVE, fixtures._facts(), complete=lambda s, u: json.dumps(PEOPLE))


def test_the_merge_keeps_short_link_cta_hashtags_ai_line_and_custom_lines():
    new, report = _propose()
    for kept in ("Short version: https://youtube.com/shorts/abc123",
                 "Subscribe to Bolt Explains the World for illustrated true stories of fixes that backfired.",
                 "#KillerBees #Bees",
                 "🤖 Created with AI assistance, including synthetic narration and AI-generated "
                 "illustrations. Disclosed as altered/synthetic content.",
                 "What other animal introduction backfired? Tell us in the comments!",
                 "Killer bees began as a breeding experiment. In 1957, 26 African queens escaped.",
                 "0:54 The March North"):
        assert kept in new, kept
    assert "Every factual line in this film was checked" in new
    assert "📍 PEOPLE & PLACES IN THIS FILM\nWarwick Kerr — Brought African queens" in new
    for gone in ("IN THIS VIDEO", "QUESTIONS ANSWERED", "Tags:"):
        assert gone not in new
    assert report["people_listed"] == 2


def test_an_existing_people_section_is_rechecked_not_regenerated():
    new, _ = _propose()

    def no_call(system, user):
        raise AssertionError("the section already exists; no model call")
    again, report = rd.propose(new, fixtures._facts(), complete=no_call)
    assert again == new and report["people_generated"] is None


def test_preview_shows_the_proposal_the_diff_and_what_was_dropped():
    new, report = _propose()
    preview = rd.render_preview("VID12345678", "Title", fixtures.LIVE, new, report)
    assert "===== PROPOSED DESCRIPTION =====" in preview and "===== DIFF (live -> proposed) =====" in preview
    assert "-🔎 IN THIS VIDEO" in preview and "+📚 RESEARCH & SOURCES" in preview
    assert "https://unused.example/old-page" in preview, "dropped live sources are listed"


def test_apply_changes_only_the_description_and_preserves_every_other_field(tmp_path):
    new, report = _propose()
    yt = FakeYouTube(_video())
    log = tmp_path / "metadata_change_log.json"
    log.write_text(json.dumps({"entries": [{"date": "2026-10-13", "label": "earlier"}]}))
    record = rd.apply(yt, _video(), new, job="/jobs/bees", channel="world", log_path=str(log),
                      report=report)
    assert len(yt.updates) == 1
    part, body = yt.updates[0]
    sent = body["snippet"]
    original = _video()["snippet"]
    assert sent["description"] == new
    for key in ("title", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage"):
        assert sent[key] == original[key], key
    assert set(sent) == {k for k in original if k not in rd.READ_ONLY_SNIPPET}
    # The default-language localization mirrors the new text; other languages are untouched.
    assert part == "snippet,localizations"
    assert body["localizations"]["en"] == {"title": original["title"], "description": new}
    assert body["localizations"]["es"] == _video()["localizations"]["es"]
    assert record["verified"] is True and record["fields_changed_unexpectedly"] == []
    entries = json.loads(log.read_text())["entries"]
    assert len(entries) == 2 and entries[-1]["video_id"] == "VID12345678"
    assert entries[-1]["before_sha256"] == rd.sha256(fixtures.LIVE)
    assert entries[-1]["after_sha256"] == rd.sha256(new)
    assert open(entries[-1]["before_file"], encoding="utf-8").read() == fixtures.LIVE
    assert open(entries[-1]["after_file"], encoding="utf-8").read() == new


def test_apply_reports_a_field_youtube_did_not_keep(tmp_path):
    new, report = _propose()
    yt = FakeYouTube(_video(), drop_on_update=("tags",))
    record = rd.apply(yt, _video(), new, job="/jobs/bees", channel="world",
                      log_path=str(tmp_path / "log.json"), report=report)
    assert record["verified"] is False and record["fields_changed_unexpectedly"] == ["tags"]


def test_a_video_without_a_default_localization_updates_the_snippet_only():
    video = _video()
    video["localizations"] = {"es": video["localizations"]["es"]}
    part, body = rd.update_request(video, "new text")
    assert part == "snippet" and "localizations" not in body


def test_a_running_title_test_is_found_in_the_change_log(tmp_path):
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"entries": [
        {"video_id": "IN1DERNZ2zA", "label": "Title A/B test (Studio Test & Compare, title only) "
                                             "started on the History film, by operator request"}]}))
    assert rd.title_test_running(str(log), "IN1DERNZ2zA").startswith("Title A/B test")
    assert rd.title_test_running(str(log), "other") == ""
    data = json.loads(log.read_text())
    data["entries"].append({"video_id": "IN1DERNZ2zA", "label": "Title A/B test ended: winner B"})
    log.write_text(json.dumps(data))
    assert rd.title_test_running(str(log), "IN1DERNZ2zA") == ""


def test_main_checkout_root_finds_the_repository():
    root = rd.main_checkout_root()
    assert os.path.isdir(root) and os.path.basename(rd.default_log_path()) == "metadata_change_log.json"
