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
    """videos().list / videos().update with YouTube's replace-the-snippet semantics, and
    channels().list(mine=True) for the bound-channel check."""

    def __init__(self, video, drop_on_update=(), fail_read_back=False, channel_id="UC1"):
        self.video = copy.deepcopy(video)
        self.updates = []
        self.drop_on_update = drop_on_update
        self.fail_read_back = fail_read_back
        self.channel_id = channel_id
        self.lists = 0

    def videos(self):
        return self

    def channels(self):
        outer = self

        class _Channels:
            def list(self, part, mine):
                return _Call(lambda: {"items": [{"id": outer.channel_id,
                                                 "snippet": {"title": "Bolt"}}]})
        return _Channels()

    def list(self, part, id):  # noqa: A002 - the API's own parameter name
        def run():
            self.lists += 1
            if self.fail_read_back and self.updates:
                raise TimeoutError("read-back timed out")
            return {"items": [copy.deepcopy(self.video)]}
        return _Call(run)

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
    assert "https://unused.example/mites" in preview, "dropped live sources are listed"


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


# --- review fixes, 2026-10-14 ---------------------------------------------------------------------

def test_a_live_update_is_logged_even_when_the_read_back_fails(tmp_path):
    new, report = _propose()
    yt = FakeYouTube(_video(), fail_read_back=True)
    log = tmp_path / "metadata_change_log.json"
    record = rd.apply(yt, _video(), new, job="/jobs/bees", channel="world", log_path=str(log),
                      report=report)
    assert len(yt.updates) == 1 and record["verified"] is False
    assert "read_back_error" in record and record["status"] == "sent, read-back failed"
    entries = json.loads(log.read_text())["entries"]
    assert len(entries) == 1, "the send-time record is completed in place, not duplicated"
    assert entries[0]["after_sha256"] == rd.sha256(new) and "TimeoutError" in entries[0]["read_back_error"]


def test_an_unwritable_log_after_a_live_update_falls_back_to_a_file_beside_it(tmp_path):
    new, report = _propose()
    log = tmp_path / "metadata_change_log.json"
    log.write_text("{ not json")
    assert rd.log_readable(str(log)), "main() refuses before sending when the log is unparsable"
    record = rd.apply(FakeYouTube(_video()), _video(), new, job="/jobs/bees", channel="world",
                      log_path=str(log), report=report)
    assert ".unlogged-" in record["logged_to"]
    saved = json.loads(open(record["logged_to"]).read())
    assert saved["entries"][-1]["after_sha256"] == rd.sha256(new)
    assert log.read_text() == "{ not json", "the damaged log is left for the operator"


def _job(tmp_path, video_id="VID12345678", **files):
    job = tmp_path / "jobs" / "bees_v16b"
    job.mkdir(parents=True)
    (job / "_state.json").write_text(json.dumps({"script": fixtures._script()}))
    (job / "transcript.txt").write_text(fixtures.TRANSCRIPT)
    if video_id:
        (job / "youtube.json").write_text(json.dumps({"video_id": video_id, "channel": "world"}))
    for name, text in files.items():
        (job / name.replace("__", ".")).write_text(text)
    return job


def test_job_binding_reads_every_record_of_the_jobs_film(tmp_path):
    job = _job(tmp_path, video_id="AAAAAAAAAAA",
               teaser_package__json=json.dumps({"film_video_id": "CCCCCCCCCCC"}),
               short_description__txt="Why import it? Full film: https://youtu.be/DDDDDDDDDDD")
    (tmp_path / "jobs" / "yt").mkdir()
    (tmp_path / "jobs" / "yt" / "upload_ledger.json").write_text(json.dumps({"uploads": [
        {"video_id": "BBBBBBBBBBB", "file": "jobs/bees_v16b/explainer.recut.mp4"},
        {"video_id": "EEEEEEEEEEE", "file": "jobs/bees_v16b/teaser.mp4"},
        {"video_id": "FFFFFFFFFFF", "file": "jobs/other/explainer.mp4"}]}))
    binding = rd.job_binding(str(job))
    assert binding == {
        "AAAAAAAAAAA": {"source": "youtube.json", "cut": "original"},
        "BBBBBBBBBBB": {"source": "upload ledger (jobs/bees_v16b/explainer.recut.mp4)", "cut": "recut"},
        "CCCCCCCCCCC": {"source": "teaser_package.json film_video_id", "cut": ""},
        "DDDDDDDDDDD": {"source": "short_description.txt full-film link", "cut": ""}}


def test_a_video_that_is_not_the_jobs_film_is_refused_before_any_call(tmp_path, capsys):
    job = _job(tmp_path, video_id="hFk6YVSa0xk")
    # A copy-paste in a loop over the films: the carp video with the hippo job.
    assert rd.main(["eWJr_iwUNx4", "--job", str(job), "--log", str(tmp_path / "log.json")]) == 2
    out = capsys.readouterr().out
    assert "refused" in out and "hFk6YVSa0xk (youtube.json)" in out


def test_a_recut_job_needs_to_know_which_cut_is_live(tmp_path):
    job = _job(tmp_path, recut_opening__json=json.dumps({"splice_sec": 10, "scenes": [
        {"narration": "New opening.", "claim_refs": ["c4"]}]}), explainer__recut__mp4="")
    binding = {"VID12345678": {"source": "youtube.json", "cut": "original"},
               "CCCCCCCCCCC": {"source": "teaser_package.json film_video_id", "cut": ""}}
    assert rd.resolve_cut(str(job), "VID12345678", binding, "auto") == (
        False, "youtube.json records the original cut")
    try:
        rd.resolve_cut(str(job), "CCCCCCCCCCC", binding, "auto")
    except ValueError as exc:
        assert "--cut" in str(exc)
    else:
        raise AssertionError("an unrecorded cut of a recut job must not be guessed")
    assert rd.resolve_cut(str(job), "CCCCCCCCCCC", binding, "recut")[0] is True
    assert rd.resolve_cut(str(_job(tmp_path / "plain")), "X", {}, "auto")[0] is False


class _Modules:
    """Stand-ins for the imports main() makes once the video is bound: no credentials, no .env."""

    def __init__(self, monkeypatch, yt):
        import types
        monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
        monkeypatch.setitem(sys.modules, "googleapiclient.discovery",
                            types.SimpleNamespace(build=lambda *a, **k: yt))
        monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
        monkeypatch.setitem(sys.modules, "youtube_upload", types.SimpleNamespace(_creds=lambda ch: None))
        import youtube_channels
        monkeypatch.setitem(youtube_channels.CHANNELS, "world",
                            {"id": "UC1", "title": "Bolt", "token_env": "X"})


def test_apply_publishes_exactly_the_reviewed_proposal_and_makes_no_model_call(tmp_path, monkeypatch):
    job = _job(tmp_path)
    yt = FakeYouTube(_video())
    _Modules(monkeypatch, yt)
    log = tmp_path / "jobs" / "yt" / "metadata_change_log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    proposal = tmp_path / "review" / "proposal.json"
    calls = []
    monkeypatch.setattr(rd.dt, "anthropic_complete",
                        lambda *a, **k: (lambda s, u: calls.append(1) or json.dumps(PEOPLE)))
    assert rd.main(["VID12345678", "--job", str(job), "--log", str(log),
                    "--proposal", str(proposal)]) == 0
    assert len(calls) == 1 and not yt.updates
    reviewed = json.loads(proposal.read_text())
    assert reviewed["live_sha256"] == rd.sha256(fixtures.LIVE)
    # The apply: no second model call, and the text sent is the one reviewed.
    assert rd.main(["VID12345678", "--job", str(job), "--log", str(log),
                    "--proposal", str(proposal), "--apply"]) == 0
    assert len(calls) == 1, "--apply never calls the model"
    assert yt.updates[0][1]["snippet"]["description"] == reviewed["proposed"]
    entry = json.loads(log.read_text())["entries"][-1]
    assert entry["job_binding"] == "youtube.json" and entry["status"] == "verified"


def test_apply_refuses_without_a_proposal_or_when_the_live_text_moved(tmp_path, monkeypatch, capsys):
    job = _job(tmp_path)
    yt = FakeYouTube(_video())
    _Modules(monkeypatch, yt)
    log = tmp_path / "log.json"
    proposal = tmp_path / "proposal.json"
    args = ["VID12345678", "--job", str(job), "--log", str(log), "--proposal", str(proposal)]
    assert rd.main(args + ["--apply"]) == 1
    assert "no reviewed proposal" in capsys.readouterr().out
    assert rd.main(args + ["--no-people"]) == 0
    yt.video["snippet"]["description"] += "\n\nAn operator edit in Studio."
    assert rd.main(args + ["--apply"]) == 1
    assert "changed since the dry run" in capsys.readouterr().out
    assert not yt.updates
    data = json.loads(proposal.read_text())
    data["proposed"] += " tampered"
    proposal.write_text(json.dumps(data))
    try:
        rd.load_proposal(str(proposal), video_id="VID12345678", job=str(job),
                         live=yt.video["snippet"]["description"], facts=fixtures._facts())
    except ValueError as exc:
        assert "altered" in str(exc)
    else:
        raise AssertionError("an edited proposal is not the reviewed one")


def test_a_video_on_another_channel_is_refused(tmp_path, monkeypatch, capsys):
    job = _job(tmp_path)
    video = _video()
    video["snippet"]["channelId"] = "UC_someone_else"
    yt = FakeYouTube(video)
    _Modules(monkeypatch, yt)
    assert rd.main(["VID12345678", "--job", str(job), "--log", str(tmp_path / "l.json"),
                    "--proposal", str(tmp_path / "p.json"), "--no-people"]) == 2
    assert "belongs to channel UC_someone_else" in capsys.readouterr().out
