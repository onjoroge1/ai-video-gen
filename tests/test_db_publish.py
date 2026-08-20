import db


class _Cursor:
    def __init__(self, manifest=None):
        self.manifest = manifest
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return self.manifest


class _Connection:
    def __init__(self, manifest=None):
        self.cur = _Cursor(manifest)
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_publish_video_bundle_writes_binary_and_documents(tmp_path, monkeypatch):
    video = tmp_path / "quiz.mp4"
    description = tmp_path / "description.txt"
    captions = tmp_path / "captions.srt"
    transcript = tmp_path / "transcript.txt"
    video.write_bytes(b"video-bytes")
    description.write_text("description", encoding="utf-8")
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    transcript.write_text("Hello", encoding="utf-8")
    conn = _Connection()
    monkeypatch.setattr(db, "_conn", lambda: conn)

    assert db.publish_video_bundle(
        slug="animal-shadows",
        title="Animal Shadows",
        video_path=str(video),
        description_path=str(description),
        captions_path=str(captions),
        transcript_path=str(transcript),
        duration_sec=11.0,
        metadata={"version": "2.1"},
    )
    assert conn.committed
    insert_params = conn.cur.calls[-1][1]
    assert insert_params[0:4] == ("animal-shadows", "Animal Shadows", "quiz", "quiz.mp4")
    assert insert_params[5] == len(b"video-bytes")
    assert insert_params[8] == "description"
    assert insert_params[10].startswith("1\n00:00:00,000")


def test_publish_video_bundle_rejects_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_conn", lambda: (_ for _ in ()).throw(AssertionError("no DB call")))
    assert not db.publish_video_bundle(
        slug="missing",
        title="Missing",
        video_path=str(tmp_path / "missing.mp4"),
        description_path=str(tmp_path / "missing.txt"),
        captions_path=str(tmp_path / "missing.srt"),
    )
